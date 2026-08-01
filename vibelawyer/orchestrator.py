"""主 agent 编排器.

装配 ClaudeAgentOptions：进程内 MCP 工具 + 子 agent + 主 agent 系统提示词，
通过 query() 端到端驱动阅卷流程。工具接口被刻意收窄为只读卷宗 + 登记记录 + 导出，
禁用文件改写与联网工具，落实“仅本地、可回溯、不外传”的约束。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    create_sdk_mcp_server,
    query,
)

from .agents import SUBAGENTS
from .config import CaseConfig
from .sessions import MANAGER, CaseSession
from .tools import bind_session, get_tools, init_tools
from .workspace import get_workspace

MCP_SERVER_NAME = "vibelawyer"

# 禁用的内置工具：文件改写、联网、自由读盘 —— 强制一切信息经 MCP 工具留痕
_DISALLOWED_TOOLS = [
    "Bash", "Read", "Edit", "Write", "NotebookEdit",
    "Grep", "Glob", "LS",
    "WebFetch", "WebSearch", "Skill",
    "TaskOutput", "TaskStop",
]


MAIN_SYSTEM_PROMPT = """你是「刑事案件阅卷主 Agent」，负责编排整个阅卷梳理流程，产出可归档、可复核的
阅卷笔录与阅卷目录。你对任意刑事案件通用，不假定具体罪名或当事人。

# 工作流（严格按序）

【步骤 1：制作阅卷笔录与阅卷目录】
0. 先调用 list_volumes 掌握卷宗全貌。
1. 委派 `case-indexer` 编制阅卷目录（卷宗目录），并定位起诉书/起诉意见书所在卷页。
2. 委派 `indictment-reader` 阅读起诉书/起诉意见书，登记当事人基本情况、指控事实、涉案金额。
3. 委派以下子 agent（可并行）逐部分提取：
   - `defendant-statement-extractor`：被告人供述与辩解（按指控事实分组，含笔录时间/办案人员/地点/同步录音录像/内容）
   - `codefendant-statement-extractor`：同案人员供述（如有）
   - `witness-statement-extractor`：证人证言
   - `procedural-extractor`：程序性文书（含具体时间、地点）
   - `evidence-extractor`：书证（时间、文件名称、卷宗页码、主要内容）
4. 委派 `conclusion-synthesizer` 形成阅卷结论。

【步骤 2：校验与导出】
5. 调用 validate_citations 校验所有来源引用；若有不合规项，委派对应子 agent 修正后重校。
6. 调用 get_workspace_summary 确认七部分均已登记。
7. 调用 write_outputs(fmt='all') 生成 Word 阅卷笔录与 Excel 阅卷目录。
8. 返回中文结案小结：案件信息、各部分登记数、校验结果、输出文件路径。

# 委派与核验（关键）
通过 Task 工具调用子 agent（按 SUBAGENTS 中的名称）。每个子 agent 共享同一套 mcp__vibelawyer__* 工具，
会自行读卷并登记到同一工作区。你本人也拥有全部工具，可随时补登或直接完成某部分。
**子 agent 的口头回报不可信，必须以工具核实为准**：每个子 agent 返回后，你**必须**调用
get_workspace_summary 查看各部分**实际登记数**；若某部分仍为 0 或明显不足（例如声称已编目但目录条目为0），
立即重新委派该子 agent 或亲自用工具补登，不得放任空缺继续后续步骤。

# 铁律（不可违反）
1. 严禁幻觉与编造：一切事实/证据必须来自卷宗实际内容，且标注来源卷宗名与页码（见《卷名》P起-止）。
2. 仅本地：不联网、不上传任何卷宗内容到外部服务；信息只在本进程内流转。
3. 范围限制：只做阅卷目录与阅卷笔录的整理及案情梳理，不生成正式辩护策略或出庭意见。
4. 当事人/罪名/金额等若卷宗未载明，如实标注“卷宗未载明”，不得臆测。

# 笔录七部分结构（write_outputs 会据此渲染，你须确保各子 agent 已登记对应数据）
一、当事人基本情况（职务犯罪含任职情况）
二、起诉书、起诉意见书内容
三、被告人的供述和辩解
四、同案人员的供述和辩解
五、证人证言
六、程序性文书
七、书证
附：阅卷目录、阅卷结论（核心事实/证据链条/矛盾点/待核查疑点）
"""


def build_options(cfg: CaseConfig, *, model: str | None = None, effort: str = "high",
                  max_turns: int = 100) -> ClaudeAgentOptions:
    """装配主 agent 运行选项."""
    tools = get_tools(cfg.vision_available)
    mcp_server = create_sdk_mcp_server(MCP_SERVER_NAME, "1.0.0", tools=tools)
    allowed = [f"mcp__{MCP_SERVER_NAME}__{t.name}" for t in tools] + ["Task", "TodoWrite"]
    opts = ClaudeAgentOptions(
        system_prompt=MAIN_SYSTEM_PROMPT + _vision_note(cfg.vision_available),
        mcp_servers={MCP_SERVER_NAME: mcp_server},
        agents=SUBAGENTS,
        allowed_tools=allowed,
        disallowed_tools=_DISALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        cwd=str(cfg.case_dir),
        add_dirs=[str(cfg.case_dir)],
        max_turns=max_turns,
        effort=effort,  # type: ignore[arg-type]
        max_buffer_size=16 * 1024 * 1024,  # 16MB：容纳 get_page_image 返回的 base64 图像
        stderr=lambda s: print(f"[cli] {s}", file=sys.stderr) if s.strip() else None,
    )
    if model:
        opts.model = model
    return opts


def _vision_note(vision_available: bool) -> str:
    if vision_available:
        return "\n\n# 视觉识别\n本环境支持视觉：扫描件页面可调用 get_page_image 渲染图像后用视觉识别。"
    return ("\n\n# 视觉识别（本环境不可用）\n"
            "本环境视觉识别不可用（无 get_page_image 工具）。所有页面文本一律以 read_pages 的"
            "本地中文 OCR 结果为准；OCR 仍不清晰的页面，如实标注“OCR识别不清/待核查”，"
            "禁止反复尝试获取图像。")


async def run_case(cfg: CaseConfig, *, model: str | None = None, effort: str = "high",
                   max_turns: int = 100, verbose: bool = True,
                   session: CaseSession | None = None, progress=None) -> dict:
    """端到端运行阅卷流程（多 agent 顺序编排），返回结果摘要.

    编排策略：Python 主编排器按阅卷工作流顺序运行各专职子 agent（每个作为独立 top-level
    query() 会话，共享同一进程内 MCP 工具与 CaseWorkspace）。OCR 结果在进程内缓存，
    后续 agent 读取同页几乎零成本。各 agent 返回后由编排器用 get_workspace_summary
    核实实际登记数，不足则补跑。最后校验引用并导出 Word/Excel。

    session 传入时复用该会话（MCP 服务模式：create_case 已建会话，不重置工作区），
    否则经 init_tools 新建会话（本地 CLI 模式）。progress 为可选的步骤回调（签名 f(str)）。
    """
    def _emit(msg: str) -> None:
        if progress is not None:
            progress(msg)
        if verbose:
            print(msg, flush=True)

    if session is not None:
        MANAGER.ensure_docling_cache(session, verbose=verbose)
        ws = bind_session(session).workspace
    else:
        ws = init_tools(cfg, use_docling=True, verbose=verbose)  # 初始化工具层 + docling 预转换 + 重置工作区
    server = create_sdk_mcp_server(MCP_SERVER_NAME, "1.0.0", tools=get_tools(cfg.vision_available))
    hint = (
        f"{'当事人：' + cfg.defendant_hint + '。' if cfg.defendant_hint else ''}"
        f"{'涉嫌罪名：' + cfg.charge_hint + '。' if cfg.charge_hint else ''}"
    )

    # 阅卷工作流：顺序子 agent（前者为后者提供基础）
    flow = [
        ("case-indexer", "编制阅卷目录（卷宗目录）并定位起诉书/起诉意见书所在卷页。"
         "用 get_volume_outline 浏览、read_pages 精读定位，再**逐条调用 add_catalog_entry 登记**"
         "每册卷所含文件（卷宗名/页码/文件名/文书类型/笔录时间）。完成调用 get_workspace_summary 核实目录条目数。"),
        ("indictment-reader", "阅读起诉书/起诉意见书。先 search_volumes 检索“起诉/指控”定位，"
         "或用 case-indexer 已定位的页码 read_pages。用 set_case_basic 登记案件基本信息，"
         "record_party 登记当事人基本情况（职务犯罪含任职情况），record_indictment 登记起诉书内容"
         "（full_text_summary 原样复制涉及被告人的指控事实），add_charged_fact 逐笔登记指控事实。"),
        ("defendant-statement-extractor", "提取被告人供述与辩解。search_volumes 检索被告人姓名定位讯问笔录，"
         "对每份笔录 read_pages 后用 record_statement(role='defendant') 登记"
         "（笔录时间/办案人员/办案地点/是否同步录音录像/对应指控事实/要点摘要/**full_text 逐字问答全文**）。"
         "多份笔录按时间逐一登记，一份笔录一次调用。"),
        ("codefendant-statement-extractor", "提取同案人供述（如有）。从起诉书识别同案人并 search_volumes 定位其讯问笔录，"
         "用 record_statement(role='codefendant') 登记（含 full_text 逐字问答全文）。无同案人则返回说明。"),
        ("witness-statement-extractor", "提取证人证言。search_volumes 检索“询问笔录/证人”定位，"
         "用 record_statement(role='witness') 登记每份证言（含 full_text 逐字问答全文，"
         "金额/账户/日期等细节原样保留）。行受贿类案件的行贿人/知情人证言须完整记录。"),
        ("procedural-extractor", "提取程序性文书。search_volumes 检索“立案/拘留/逮捕/取保/搜查/扣押/鉴定/移送/起诉/法律援助/出庭”等，"
         "用 record_procedural_doc 逐份登记（文书类型/**文号 doc_no**/时间/地点/内容）。"
         "按时间顺序覆盖从被调查到当前的程序链条。"),
        ("evidence-extractor", "提取书证。用 get_volume_outline 浏览各卷识别客观证据（合同/银行流水/转账凭证/收据/"
         "公司登记资料/审计报告/鉴定意见/任职文件等），用 record_documentary_evidence 逐份登记"
         "（文件名称/时间/卷宗页码/来源/主要内容/**fact_group 待证事实分组**）；"
         "流水类书证必须用 add_transaction 逐笔登记资金流水。"),
        ("conclusion-synthesizer", "形成阅卷结论。先 get_workspace_summary 查看整体登记，必要时 read_pages 复核关键页，"
         "用 record_conclusions 登记核心事实/证据链条/证据矛盾点（重点比对各次供述全文的不一致）/待核查疑点；"
         "用 record_funds_summary 登记资金勾稽摘要（报案合计/合同合计/指控金额/已返还/违法所得/已退赔，"
         "口径不一致须在 note 说明）。仅做案情梳理，不输出正式辩护策略。"),
    ]

    sub_summary = []
    catalog_briefing = ""  # case-indexer 完成后填充，供后续 agent 共享卷宗定位信息
    for name, task in flow:
        _emit(f"\n========== 委派子 agent: {name} ==========")
        ad = SUBAGENTS[name]
        full_task = task + " " + hint
        if name != "case-indexer" and catalog_briefing:
            full_task += "\n\n【卷宗目录摘要（case-indexer 已编制，据此定位文书，勿遗漏任何卷）】\n" + catalog_briefing
        ok, summary = await _run_subagent(ad, full_task, cfg, server,
                                          model=model, effort=effort, verbose=verbose)
        sub_summary.append((name, ok, summary))
        # 核实实际登记数
        ws_now = get_workspace()
        counts = _section_counts(ws_now)
        _emit(f"[核实] {name} 后工作区: {counts}")
        # case-indexer 完成后，构建卷宗目录摘要供后续 agent 使用
        if name == "case-indexer" and not catalog_briefing:
            catalog_briefing = _build_catalog_briefing(ws_now)

    # 主 agent 收尾：校验 + 导出（直接调用，确保执行）。最终产出仅 Word/Excel，不再导出 JSON。
    _emit("\n========== 校验引用 + 导出 ==========")
    from .generators.docx_notes import generate_review_notes
    from .generators.xlsx_catalog import generate_catalog_xlsx
    out_dir = cfg.ensure_output_dir()
    problems = ws.validate_all()
    docx_path = generate_review_notes(ws, out_dir)
    xlsx_path = generate_catalog_xlsx(ws, out_dir)

    return {
        "case_name": ws.case_name,
        "defendant": ws.defendant,
        "charge": ws.charge,
        "total_amount": ws.total_amount,
        "docx": str(docx_path),
        "xlsx": str(xlsx_path),
        "citation_problems": problems,
        "section_counts": _section_counts(ws),
        "subagent_summaries": sub_summary,
    }


async def _run_subagent(agent_def, task_prompt: str, cfg: CaseConfig, server,
                        *, model: str | None = None, effort: str = "high",
                        verbose: bool = True) -> tuple[bool, str]:
    """以 top-level query() 运行一个子 agent（共享 MCP 工具与工作区）."""
    tools = get_tools(cfg.vision_available)
    allowed = [f"mcp__{MCP_SERVER_NAME}__{t.name}" for t in tools]
    opts = ClaudeAgentOptions(
        system_prompt=agent_def.prompt + _vision_note(cfg.vision_available),
        mcp_servers={MCP_SERVER_NAME: server},
        allowed_tools=allowed,
        disallowed_tools=_DISALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        cwd=str(cfg.case_dir),
        add_dirs=[str(cfg.case_dir)],
        max_turns=agent_def.maxTurns or 60,
        effort=effort,  # type: ignore[arg-type]
        max_buffer_size=16 * 1024 * 1024,
        stderr=lambda s: print(f"[cli:{agent_def.description[:12]}] {s}", file=sys.stderr) if s.strip() else None,
    )
    if model:
        opts.model = model
    final = ""
    try:
        async for msg in query(prompt=task_prompt, options=opts):
            if verbose:
                _log_message(msg)
            txt = _extract_text(msg)
            if txt:
                final = txt
    except Exception as e:
        print(f"[error] 子 agent 异常: {e}", flush=True)
        return False, f"异常: {e}"
    return True, final[:800]


def _build_catalog_briefing(ws) -> str:
    """把已登记的阅卷目录压缩成摘要，供后续 agent 定位文书（含起诉书位置等）。"""
    if not ws.catalog:
        return ""
    lines = []
    # 高亮起诉书/起诉意见书位置
    for e in ws.catalog:
        dt = (e.doc_type or "") + (e.file_name or "")
        mark = " ★【起诉书/起诉意见书】" if "起诉" in dt else ""
        lines.append(f"- 《{e.volume_name}》 P{e.page_range} | {e.file_name} | {e.doc_type}{mark}")
    return "\n".join(lines)


def _section_counts(ws) -> dict:
    return {
        "案件": ws.case_name or "—",
        "当事人": ws.defendant or "—",
        "罪名": ws.charge or "—",
        "金额": ws.total_amount or "—",
        "目录": len(ws.catalog),
        "当事人信息": 1 if ws.party.name else 0,
        "起诉书": 1 if ws.indictment.doc_type else 0,
        "指控事实": len(ws.indictment.facts),
        "被告人供述": len(ws.defendant_statements),
        "同案人供述": len(ws.codefendant_statements),
        "证人证言": len(ws.witness_statements),
        "程序性文书": len(ws.procedural_docs),
        "书证": len(ws.documentary_evidence),
        "结论核心/矛盾/疑点": f"{len(ws.conclusions.core_facts)}/{len(ws.conclusions.contradictions)}/{len(ws.conclusions.doubts)}",
    }


def _extract_result_text(content) -> str:
    """从 ToolResultBlock.content（str | list[dict] | None）提取文本摘要."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict):
                t = c.get("type")
                if t == "text":
                    return c.get("text", "")
                if t == "image":
                    return f"<image {len(c.get('data', ''))}chars>"
            else:
                t = getattr(c, "type", None)
                if t == "text":
                    return getattr(c, "text", "")
                if t == "image":
                    return f"<image {len(getattr(c,'data',''))}chars>"
    return ""


def _extract_text(msg) -> str:
    try:
        from claude_agent_sdk import AssistantMessage, TextBlock
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    return block.text or ""
    except Exception:
        pass
    # 兜底：dict 形态
    if isinstance(msg, dict):
        if msg.get("type") == "assistant":
            for block in msg.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
    return ""


def _log_message(msg) -> None:
    """简洁打印流式消息，便于观察进度（含工具调用与结果摘要）."""
    try:
        from claude_agent_sdk import (
            AssistantMessage, ResultMessage, ToolUseBlock, ToolResultBlock, TextBlock,
            UserMessage,
        )
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock) and b.text:
                    print(f"\n[assistant] {b.text[:500]}", flush=True)
                elif isinstance(b, ToolUseBlock):
                    print(f"  [tool→] {b.name} {str(b.input)[:160]}", flush=True)
        elif isinstance(msg, UserMessage):
            # 工具结果以 user message 形式回流（含 ToolResultBlock）
            for b in (getattr(msg, "content", None) or []):
                if isinstance(b, ToolResultBlock):
                    content = getattr(b, "content", None)
                    txt = _extract_result_text(content)
                    print(f"  [tool←] {txt[:140]}", flush=True)
        elif isinstance(msg, ResultMessage):
            print(f"\n[result] {msg.subtype} cost=${getattr(msg, 'total_cost_usd', 0) or 0:.4f} "
                  f"turns={getattr(msg, 'num_turns', '?')}", flush=True)
    except Exception:
        pass
