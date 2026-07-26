"""诊断脚本：验证 PDF 文本层、工具层、生成器（不调用 LLM）.

用法: python scripts/diag.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vibelawyer.config import DEFAULT_DATA_DIR, load_case
from vibelawyer.pdf_volume import VolumeStore, _tesseract_has_chinese
from vibelawyer.tools import init_tools
from vibelawyer.workspace import get_workspace, Citation, PartyInfo, reset_workspace


def check_pdf_text() -> None:
    print("=" * 60)
    print("1. PDF 文本层检测")
    print("=" * 60)
    cfg = load_case()
    store = VolumeStore(cfg)
    for v in cfg.volumes:
        vol = store.get(v.name)
        n = vol.page_count()
        # 抽样前3页 + 中间页 + 末页
        sample_pages = sorted({1, 2, 3, n // 2, n})
        print(f"\n《{v.name}》 共 {n} 页，chi_sim可用={_tesseract_has_chinese()}")
        for p in sample_pages:
            if p < 1 or p > n:
                continue
            pt = vol.get_page_text(p)
            preview = (pt.text or "").strip().replace("\n", " ")[:80]
            print(f"  P{p}: {pt.char_count}字 {'⚠无文本层(需视觉OCR)' if pt.needs_ocr else '✓有文本层'} | {preview}")


def check_tools() -> None:
    print("\n" + "=" * 60)
    print("2. 工具层检测（init_tools + 调用）")
    print("=" * 60)
    import asyncio
    cfg = load_case()
    ws = init_tools(cfg)

    async def run():
        from vibelawyer import tools as T
        r1 = await T.list_volumes.handler({})
        print("list_volumes:", r1["content"][0]["text"][:200])
        # 读第一卷前2页
        first_vol = cfg.volumes[0].name
        r2 = await T.read_pages.handler({"volume": first_vol, "start_page": 1, "end_page": 2})
        print(f"\nread_pages({first_vol},1,2) 长度:", len(r2["content"][0]["text"]))
        # 搜索
        r3 = await T.search_volumes.handler({"query": cfg.defendant_hint or "张"})
        print("\nsearch '张':", r3["content"][0]["text"][:200])

    asyncio.run(run())


def check_generators() -> None:
    print("\n" + "=" * 60)
    print("3. 生成器检测（合成数据）")
    print("=" * 60)
    from vibelawyer.config import CaseConfig, DEFAULT_OUTPUT_DIR
    from vibelawyer.workspace import (
        IndictmentInfo, ChargedFact, Statement, ProceduralDoc, DocumentaryEvidence,
        CatalogEntry, Conclusions,
    )
    ws = reset_workspace()
    ws.register_volume("主卷", 100)
    ws.case_name = "测试案"
    ws.defendant = "张三"
    ws.charge = "受贿罪"
    ws.total_amount = "人民币50万元"
    ws.volume_count = 1
    ws.party = PartyInfo(name="张三", gender="男", position="某局局长",
                         appointment_history=["2015-2020 某局副局长", "2020- 某局局长"],
                         source=Citation("主卷", 1, 3, "当事人"))
    ws.indictment = IndictmentInfo(doc_type="起诉意见书", issuer="某市监察委",
                                   charge="受贿罪", total_amount="人民币50万元",
                                   full_text_summary="张三利用职务便利…",
                                   source=Citation("主卷", 5, 8))
    ws.indictment.facts.append(ChargedFact(index=1, description="收受李四贿赂", amount="50万",
                                           source=Citation("主卷", 5, 6)))
    ws.defendant_statements.append(Statement(person="张三", role="defendant", volume="主卷",
                                             page_start=10, page_end=15, record_time="2024-01-01",
                                             investigators="王五、赵六", location="监察委谈话室",
                                             has_av_recording="是", content_summary="供述收受50万",
                                             source=Citation("主卷", 10, 15)))
    ws.procedural_docs.append(ProceduralDoc(doc_type="立案决定书", volume="主卷", page_start=20, page_end=20,
                                            time="2024-01-01", location="某市", content_summary="立案",
                                            source=Citation("主卷", 20, 20)))
    ws.documentary_evidence.append(DocumentaryEvidence(name="银行流水", volume="主卷", page_start=30, page_end=40,
                                                       time="2024", source="某银行",
                                                       content_summary="体现受贿转账", source_ref=Citation("主卷", 30, 40)))
    ws.catalog.append(CatalogEntry(volume_name="主卷", page_range="1-100", file_name="起诉意见书",
                                   doc_type="起诉意见书", record_time="", note=""))
    ws.conclusions = Conclusions(core_facts=["张三收受50万"], evidence_chain=["供述+银行流水"],
                                 contradictions=["供述金额与流水略有出入"], doubts=["款项去向待查"])

    from vibelawyer.generators.docx_notes import generate_review_notes
    from vibelawyer.generators.xlsx_catalog import generate_catalog_xlsx
    out = DEFAULT_OUTPUT_DIR / "_diag"
    out.mkdir(parents=True, exist_ok=True)
    docx_p = generate_review_notes(ws, out)
    xlsx_p = generate_catalog_xlsx(ws, out)
    print(f"Word: {docx_p} ({docx_p.stat().st_size} bytes)")
    print(f"Excel: {xlsx_p} ({xlsx_p.stat().st_size} bytes)")
    problems = ws.validate_all()
    print(f"citation 校验: {len(problems)} 处问题 -> {problems}")


if __name__ == "__main__":
    check_pdf_text()
    check_tools()
    check_generators()
    print("\n✓ 诊断完成")
