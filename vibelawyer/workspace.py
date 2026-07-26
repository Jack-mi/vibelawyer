"""案件工作区（CaseWorkspace）—— 进程内结构化状态.

所有原子写工具都向同一个 CaseWorkspace 写入结构化记录；输出文档生成器
从该状态读取数据渲染 Word/Excel。这样 agent 的“理解”与文档的“渲染”解耦：
agent 只需调用 record_* 工具登记一条带卷宗页码的事实，生成器保证引用格式统一。

每条记录都强制要求 source（卷宗名 + 页码区间），未标注来源的记录会被
validate_citations 标红 —— 落实“禁止幻觉与编造、结论可回溯”的约束。
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 数据结构定义（尽量通用，不绑定具体罪名）
# ---------------------------------------------------------------------------


@dataclass
class Citation:
    """一条来源引用：见《volume》P start-end."""

    volume: str
    page_start: int
    page_end: int
    context: str = ""  # 引用对应的简述，便于校验

    def render(self) -> str:
        if self.page_start == self.page_end:
            return f"见《{self.volume}》P{self.page_start}"
        return f"见《{self.volume}》P{self.page_start}-{self.page_end}"


@dataclass
class PartyInfo:
    """当事人基本情况（职务犯罪含任职情况）."""

    name: str = ""
    gender: str = ""
    ethnicity: str = ""
    birth: str = ""
    native_place: str = ""  # 籍贯
    id_no: str = ""  # 身份证号
    education: str = ""
    occupation: str = ""  # 职业
    position: str = ""  # 职务/任职（职务犯罪重点）
    appointment_history: list[str] = field(default_factory=list)  # 任职履历
    address: str = ""
    other: list[str] = field(default_factory=list)
    source: Citation | None = None


@dataclass
class ChargedFact:
    """起诉书/起诉意见书中指控的单笔事实."""

    index: int  # 第几笔
    description: str = ""  # 事实概述（时间/地点/人物/行为/金额）
    amount: str = ""  # 涉案金额
    time_period: str = ""  # 行为发生时间
    source: Citation | None = None


@dataclass
class IndictmentInfo:
    """起诉书/起诉意见书内容."""

    doc_type: str = ""  # 起诉书 / 起诉意见书
    issuer: str = ""  # 制作机关
    issue_date: str = ""
    defendant: str = ""  # 被告人/犯罪嫌疑人
    charge: str = ""  # 涉嫌罪名
    facts: list[ChargedFact] = field(default_factory=list)
    total_amount: str = ""  # 涉案总金额
    legal_basis: list[str] = field(default_factory=list)  # 适用法律条文
    full_text_summary: str = ""  # 指控事实全文摘录
    source: Citation | None = None


@dataclass
class Statement:
    """供述/辩解或证言（讯问/询问笔录）."""

    person: str = ""
    role: str = ""  # defendant / co-defendant / witness
    volume: str = ""
    page_start: int = 0
    page_end: int = 0
    record_time: str = ""  # 笔录时间
    investigators: str = ""  # 办案人员
    location: str = ""  # 办案地点
    has_av_recording: str = ""  # 是否同步录音录像（是/否/未注明）
    charged_fact_ref: str = ""  # 对应指控事实（如“第1笔”）
    content_summary: str = ""  # 笔录内容摘要
    source: Citation | None = None


@dataclass
class ProceduralDoc:
    """程序性文书（立案/拘留/逮捕/取保/搜查/扣押/鉴定/起诉等）."""

    doc_type: str = ""
    volume: str = ""
    page_start: int = 0
    page_end: int = 0
    time: str = ""  # 具体时间
    location: str = ""  # 具体地点
    content_summary: str = ""
    source: Citation | None = None


@dataclass
class DocumentaryEvidence:
    """书证（客观证据）."""

    name: str = ""  # 文件名称
    volume: str = ""
    page_start: int = 0
    page_end: int = 0
    time: str = ""  # 形成时间
    source: str = ""  # 来源/制作主体
    content_summary: str = ""
    source_ref: Citation | None = None


@dataclass
class CatalogEntry:
    """阅卷目录（卷宗目录）一条."""

    volume_name: str = ""  # 卷宗名称
    page_range: str = ""  # 本卷页码区间
    file_name: str = ""  # 本卷所含文件名称
    doc_type: str = ""  # 文书类型
    record_time: str = ""  # 笔录时间
    note: str = ""  # 备注


@dataclass
class Conclusions:
    """阅卷结论."""

    core_facts: list[str] = field(default_factory=list)  # 已查明核心事实
    evidence_chain: list[str] = field(default_factory=list)  # 证据链条
    contradictions: list[str] = field(default_factory=list)  # 证据矛盾点
    doubts: list[str] = field(default_factory=list)  # 待核查疑点
    raw: str = ""


# ---------------------------------------------------------------------------
# 工作区
# ---------------------------------------------------------------------------


class CaseWorkspace:
    """全局进程内工作区（线程安全）.

    SDK MCP 工具运行在同一进程，多个子 agent 可能并发写入，故加锁。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.case_name: str = ""
        self.defendant: str = ""
        self.charge: str = ""
        self.total_amount: str = ""
        self.volume_count: int = 0

        self.party: PartyInfo = PartyInfo()
        self.indictment: IndictmentInfo = IndictmentInfo()
        self.defendant_statements: list[Statement] = []
        self.codefendant_statements: list[Statement] = []
        self.witness_statements: list[Statement] = []
        self.procedural_docs: list[ProceduralDoc] = []
        self.documentary_evidence: list[DocumentaryEvidence] = []
        self.catalog: list[CatalogEntry] = []
        self.conclusions: Conclusions = Conclusions()

        # 页码合法性校验用：volume_name -> max_pages
        self._volume_pages: dict[str, int] = {}

    # ----- 卷宗页数登记（供 citation 校验）-----
    def register_volume(self, name: str, pages: int) -> None:
        with self._lock:
            self._volume_pages[name] = pages

    def volume_pages(self, name: str) -> int:
        with self._lock:
            return self._volume_pages.get(name, 0)

    def known_volumes(self) -> list[str]:
        with self._lock:
            return list(self._volume_pages.keys())

    # ----- 引用校验 -----
    def validate_citation(self, c: Citation | None) -> tuple[bool, str]:
        """校验一条引用的卷宗名与页码是否落在真实页数区间内."""
        if c is None:
            return False, "未标注来源"
        if not c.volume:
            return False, "卷宗名为空"
        max_pages = self._volume_pages.get(c.volume)
        if max_pages is None:
            return False, f"卷宗《{c.volume}》不在已登记卷宗中"
        if c.page_start <= 0 or c.page_end < c.page_start:
            return False, f"页码非法: {c.page_start}-{c.page_end}"
        if c.page_end > max_pages:
            return False, f"页码超出《{c.volume}》总页数 {max_pages}: {c.page_end}"
        return True, "ok"

    def validate_all(self) -> list[dict[str, Any]]:
        """校验所有记录的来源引用，返回不合规项清单."""
        with self._lock:
            records: list[tuple[str, Citation | None]] = []
            records.append(("当事人基本情况", self.party.source))
            records.append(("起诉书", self.indictment.source))
            for f in self.indictment.facts:
                records.append((f"指控事实第{f.index}笔", f.source))
            for s in self.defendant_statements:
                records.append((f"被告人供述:{s.person}", s.source))
            for s in self.codefendant_statements:
                records.append((f"同案人供述:{s.person}", s.source))
            for s in self.witness_statements:
                records.append((f"证人证言:{s.person}", s.source))
            for d in self.procedural_docs:
                records.append((f"程序性文书:{d.doc_type}", d.source))
            for e in self.documentary_evidence:
                records.append((f"书证:{e.name}", e.source_ref))
        problems = []
        for label, c in records:
            ok, msg = self.validate_citation(c)
            if not ok:
                problems.append({"record": label, "issue": msg})
        return problems

    # ----- 序列化（供生成器与调试）-----
    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            def c(cit: Citation | None) -> dict | None:
                return asdict(cit) if cit else None
            return {
                "case_name": self.case_name,
                "defendant": self.defendant,
                "charge": self.charge,
                "total_amount": self.total_amount,
                "volume_count": self.volume_count,
                "party": asdict(self.party),
                "indictment": asdict(self.indictment),
                "defendant_statements": [asdict(s) for s in self.defendant_statements],
                "codefendant_statements": [asdict(s) for s in self.codefendant_statements],
                "witness_statements": [asdict(s) for s in self.witness_statements],
                "procedural_docs": [asdict(d) for d in self.procedural_docs],
                "documentary_evidence": [asdict(e) for e in self.documentary_evidence],
                "catalog": [asdict(e) for e in self.catalog],
                "conclusions": asdict(self.conclusions),
            }

    def dump_json(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


# 进程级单例：所有 @tool 共享
_WORKSPACE: CaseWorkspace | None = None


def get_workspace() -> CaseWorkspace:
    global _WORKSPACE
    if _WORKSPACE is None:
        _WORKSPACE = CaseWorkspace()
    return _WORKSPACE


def reset_workspace() -> CaseWorkspace:
    global _WORKSPACE
    _WORKSPACE = CaseWorkspace()
    return _WORKSPACE
