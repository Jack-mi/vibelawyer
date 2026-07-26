"""从已保存的 workspace.json 重建 CaseWorkspace 并重新生成 docx/xlsx（验证无损渲染，不重跑 agent）。

用法: python scripts/rerender.py [workspace.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vibelawyer.workspace import (
    CaseWorkspace, PartyInfo, IndictmentInfo, ChargedFact, Statement,
    ProceduralDoc, DocumentaryEvidence, CatalogEntry, Conclusions, Citation,
)
from vibelawyer.config import load_case
from vibelawyer.generators.docx_notes import generate_review_notes
from vibelawyer.generators.xlsx_catalog import generate_catalog_xlsx


def _cite(d: dict | None) -> Citation | None:
    if not d:
        return None
    return Citation(volume=d.get("volume", ""), page_start=d.get("page_start", 0),
                    page_end=d.get("page_end", 0), context=d.get("context", ""))


def load_ws(path: Path) -> CaseWorkspace:
    d = json.loads(path.read_text(encoding="utf-8"))
    ws = CaseWorkspace()
    ws.case_name = d.get("case_name", "")
    ws.defendant = d.get("defendant", "")
    ws.charge = d.get("charge", "")
    ws.total_amount = d.get("total_amount", "")
    ws.volume_count = d.get("volume_count", 0)
    p = d.get("party", {})
    ws.party = PartyInfo(
        name=p.get("name", ""), gender=p.get("gender", ""), ethnicity=p.get("ethnicity", ""),
        birth=p.get("birth", ""), native_place=p.get("native_place", ""), id_no=p.get("id_no", ""),
        education=p.get("education", ""), occupation=p.get("occupation", ""), position=p.get("position", ""),
        appointment_history=p.get("appointment_history", []), address=p.get("address", ""),
        source=_cite(p.get("source")),
    )
    i = d.get("indictment", {})
    ws.indictment = IndictmentInfo(
        doc_type=i.get("doc_type", ""), issuer=i.get("issuer", ""), issue_date=i.get("issue_date", ""),
        defendant=i.get("defendant", ""), charge=i.get("charge", ""), total_amount=i.get("total_amount", ""),
        legal_basis=i.get("legal_basis", []), full_text_summary=i.get("full_text_summary", ""),
        source=_cite(i.get("source")),
    )
    for f in i.get("facts", []):
        ws.indictment.facts.append(ChargedFact(
            index=f.get("index", 0), description=f.get("description", ""), amount=f.get("amount", ""),
            time_period=f.get("time_period", ""), source=_cite(f.get("source"))))
    for role_attr, role in [("defendant_statements", "defendant"), ("codefendant_statements", "codefendant"),
                            ("witness_statements", "witness")]:
        for s in d.get(role_attr, []):
            ws.__dict__[role_attr].append(Statement(
                person=s.get("person", ""), role=role, volume=s.get("volume", ""),
                page_start=s.get("page_start", 0), page_end=s.get("page_end", 0),
                record_time=s.get("record_time", ""), investigators=s.get("investigators", ""),
                location=s.get("location", ""), has_av_recording=s.get("has_av_recording", ""),
                charged_fact_ref=s.get("charged_fact_ref", ""), content_summary=s.get("content_summary", ""),
                source=_cite(s.get("source"))))
    for pd in d.get("procedural_docs", []):
        ws.procedural_docs.append(ProceduralDoc(
            doc_type=pd.get("doc_type", ""), volume=pd.get("volume", ""),
            page_start=pd.get("page_start", 0), page_end=pd.get("page_end", 0),
            time=pd.get("time", ""), location=pd.get("location", ""),
            content_summary=pd.get("content_summary", ""), source=_cite(pd.get("source"))))
    for e in d.get("documentary_evidence", []):
        ws.documentary_evidence.append(DocumentaryEvidence(
            name=e.get("name", ""), volume=e.get("volume", ""), page_start=e.get("page_start", 0),
            page_end=e.get("page_end", 0), time=e.get("time", ""), source=e.get("source", ""),
            content_summary=e.get("content_summary", ""), source_ref=_cite(e.get("source_ref"))))
    for c in d.get("catalog", []):
        ws.catalog.append(CatalogEntry(
            volume_name=c.get("volume_name", ""), page_range=c.get("page_range", ""),
            file_name=c.get("file_name", ""), doc_type=c.get("doc_type", ""),
            record_time=c.get("record_time", ""), note=c.get("note", "")))
    ccl = d.get("conclusions", {})
    ws.conclusions = Conclusions(
        core_facts=ccl.get("core_facts", []), evidence_chain=ccl.get("evidence_chain", []),
        contradictions=ccl.get("contradictions", []), doubts=ccl.get("doubts", []), raw=ccl.get("raw", ""))
    for v in d.get("known_volumes") or []:
        pass
    return ws


def main() -> int:
    cfg = load_case()
    out_dir = cfg.ensure_output_dir()
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(out_dir.glob("*_workspace.json"))[-1]
    print(f"载入: {src.name}")
    ws = load_ws(src)
    for v in cfg.volumes:
        ws.register_volume(v.name, v.pages)
    docx_p = generate_review_notes(ws, out_dir)
    xlsx_p = generate_catalog_xlsx(ws, out_dir)
    print(f"Word: {docx_p}")
    print(f"Excel: {xlsx_p}")
    print(f"校验不合规: {len(ws.validate_all())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
