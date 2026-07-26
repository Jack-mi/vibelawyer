"""原子化工具集（SDK MCP in-process tools）.

设计原则:
  - 读工具：只读卷宗，返回带页码的文本/图像，绝不替 agent 下结论。
  - 写工具：向 CaseWorkspace 登记一条结构化记录，强制带来源引用（卷宗名+页码），
    写入前即时校验页码合法性，落实“禁止幻觉、结论可回溯”。
  - 校验/导出工具：validate_citations 检查所有引用；write_outputs 生成 Word/Excel。

工具通过 create_sdk_mcp_server 注册为进程内 MCP server，主 agent 与各子 agent 共享。
字段必填性：来源卷宗名/页码等追溯骨架字段 required，其余 NotRequired，便于 agent
按卷宗实际载明情况灵活登记。
"""
from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict

from claude_agent_sdk import tool

from .config import CaseConfig
from .pdf_volume import VolumeStore
from .workspace import (
    CaseWorkspace,
    CatalogEntry,
    ChargedFact,
    Citation,
    Conclusions,
    DocumentaryEvidence,
    IndictmentInfo,
    PartyInfo,
    ProceduralDoc,
    Statement,
    get_workspace,
    reset_workspace,
)

# ---------------------------------------------------------------------------
# 进程级状态
# ---------------------------------------------------------------------------

_STORE: VolumeStore | None = None
_CFG: CaseConfig | None = None


def init_tools(cfg: CaseConfig, *, use_docling: bool = True, verbose: bool = False) -> CaseWorkspace:
    """初始化工具层：预转换 docling 缓存、建立卷宗存储、重置工作区、登记各卷页数.

    use_docling=True 时，优先用 docling（RapidOCR）预转换全部卷宗为按页文本并缓存；
    docling 不可用时自动回退到 pypdfium2 文本层 + tesseract。
    """
    global _STORE, _CFG
    _CFG = cfg
    import os
    if os.environ.get("VIBELAWYER_NO_DOCLING"):
        use_docling = False
    docling_dir = None
    if use_docling:
        from . import docling_cache
        if docling_cache.docling_available():
            docling_dir = docling_cache.cache_dir_for(cfg.output_dir)
            # 仅在无缓存时构建（避免重复转换）
            have = all(docling_cache.get_cached_page_count(v.name, docling_dir) is not None
                       for v in cfg.volumes) if cfg.volumes else False
            if not have:
                print("[init] 预转换 docling 缓存（首次较慢，模型加载+OCR）...", flush=True)
                docling_cache.build_docling_cache(cfg.volumes, docling_dir, verbose=verbose)
            else:
                print("[init] docling 缓存已存在，复用", flush=True)
        else:
            print("[init] docling 不可用，回退 tesseract OCR", flush=True)
    _STORE = VolumeStore(cfg, docling_cache_dir=docling_dir)
    ws = reset_workspace()
    for v in cfg.volumes:
        ws.register_volume(v.name, _STORE.page_count(v.name))
    ws.volume_count = len(cfg.volumes)
    return ws


def _store() -> VolumeStore:
    if _STORE is None:
        raise RuntimeError("工具未初始化，请先 init_tools(cfg)")
    return _STORE


def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _err(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def _cite(volume, p_start, p_end, context="") -> Citation:
    return Citation(
        volume=str(volume),
        page_start=int(p_start),
        page_end=int(p_end if p_end is not None else p_start),
        context=context,
    )


# ===========================================================================
# 读工具
# ===========================================================================


@tool(
    "list_volumes",
    "列出本案全部卷宗：卷宗名称、文件名、总页数。阅卷第一步应先调用此工具掌握卷宗全貌。",
    {},
)
async def list_volumes(args: dict) -> dict:
    inv = _store().volume_inventory()
    lines = [f"本案共 {len(inv)} 册卷宗："]
    for i, v in enumerate(inv, 1):
        lines.append(f"  {i}. 《{v['name']}》 文件:{v['file']} 页数:{v['pages']}")
    lines.append("\n提示：用 read_pages(volume, start_page, end_page) 阅读具体页；"
                 "用 get_volume_outline(volume) 获取逐页概要以快速定位文书。")
    return _ok("\n".join(lines))


class ReadPagesInput(TypedDict):
    volume: Annotated[str, "卷宗名称（见 list_volumes 的名称，如：刑事侦查案卷）"]
    start_page: Annotated[int, "起始页码（1-based，含）"]
    end_page: Annotated[int, "结束页码（1-based，含）"]


@tool(
    "read_pages",
    "读取指定卷宗的某一页码区间文本，每页标注页码。扫描件/乱码页会自动经本地中文OCR提取文字，"
    "故大多数页面可直接拿到可读文本。仅当某页仍提示 needs_ocr（OCR失败/空白页）时，才需改用 "
    "get_page_image 视觉识别（若环境支持视觉）或如实标注内容无法识别。所有引用须以 "
    "见《卷名》P起-止 的格式回溯到此处读取的页码。",
    ReadPagesInput,
)
async def read_pages(args: dict) -> dict:
    try:
        pages = _store().read_pages(args["volume"], int(args["start_page"]), int(args["end_page"]))
    except (KeyError, IndexError) as e:
        return _err(str(e))
    chunks = []
    ocr_pages: list[int] = []
    for pt in pages:
        if pt.needs_ocr:
            chunks.append(f"《{pt.volume}》 P{pt.page}（{pt.char_count}字，⚠OCR后仍无可用文本，疑似空白页；可尝试 get_page_image 视觉识别或标注内容无法识别）")
            ocr_pages.append(pt.page)
        else:
            chunks.append(f"《{pt.volume}》 P{pt.page}（{pt.char_count}字）\n{pt.text}")
    text = "\n\n---\n\n".join(chunks)
    note = ""
    if ocr_pages:
        note = (f"\n\n提示：P{ocr_pages} OCR后仍无文本，可能为空白页或图像损坏；"
                "可调用 get_page_image 视觉确认，或如实标注。")
    return _ok(text + note)


class SearchInput(TypedDict):
    query: Annotated[str, "检索关键词（如人名、金额、罪名、日期）"]
    volume: NotRequired[Annotated[str, "可选：限定在某卷内检索；留空则跨全部卷宗"]]


@tool(
    "search_volumes",
    "在卷宗中检索关键词，返回命中卷宗/页码与上下文片段。用于快速定位某事实、某人的所有出现位置。",
    SearchInput,
)
async def search_volumes(args: dict) -> dict:
    query = (args.get("query") or "").strip()
    volume = (args.get("volume") or "").strip()
    if not query:
        return _err("query 不能为空")
    if volume:
        try:
            hits = _store().get(volume).search(query)
        except KeyError as e:
            return _err(str(e))
    else:
        hits = _store().search_all(query)
    if not hits:
        return _ok(f"未检索到“{query}”的命中。")
    lines = [f"检索“{query}”命中 {len(hits)} 处："]
    for i, h in enumerate(hits[:60], 1):
        lines.append(f"  {i}. 《{h['volume']}》P{h['page']}: …{h['snippet']}…")
    if len(hits) > 60:
        lines.append(f"  …另有 {len(hits) - 60} 处命中未显示")
    return _ok("\n".join(lines))


class OutlineInput(TypedDict):
    volume: Annotated[str, "卷宗名称"]
    max_pages: NotRequired[Annotated[int, "可选：最多概览多少页，默认全部"]]


@tool(
    "get_volume_outline",
    "获取某卷的逐页概览（每页字数 + 首行内容），用于在大卷中快速定位文书边界，"
    "再决定 read_pages 精读哪些页。",
    OutlineInput,
)
async def get_volume_outline(args: dict) -> dict:
    try:
        vol = _store().get(args["volume"])
    except KeyError as e:
        return _err(str(e))
    total = vol.page_count()
    max_pages = int(args.get("max_pages") or total)
    n = min(total, max_pages)
    lines = [f"《{vol.name}》 共 {total} 页，概览前 {n} 页："]
    for p in range(1, n + 1):
        pt = vol.get_page_text(p)
        first = (pt.text or "").strip().split("\n", 1)[0][:50]
        flag = " ⚠无文本层" if pt.needs_ocr else ""
        lines.append(f"  P{p} [{pt.char_count}字{flag}] {first}")
    return _ok("\n".join(lines))


class PageImageInput(TypedDict):
    volume: Annotated[str, "卷宗名称"]
    page: Annotated[int, "页码（1-based）"]


@tool(
    "get_page_image",
    "将指定页渲染为图片返回（用于扫描件无文本层时的视觉识别）。模型应直接‘看图’"
    "提取文字与结构信息，再通过对应 record_* 工具登记。",
    PageImageInput,
)
async def get_page_image(args: dict) -> dict:
    try:
        vol = _store().get(args["volume"])
        page = int(args["page"])
        b64, mime = vol.get_page_image_b64(page)
    except (KeyError, IndexError) as e:
        return _err(str(e))
    return {
        "content": [
            {"type": "text", "text": f"《{vol.name}》P{page} 图像如下，请视觉识别其内容："},
            {"type": "image", "data": b64, "mimeType": mime},
        ]
    }


# ===========================================================================
# 写工具（登记结构化记录）
# ===========================================================================


class CaseBasicInput(TypedDict):
    case_name: NotRequired[Annotated[str, "案件名称"]]
    defendant: NotRequired[Annotated[str, "当事人/被告人姓名"]]
    charge: NotRequired[Annotated[str, "涉嫌罪名"]]
    total_amount: NotRequired[Annotated[str, "涉案总金额（如：人民币83万元）"]]
    volume_count: NotRequired[Annotated[int, "卷宗数量"]]


@tool(
    "set_case_basic",
    "登记案件基本信息表：主体、涉嫌罪名、涉案金额、卷宗数量。",
    CaseBasicInput,
)
async def set_case_basic(args: dict) -> dict:
    ws = get_workspace()
    if args.get("case_name") is not None:
        ws.case_name = args["case_name"]
    if args.get("defendant") is not None:
        ws.defendant = args["defendant"]
    if args.get("charge") is not None:
        ws.charge = args["charge"]
    if args.get("total_amount") is not None:
        ws.total_amount = args["total_amount"]
    if args.get("volume_count"):
        ws.volume_count = int(args["volume_count"])
    return _ok(f"已登记案件基本信息：{ws.case_name} / 当事人:{ws.defendant} / 罪名:{ws.charge} / 金额:{ws.total_amount} / 卷数:{ws.volume_count}")


class PartyInput(TypedDict):
    name: Annotated[str, "姓名"]
    volume: Annotated[str, "来源卷宗"]
    page_start: Annotated[int, "来源起始页"]
    page_end: Annotated[int, "来源结束页"]
    gender: NotRequired[Annotated[str, "性别"]]
    ethnicity: NotRequired[Annotated[str, "民族"]]
    birth: NotRequired[Annotated[str, "出生日期"]]
    native_place: NotRequired[Annotated[str, "籍贯"]]
    id_no: NotRequired[Annotated[str, "身份证号"]]
    education: NotRequired[Annotated[str, "文化程度"]]
    occupation: NotRequired[Annotated[str, "职业"]]
    position: NotRequired[Annotated[str, "职务（职务犯罪必填）"]]
    appointment_history: NotRequired[Annotated[str, "任职履历，多条用分号分隔"]]
    address: NotRequired[Annotated[str, "住址"]]


@tool(
    "record_party",
    "登记当事人基本情况（第一部分）。职务犯罪须填 position 与 appointment_history。",
    PartyInput,
)
async def record_party(args: dict) -> dict:
    ws = get_workspace()
    c = _cite(args["volume"], args.get("page_start"), args.get("page_end"), "当事人基本情况")
    ws.party = PartyInfo(
        name=args.get("name", ""),
        gender=args.get("gender", ""),
        ethnicity=args.get("ethnicity", ""),
        birth=args.get("birth", ""),
        native_place=args.get("native_place", ""),
        id_no=args.get("id_no", ""),
        education=args.get("education", ""),
        occupation=args.get("occupation", ""),
        position=args.get("position", ""),
        appointment_history=[s.strip() for s in (args.get("appointment_history") or "").split(";") if s.strip()],
        address=args.get("address", ""),
        source=c,
    )
    ok, msg = ws.validate_citation(c)
    return _ok(f"已登记当事人 {ws.party.name}（来源{c.render()}，校验:{msg}）")


class IndictmentInput(TypedDict):
    doc_type: Annotated[str, "文书类型：起诉书 / 起诉意见书"]
    volume: Annotated[str, "来源卷宗"]
    page_start: Annotated[int, "来源起始页"]
    page_end: Annotated[int, "来源结束页"]
    defendant: NotRequired[Annotated[str, "被指控人"]]
    charge: NotRequired[Annotated[str, "涉嫌罪名"]]
    total_amount: NotRequired[Annotated[str, "涉案总金额"]]
    issuer: NotRequired[Annotated[str, "制作机关"]]
    issue_date: NotRequired[Annotated[str, "落款日期"]]
    legal_basis: NotRequired[Annotated[str, "适用法律条文，多条分号分隔"]]
    full_text_summary: NotRequired[Annotated[str, "指控事实全文摘录（原样复制涉及被告人的事实）"]]


@tool(
    "record_indictment",
    "登记起诉书/起诉意见书内容（第二部分）。full_text_summary 应原样复制涉及被告人的指控事实。",
    IndictmentInput,
)
async def record_indictment(args: dict) -> dict:
    ws = get_workspace()
    c = _cite(args["volume"], args.get("page_start"), args.get("page_end"), "起诉书/起诉意见书")
    ws.indictment = IndictmentInfo(
        doc_type=args.get("doc_type", ""),
        issuer=args.get("issuer", ""),
        issue_date=args.get("issue_date", ""),
        defendant=args.get("defendant", ""),
        charge=args.get("charge", ""),
        total_amount=args.get("total_amount", ""),
        legal_basis=[s.strip() for s in (args.get("legal_basis") or "").split(";") if s.strip()],
        full_text_summary=args.get("full_text_summary", ""),
        source=c,
    )
    if not ws.charge:
        ws.charge = ws.indictment.charge
    if not ws.defendant:
        ws.defendant = ws.indictment.defendant
    return _ok(f"已登记{ws.indictment.doc_type}（来源{c.render()}）")


class ChargedFactInput(TypedDict):
    index: Annotated[int, "第几笔事实（从1开始）"]
    description: Annotated[str, "该笔事实概述：时间/地点/人物/行为/金额"]
    volume: Annotated[str, "来源卷宗"]
    page_start: Annotated[int, "来源起始页"]
    page_end: Annotated[int, "来源结束页"]
    amount: NotRequired[Annotated[str, "该笔涉案金额"]]
    time_period: NotRequired[Annotated[str, "行为发生时间"]]


@tool("add_charged_fact", "登记起诉书指控的单笔事实（第三/四部分的整理依据）。", ChargedFactInput)
async def add_charged_fact(args: dict) -> dict:
    ws = get_workspace()
    c = _cite(args["volume"], args.get("page_start"), args.get("page_end"), f"指控事实第{args['index']}笔")
    ws.indictment.facts.append(
        ChargedFact(
            index=int(args["index"]),
            description=args.get("description", ""),
            amount=args.get("amount", ""),
            time_period=args.get("time_period", ""),
            source=c,
        )
    )
    return _ok(f"已登记指控事实第{args['index']}笔（来源{c.render()}）")


class StatementInput(TypedDict):
    person: Annotated[str, "供述/证言人姓名"]
    role: Annotated[str, "defendant / codefendant / witness 之一"]
    volume: Annotated[str, "卷宗"]
    page_start: Annotated[int, "起始页"]
    page_end: Annotated[int, "结束页"]
    record_time: NotRequired[Annotated[str, "笔录时间"]]
    investigators: NotRequired[Annotated[str, "办案人员"]]
    location: NotRequired[Annotated[str, "办案地点"]]
    has_av_recording: NotRequired[Annotated[str, "是否同步录音录像：是/否/未注明"]]
    charged_fact_ref: NotRequired[Annotated[str, "对应指控事实，如 第1笔；多笔分号分隔"]]
    content_summary: NotRequired[Annotated[str, "笔录内容摘要（含关键供述/辩解）"]]


@tool("record_statement", "登记供述/辩解或证言。role=defendant(被告人)/codefendant(同案人)/witness(证人)。"
     "须提取笔录时间、办案人员、办案地点、是否同步录音录像、笔录内容。",
     StatementInput)
async def record_statement(args: dict) -> dict:
    ws = get_workspace()
    role = (args.get("role") or "defendant").strip()
    c = _cite(args["volume"], args.get("page_start"), args.get("page_end"), f"{role}:{args.get('person')}")
    st = Statement(
        person=args.get("person", ""),
        role=role,
        volume=args["volume"],
        page_start=int(args.get("page_start") or 0),
        page_end=int(args.get("page_end") or 0),
        record_time=args.get("record_time", ""),
        investigators=args.get("investigators", ""),
        location=args.get("location", ""),
        has_av_recording=args.get("has_av_recording", "未注明"),
        charged_fact_ref=args.get("charged_fact_ref", ""),
        content_summary=args.get("content_summary", ""),
        source=c,
    )
    if role == "codefendant":
        ws.codefendant_statements.append(st)
    elif role == "witness":
        ws.witness_statements.append(st)
    else:
        ws.defendant_statements.append(st)
    ok, msg = ws.validate_citation(c)
    return _ok(f"已登记{role}笔录:{st.person} {c.render()}（校验:{msg}）")


class ProceduralInput(TypedDict):
    doc_type: Annotated[str, "文书类型：立案决定书/拘留/逮捕/取保候审/监视居住/搜查/扣押/鉴定意见/移送起诉等"]
    volume: Annotated[str, "卷宗"]
    page_start: Annotated[int, "起始页"]
    page_end: Annotated[int, "结束页"]
    time: NotRequired[Annotated[str, "具体时间"]]
    location: NotRequired[Annotated[str, "具体地点"]]
    content_summary: NotRequired[Annotated[str, "文书主要内容"]]


@tool("record_procedural_doc", "登记程序性文书（第六部分）。包含从被调查至当前的全部程序性文书，需含时间、地点。",
      ProceduralInput)
async def record_procedural_doc(args: dict) -> dict:
    ws = get_workspace()
    c = _cite(args["volume"], args.get("page_start"), args.get("page_end"), f"程序性文书:{args['doc_type']}")
    ws.procedural_docs.append(
        ProceduralDoc(
            doc_type=args.get("doc_type", ""),
            volume=args["volume"],
            page_start=int(args.get("page_start") or 0),
            page_end=int(args.get("page_end") or 0),
            time=args.get("time", ""),
            location=args.get("location", ""),
            content_summary=args.get("content_summary", ""),
            source=c,
        )
    )
    ok, msg = ws.validate_citation(c)
    return _ok(f"已登记程序性文书:{args['doc_type']} {c.render()}（校验:{msg}）")


class EvidenceInput(TypedDict):
    name: Annotated[str, "文件名称"]
    volume: Annotated[str, "卷宗"]
    page_start: Annotated[int, "起始页"]
    page_end: Annotated[int, "结束页"]
    time: NotRequired[Annotated[str, "形成时间"]]
    source: NotRequired[Annotated[str, "来源/制作主体"]]
    content_summary: NotRequired[Annotated[str, "主要内容"]]


@tool("record_documentary_evidence", "登记书证（第七部分，客观证据）。须列明时间、文件名称、卷宗页码、主要内容。",
      EvidenceInput)
async def record_documentary_evidence(args: dict) -> dict:
    ws = get_workspace()
    c = _cite(args["volume"], args.get("page_start"), args.get("page_end"), f"书证:{args['name']}")
    ws.documentary_evidence.append(
        DocumentaryEvidence(
            name=args.get("name", ""),
            volume=args["volume"],
            page_start=int(args.get("page_start") or 0),
            page_end=int(args.get("page_end") or 0),
            time=args.get("time", ""),
            source=args.get("source", ""),
            content_summary=args.get("content_summary", ""),
            source_ref=c,
        )
    )
    ok, msg = ws.validate_citation(c)
    return _ok(f"已登记书证:{args['name']} {c.render()}（校验:{msg}）")


class CatalogInput(TypedDict):
    volume_name: Annotated[str, "卷宗名称"]
    file_name: Annotated[str, "本卷所含文件名称"]
    page_range: NotRequired[Annotated[str, "本卷页码区间，如 1-50"]]
    doc_type: NotRequired[Annotated[str, "文书类型"]]
    record_time: NotRequired[Annotated[str, "笔录时间（如有）"]]
    note: NotRequired[Annotated[str, "备注"]]


@tool("add_catalog_entry", "登记阅卷目录（卷宗目录）一条：卷宗名称、页码、所含文件、笔录时间等。",
      CatalogInput)
async def add_catalog_entry(args: dict) -> dict:
    ws = get_workspace()
    ws.catalog.append(
        CatalogEntry(
            volume_name=args.get("volume_name", ""),
            page_range=args.get("page_range", ""),
            file_name=args.get("file_name", ""),
            doc_type=args.get("doc_type", ""),
            record_time=args.get("record_time", ""),
            note=args.get("note", ""),
        )
    )
    return _ok(f"已登记目录条目:{args.get('volume_name')} / {args.get('file_name')}")


class ConclusionsInput(TypedDict):
    core_facts: NotRequired[Annotated[str, "已查明核心事实，多条分号分隔"]]
    evidence_chain: NotRequired[Annotated[str, "证据链条，多条分号分隔"]]
    contradictions: NotRequired[Annotated[str, "证据矛盾点，多条分号分隔"]]
    doubts: NotRequired[Annotated[str, "待核查疑点，多条分号分隔"]]


@tool("record_conclusions", "登记阅卷结论：核心事实、证据链条、矛盾点、待核查疑点。供后续辩护意见参考。",
      ConclusionsInput)
async def record_conclusions(args: dict) -> dict:
    ws = get_workspace()

    def split(s: str) -> list[str]:
        return [x.strip() for x in (s or "").split(";") if x.strip()]

    ws.conclusions = Conclusions(
        core_facts=split(args.get("core_facts", "")),
        evidence_chain=split(args.get("evidence_chain", "")),
        contradictions=split(args.get("contradictions", "")),
        doubts=split(args.get("doubts", "")),
    )
    return _ok(f"已登记阅卷结论：核心事实{len(ws.conclusions.core_facts)}条 / 矛盾点{len(ws.conclusions.contradictions)}条 / 疑点{len(ws.conclusions.doubts)}条")


# ===========================================================================
# 校验与导出工具
# ===========================================================================


@tool("validate_citations", "校验所有已登记记录的来源引用是否落在真实卷宗页码区间内，返回不合规项。阅卷结束前必跑。",
      {})
async def validate_citations(args: dict) -> dict:
    ws = get_workspace()
    problems = ws.validate_all()
    counts = _count_records(ws)
    total = 1 + 1 + len(ws.indictment.facts) + counts["defendant"] + counts["codefendant"] + counts["witness"] + len(ws.procedural_docs) + len(ws.documentary_evidence)
    if not problems:
        return _ok(f"✓ 全部 {total} 条记录的来源引用校验通过，无幻觉页码。")
    lines = [f"发现 {len(problems)} 处来源引用不合规（共 {total} 条记录）："]
    for p in problems:
        lines.append(f"  - [{p['record']}] {p['issue']}")
    return _ok("\n".join(lines))


@tool("get_workspace_summary", "查看当前阅卷工作区进度：各部分已登记记录数与案件基本信息。", {})
async def get_workspace_summary(args: dict) -> dict:
    ws = get_workspace()
    c = _count_records(ws)
    lines = [
        f"案件:{ws.case_name or '(未登记)'} | 当事人:{ws.defendant or '(未登记)'} | 罪名:{ws.charge or '(未登记)'} | 金额:{ws.total_amount or '(未登记)'} | 卷数:{ws.volume_count}",
        "各部分登记数：",
        f"  一.当事人基本情况: {1 if ws.party.name else 0}",
        f"  二.起诉书/起诉意见书: {1 if ws.indictment.doc_type else 0}（指控事实 {len(ws.indictment.facts)} 笔）",
        f"  三.被告人供述: {c['defendant']}",
        f"  四.同案人供述: {c['codefendant']}",
        f"  五.证人证言: {c['witness']}",
        f"  六.程序性文书: {len(ws.procedural_docs)}",
        f"  七.书证: {len(ws.documentary_evidence)}",
        f"  阅卷目录条目: {len(ws.catalog)}",
        f"  阅卷结论: 核心{len(ws.conclusions.core_facts)}/矛盾{len(ws.conclusions.contradictions)}/疑点{len(ws.conclusions.doubts)}",
    ]
    return _ok("\n".join(lines))


class WriteOutputInput(TypedDict):
    fmt: NotRequired[Annotated[str, "输出格式：all / docx / xlsx，默认 all"]]


@tool("write_outputs", "生成阅卷笔录(Word)与阅卷目录(Excel)（含案件信息表与结论），返回文件路径。",
      WriteOutputInput)
async def write_outputs(args: dict) -> dict:
    if _CFG is None:
        return _err("未初始化案件配置")
    from .generators.docx_notes import generate_review_notes
    from .generators.xlsx_catalog import generate_catalog_xlsx

    ws = get_workspace()
    out_dir = _CFG.ensure_output_dir()
    fmt = (args.get("fmt") or "all").strip()
    paths = []
    if fmt in ("all", "docx"):
        p = generate_review_notes(ws, out_dir)
        paths.append(f"阅卷笔录(Word): {p}")
    if fmt in ("all", "xlsx"):
        p = generate_catalog_xlsx(ws, out_dir)
        paths.append(f"阅卷目录(Excel): {p}")
    return _ok("已生成输出文件：\n" + "\n".join(paths))


def _count_records(ws: CaseWorkspace) -> dict:
    return {
        "defendant": len(ws.defendant_statements),
        "codefendant": len(ws.codefendant_statements),
        "witness": len(ws.witness_statements),
    }


# 全部工具（含视觉）
_ALL_TOOLS_WITH_VISION = [
    list_volumes, read_pages, search_volumes, get_volume_outline, get_page_image,
    set_case_basic, record_party, record_indictment, add_charged_fact,
    record_statement, record_procedural_doc, record_documentary_evidence,
    add_catalog_entry, record_conclusions, validate_citations,
    get_workspace_summary, write_outputs,
]

# 不含视觉（仅本地 OCR）：用于视觉不可用的环境，避免 agent 反复调用 get_page_image 空转
_ALL_TOOLS_NO_VISION = [t for t in _ALL_TOOLS_WITH_VISION if t is not get_page_image]


def get_tools(vision_available: bool = False) -> list:
    """返回当前环境应启用的工具集。

    vision_available=True 时包含 get_page_image（视觉识别）；
    False 时仅用本地 OCR（read_pages 已自动对扫描件做 chi_sim OCR）。
    """
    return _ALL_TOOLS_WITH_VISION if vision_available else _ALL_TOOLS_NO_VISION


# 向后兼容
ALL_TOOLS = _ALL_TOOLS_WITH_VISION
