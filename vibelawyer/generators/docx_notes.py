"""阅卷笔录 Word 文档生成器.

按需求定义的七部分结构输出，所有事实/证据均带 见《卷》P x-y 来源引用。
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, Cm

from ..workspace import CaseWorkspace, Statement


def _set_cn_font(doc: Document) -> None:
    """设置默认中文字体（宋体）."""
    style = doc.styles["Normal"]
    style.font.name = "SimSun"
    style.font.size = Pt(11)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), "SimSun")


def _cite_text(c) -> str:
    return c.render() if c else "（未标注来源）"


def _cite_full(c) -> str:
    """完整来源引用：见《卷》P起-止（context 说明）。含 JSON 里 source 对象的全部信息。"""
    if not c:
        return "（未标注来源）"
    base = c.render()
    if c.context:
        return f"{base}（{c.context}）"
    return base


def _add_table(doc: Document, headers: list[str], rows: list[list[str]], widths: list[float] | None = None) -> None:
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(10)
    for ri, row in enumerate(rows, 1):
        for ci, val in enumerate(row):
            cell = table.rows[ri].cells[ci]
            cell.text = str(val)
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(10)
    if widths:
        for ci, w in enumerate(widths):
            for row in table.rows:
                row.cells[ci].width = Cm(w)


def _statement_block(doc: Document, s: Statement, label: str) -> None:
    """渲染一条笔录（供述/证言）."""
    doc.add_heading(f"{label}：{s.person}", level=3)
    meta = doc.add_paragraph()
    meta.add_run(
        f"笔录时间：{s.record_time or '未注明'}    办案人员：{s.investigators or '未注明'}    "
        f"办案地点：{s.location or '未注明'}    同步录音录像：{s.has_av_recording or '未注明'}"
    ).font.size = Pt(10)
    if s.charged_fact_ref:
        p = doc.add_paragraph()
        p.add_run(f"对应指控事实：{s.charged_fact_ref}").font.size = Pt(10)
    p = doc.add_paragraph()
    p.add_run("笔录内容：").bold = True
    p.add_run(s.content_summary or "（无）")
    p2 = doc.add_paragraph()
    r = p2.add_run(f"来源：{_cite_full(s.source)}")
    r.font.size = Pt(9)
    r.italic = True


def generate_review_notes(ws: CaseWorkspace, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = Document()
    _set_cn_font(doc)

    case = ws.case_name or "案件"
    title = doc.add_heading(f"{case} 阅卷笔录", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # ---- 案件基本信息表 ----
    doc.add_heading("案件基本信息表", level=1)
    # 完整渲染，不截断：指控事实全文（若过长则单独成段，避免表格单元格压缩丢失文字）
    fact_full = ws.indictment.full_text_summary or "—"
    key_evidence = "；".join(
        f"{e.name}({_cite_text(e.source_ref)})" for e in ws.documentary_evidence
    ) or "（见下文第七部分）"
    _add_table(
        doc,
        ["项目", "内容"],
        [
            ["1. 代理主体", ws.defendant or "—"],
            ["2. 涉嫌罪名", ws.charge or "—"],
            ["3. 起诉书/起诉意见书指控事实", fact_full],
            ["4. 涉案金额", ws.total_amount or "—"],
            ["5. 卷宗数量", f"{ws.volume_count} 册（{'; '.join('《'+v+'》' for v in ws.known_volumes())}）" if ws.known_volumes() else f"{ws.volume_count} 册"],
            ["6. 关键证据索引", key_evidence],
        ],
        widths=[4.5, 12.0],
    )

    # ---- 一、当事人基本情况 ----
    doc.add_heading("一、当事人基本情况", level=1)
    p = ws.party
    if p.name:
        lines = [
            f"姓名：{p.name}",
            f"性别：{p.gender or '—'}    民族：{p.ethnicity or '—'}    出生：{p.birth or '—'}",
            f"籍贯：{p.native_place or '—'}    身份证号：{p.id_no or '—'}    文化程度：{p.education or '—'}",
            f"职业：{p.occupation or '—'}    住址：{p.address or '—'}",
        ]
        for ln in lines:
            doc.add_paragraph(ln)
        if p.position or p.appointment_history:
            doc.add_heading("任职情况（职务犯罪）", level=3)
            if p.position:
                doc.add_paragraph(f"职务：{p.position}")
            for ap in p.appointment_history:
                doc.add_paragraph(ap, style="List Bullet")
        rp = doc.add_paragraph()
        rp.add_run(f"来源：{_cite_full(p.source)}").font.size = Pt(9)
    else:
        doc.add_paragraph("（卷宗中未提取到当事人基本情况，待补充。）")

    # ---- 二、起诉书、起诉意见书内容 ----
    doc.add_heading("二、起诉书、起诉意见书内容", level=1)
    ind = ws.indictment
    if ind.doc_type:
        doc.add_paragraph(
            f"文书类型：{ind.doc_type}    制作机关：{ind.issuer or '—'}    落款日期：{ind.issue_date or '—'}"
        )
        doc.add_paragraph(f"被告人：{ind.defendant or '—'}    涉嫌罪名：{ind.charge or '—'}    涉案金额：{ind.total_amount or '—'}")
        if ind.legal_basis:
            doc.add_paragraph("适用法律条文：")
            for lb in ind.legal_basis:
                doc.add_paragraph(lb, style="List Bullet")
        doc.add_heading("指控事实（原文摘录）", level=3)
        doc.add_paragraph(ind.full_text_summary or "（无）")
        rp = doc.add_paragraph()
        rp.add_run(f"来源：{_cite_full(ind.source)}").font.size = Pt(9)
        if ind.facts:
            doc.add_heading("指控事实分笔", level=3)
            _add_table(
                doc,
                ["序号", "事实概述", "金额", "时间", "来源"],
                [
                    [str(f.index), f.description, f.amount or "—", f.time_period or "—", _cite_text(f.source)]
                    for f in ind.facts
                ],
                widths=[1.2, 8.5, 2.2, 2.5, 2.5],
            )
    else:
        doc.add_paragraph("（卷宗中未发现起诉书/起诉意见书，待补充。）")

    # ---- 三、被告人供述和辩解 ----
    doc.add_heading("三、被告人的供述和辩解", level=1)
    if ws.defendant_statements:
        # 按对应指控事实分组
        groups: dict[str, list[Statement]] = {}
        for s in ws.defendant_statements:
            key = s.charged_fact_ref or "（未对应具体事实）"
            groups.setdefault(key, []).append(s)
        for key, stmts in groups.items():
            doc.add_heading(f"对应：{key}", level=2)
            for s in stmts:
                _statement_block(doc, s, "被告人供述")
    else:
        doc.add_paragraph("（未提取到被告人供述笔录。）")

    # ---- 四、同案人员供述和辩解 ----
    doc.add_heading("四、同案人员的供述和辩解", level=1)
    if ws.codefendant_statements:
        for s in ws.codefendant_statements:
            _statement_block(doc, s, "同案人供述")
    else:
        doc.add_paragraph("（本案无同案人员，或卷宗中未提取到同案人供述。）")

    # ---- 五、证人证言 ----
    doc.add_heading("五、证人证言", level=1)
    if ws.witness_statements:
        for s in ws.witness_statements:
            _statement_block(doc, s, "证人证言")
    else:
        doc.add_paragraph("（卷宗中未提取到证人证言。）")

    # ---- 六、程序性文书 ----
    doc.add_heading("六、程序性文书", level=1)
    if ws.procedural_docs:
        _add_table(
            doc,
            ["序号", "文书类型", "时间", "地点", "主要内容", "来源"],
            [
                [str(i + 1), d.doc_type, d.time or "—", d.location or "—", d.content_summary, _cite_text(d.source)]
                for i, d in enumerate(ws.procedural_docs)
            ],
            widths=[1.0, 2.8, 2.2, 2.2, 5.0, 2.3],
        )
    else:
        doc.add_paragraph("（未提取到程序性文书。）")

    # ---- 七、书证 ----
    doc.add_heading("七、书证（客观证据）", level=1)
    if ws.documentary_evidence:
        _add_table(
            doc,
            ["序号", "文件名称", "形成时间", "卷宗页码", "来源/制作主体", "主要内容", "来源引用"],
            [
                [str(i + 1), e.name, e.time or "—", f"P{e.page_start}-{e.page_end}" if e.page_start else "—",
                 e.source or "—", e.content_summary, _cite_text(e.source_ref)]
                for i, e in enumerate(ws.documentary_evidence)
            ],
            widths=[1.0, 2.8, 2.0, 1.8, 2.2, 4.5, 2.2],
        )
    else:
        doc.add_paragraph("（未提取到书证。）")

    # ---- 阅卷结论 ----
    doc.add_heading("阅卷结论", level=1)
    c = ws.conclusions
    doc.add_heading("（一）已查明核心事实", level=3)
    for x in c.core_facts:
        doc.add_paragraph(x, style="List Bullet")
    if not c.core_facts:
        doc.add_paragraph("（待补充）")
    doc.add_heading("（二）证据链条", level=3)
    for x in c.evidence_chain:
        doc.add_paragraph(x, style="List Bullet")
    if not c.evidence_chain:
        doc.add_paragraph("（待补充）")
    doc.add_heading("（三）证据矛盾点", level=3)
    for x in c.contradictions:
        doc.add_paragraph(x, style="List Bullet")
    if not c.contradictions:
        doc.add_paragraph("（未发现明显矛盾）")
    doc.add_heading("（四）待核查疑点", level=3)
    for x in c.doubts:
        doc.add_paragraph(x, style="List Bullet")
    if not c.doubts:
        doc.add_paragraph("（暂无）")
    # raw：结论合成员的完整原文（若有），完整保留，不截断
    if c.raw:
        doc.add_heading("（五）结论原文", level=3)
        doc.add_paragraph(c.raw)

    # ---- 阅卷目录附表 ----
    doc.add_heading("附：阅卷目录", level=1)
    _add_table(
        doc,
        ["卷宗名称", "页码", "所含文件", "文书类型", "笔录时间", "备注"],
        [
            [e.volume_name, e.page_range, e.file_name, e.doc_type, e.record_time, e.note]
            for e in ws.catalog
        ]
        or [["—"] * 6],
        widths=[3.0, 1.8, 4.0, 2.5, 2.5, 2.5],
    )

    # 免责声明
    doc.add_paragraph()
    disc = doc.add_paragraph()
    r = disc.add_run(
        "说明：本笔录由阅卷 Agent 基于本地卷宗材料自动梳理生成，所有引用均标注来源卷宗及页码，"
        "仅供后续辩护意见参考，不构成正式辩护策略或出庭意见。"
    )
    r.font.size = Pt(9)
    r.italic = True

    safe = case.replace("/", "_").replace(" ", "")
    path = out_dir / f"{safe}_阅卷笔录.docx"
    doc.save(str(path))
    return path
