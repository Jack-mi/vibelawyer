"""阅卷分步说明（纯数据，不依赖 claude-agent-sdk）.

历史「专职子 agent」提示词已迁入 playbook.REVIEW_STEPS。
本模块保留兼容别名，供可选 legacy 编排读取。
"""
from __future__ import annotations

from .playbook import COMMON_RULES, REVIEW_STEPS

# 兼容旧名
_COMMON_RULES = COMMON_RULES

# step_id -> {description, prompt, tools_hint}
STEP_PROMPTS: dict[str, dict[str, str]] = {
    s["id"]: {
        "description": s["goal"],
        "prompt": s["detail"] + "\n" + COMMON_RULES,
        "title": s["title"],
    }
    for s in REVIEW_STEPS
    if s["id"] != "validate-and-export"
}

# 旧 SUBAGENTS 键名列表（顺序）
SUBAGENT_ORDER = [
    "case-indexer",
    "indictment-reader",
    "defendant-statement-extractor",
    "codefendant-statement-extractor",
    "witness-statement-extractor",
    "procedural-extractor",
    "evidence-extractor",
    "conclusion-synthesizer",
]


def get_subagent_prompt(name: str) -> dict[str, str]:
    """返回某一步的 description/prompt；未知名称抛 KeyError."""
    return STEP_PROMPTS[name]
