"""宿主 Agent 阅卷工作流（playbook）—— 与 Claude Code / SDK 无关.

供 FastMCP `start_review` 返回、以及 skills/vibelawyer-review/SKILL.md 共用，
避免步骤与铁律两处漂移。
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 铁律（宿主每一步都必须遵守）
# ---------------------------------------------------------------------------

COMMON_RULES = """
【铁律】
1. 严禁幻觉：只能基于 read_pages 实际读到的内容登记记录，绝不臆测或编造。
2. 来源必标：每条记录必须给出真实卷宗名与页码区间（见 list_volumes 的卷名）。页码拿不准时，
   重新 read_pages 核对后再登记。
3. **交付物 = 工具调用，不是文字报告**：任务完成标志是“已实际调用对应 record_*/add_*
   工具把数据登记进工作区”，而**不是**在回复里写出目录或内容。仅口述而未调用工具登记，
   视为未完成。读完卷宗后，必须逐条调用登记工具把数据写入工作区。
4. 扫描件处理：read_pages 已自动对扫描件做本地中文 OCR，多数页面可直接拿到可读文本。
   OCR 仍不清晰的页面，如实标注“OCR识别不清/待核查”，不要反复尝试获取图像。
5. 高效：先 get_volume_outline 浏览逐页概览定位目标文书，再 read_pages 精读相关页，
   避免无谓逐页全读。
6. 全面性：用 search_volumes 检索关键人名/事实（扫描页经OCR后亦可检索），不遗漏出现位置。
7. 收尾：调用 get_workspace_summary（或 get_case_status）核实本部分**实际登记数**
   （以工具返回为准，不是你以为的数）；若为 0 或与预期不符，补登后再进入下一步。
""".strip()

# ---------------------------------------------------------------------------
# FastMCP 调用约定
# ---------------------------------------------------------------------------

MCP_CALL_HINT = """
【FastMCP 调用约定】
- 除 create_case / list_cases 外，几乎所有工具都需要 case_id。
- 读卷/登记/校验类 passthrough 工具签名为：tool_name(case_id, args={...})。
  例如：read_pages(case_id="...", args={"volume": "主卷", "start_page": 1, "end_page": 5})。
- 先 create_case(case_dir="/绝对路径/到卷宗目录") 拿到 case_id，再按步骤调用。
- 全流程由宿主 Agent 自行编排；本服务不启动后台 LLM job。
""".strip()

# ---------------------------------------------------------------------------
# 分步定义（与历史 orchestrator flow / agents 对齐）
# ---------------------------------------------------------------------------

# 每步：id, title, goal, tools, done_when, detail（给宿主的详细任务说明）

REVIEW_STEPS: list[dict[str, Any]] = [
    {
        "id": "case-indexer",
        "title": "编制阅卷目录",
        "goal": "编制阅卷目录并定位起诉书/起诉意见书所在卷页",
        "tools": [
            "list_volumes", "get_volume_outline", "read_pages",
            "add_catalog_entry", "get_workspace_summary",
        ],
        "done_when": "get_workspace_summary / get_case_status 中「目录」计数 > 0，且已定位起诉书页码",
        "detail": (
            "1. list_volumes 掌握全部卷宗。\n"
            "2. 对每册 get_volume_outline 获取逐页概览，识别文件/文书及页码边界。\n"
            "3. 用 add_catalog_entry 为每册每个文件登记：卷宗名称、页码区间、文件名称、"
            "文书类型、笔录时间（如能识别）、备注。\n"
            "4. 特别定位起诉书或起诉意见书所在卷与页，供后续步骤直接 read_pages。"
        ),
    },
    {
        "id": "indictment-reader",
        "title": "阅读起诉书 / 当事人",
        "goal": "提取当事人基本情况、起诉书/起诉意见书指控事实与涉案金额",
        "tools": [
            "search_volumes", "read_pages", "set_case_basic", "record_party",
            "record_indictment", "add_charged_fact", "get_workspace_summary",
        ],
        "done_when": "已 set_case_basic；当事人与起诉书已登记；指控事实已分笔（如可分）",
        "detail": (
            "1. search_volumes 检索「起诉」「指控」等定位文书，或用上一步已定位页码 read_pages。\n"
            "2. record_party 只登记本案当事人（辩护对象/被告人本人），不是同案人；"
            "职务犯罪提取 position 与 appointment_history。\n"
            "3. record_indictment 登记文书类型、机关、日期、被告人、罪名、金额、法条、"
            "量刑情节；full_text_summary 原样复制涉及被告人的指控事实。\n"
            "4. 可分笔时用 add_charged_fact 逐笔登记。\n"
            "5. set_case_basic 登记案件名称、当事人、罪名、涉案金额、卷宗数量。"
        ),
    },
    {
        "id": "defendant-statement-extractor",
        "title": "提取被告人供述",
        "goal": "按指控事实整理被告人供述与辩解（讯问笔录），逐字转录问答全文",
        "tools": [
            "search_volumes", "read_pages", "record_statement", "get_workspace_summary",
        ],
        "done_when": "「被告人供述」计数与讯问笔录份数相符；每份含 full_text",
        "detail": (
            "1. search_volumes 检索被告人姓名，定位讯问笔录。\n"
            "2. 对每份笔录 read_pages 后 record_statement(role='defendant')："
            "person / record_time / investigators / location / has_av_recording / "
            "occasion / charged_fact_ref / content_summary / **full_text 逐字问答全文**。\n"
            "3. 多份笔录按时间逐一登记；一份笔录一次调用。"
        ),
    },
    {
        "id": "codefendant-statement-extractor",
        "title": "提取同案人供述",
        "goal": "整理同案人员供述（如有），逐字转录问答全文",
        "tools": [
            "search_volumes", "read_pages", "record_statement", "get_workspace_summary",
        ],
        "done_when": "无同案人则跳过并注明；有则「同案人供述」已登记且含 full_text",
        "detail": (
            "1. 从起诉书识别同案人；无同案人则说明后跳过。\n"
            "2. 有则 search_volumes 定位其讯问笔录，"
            "record_statement(role='codefendant')（字段同被告，含 full_text）。\n"
            "3. 记录是否指认被告人及与被告供述是否一致。"
        ),
    },
    {
        "id": "witness-statement-extractor",
        "title": "提取证人证言",
        "goal": "整理证人证言（询问笔录），逐字转录问答全文",
        "tools": [
            "search_volumes", "read_pages", "record_statement", "get_workspace_summary",
        ],
        "done_when": "相关询问笔录均已 record_statement(role='witness') 且含 full_text",
        "detail": (
            "1. search_volumes 检索「询问笔录」「证人」定位。\n"
            "2. record_statement(role='witness')：person、时间/办案人/地点/同步录音录像、"
            "content_summary、**full_text**（金额/账户/日期等原样保留）。\n"
            "3. 行受贿类案件行贿人/知情人证言须完整记录。"
        ),
    },
    {
        "id": "procedural-extractor",
        "title": "提取程序性文书",
        "goal": "整理从被调查至当前的全部程序性文书（含文号）",
        "tools": [
            "search_volumes", "read_pages", "record_procedural_doc", "get_workspace_summary",
        ],
        "done_when": "「程序性文书」已覆盖立案至当前主链条；文号尽量齐全",
        "detail": (
            "1. search_volumes 检索立案/拘留/逮捕/取保/搜查/扣押/鉴定/移送/起诉等。\n"
            "2. record_procedural_doc：类型、卷宗、页码、**文号 doc_no**、时间、地点、内容。\n"
            "3. 按时间顺序覆盖完整程序链条。"
        ),
    },
    {
        "id": "evidence-extractor",
        "title": "提取书证与资金流水",
        "goal": "按待证事实分组整理书证；流水类逐笔登记",
        "tools": [
            "get_volume_outline", "read_pages", "record_documentary_evidence",
            "add_transaction", "get_workspace_summary",
        ],
        "done_when": "客观书证已登记；流水类已用 add_transaction 逐笔登记",
        "detail": (
            "1. get_volume_outline 浏览各卷识别合同/流水/转账/登记资料/审计/鉴定/任职文件等。\n"
            "2. record_documentary_evidence（名称/时间/页码/来源/主要内容/fact_group/doc_no）。\n"
            "3. 流水类书证必须 add_transaction 逐笔登记（日期/收付方/金额/账户/页码）。"
        ),
    },
    {
        "id": "conclusion-synthesizer",
        "title": "形成阅卷结论",
        "goal": "提炼核心事实/证据链/矛盾点/疑点，并登记资金勾稽摘要",
        "tools": [
            "get_workspace_summary", "read_pages", "record_conclusions",
            "record_funds_summary",
        ],
        "done_when": "已 record_conclusions 与 record_funds_summary",
        "detail": (
            "1. get_workspace_summary 查看整体；必要时 read_pages 复核。\n"
            "2. record_conclusions：core_facts / evidence_chain / contradictions / doubts"
            "（重点比对各次供述全文不一致）。\n"
            "3. record_funds_summary：报案/合同/指控/已返还/违法所得/已退赔；口径不一致在 note 说明。\n"
            "4. 仅做案情梳理，不输出正式辩护策略。"
        ),
    },
    {
        "id": "validate-and-export",
        "title": "校验引用并导出",
        "goal": "校验全部来源页码合法性，生成 Word 笔录与 Excel 目录并取件",
        "tools": [
            "validate_citations", "write_outputs", "download_output", "get_case_status",
        ],
        "done_when": "validate_citations 无严重问题；已 write_outputs；可 download_output(docx|xlsx)",
        "detail": (
            "1. validate_citations 校验全部引用页码。\n"
            "2. write_outputs 生成阅卷笔录(docx)与阅卷目录(xlsx)。\n"
            "3. download_output(fmt='docx'|'xlsx') 取回文件。"
        ),
    },
]


def get_playbook(case_id: str | None = None) -> dict[str, Any]:
    """返回宿主可执行的结构化阅卷 playbook."""
    return {
        "mode": "host_agent",
        "message": (
            "本服务不启动后台 LLM job。请由宿主 Agent（Cursor / Kimi / OpenCode / Codex 等）"
            "按 steps 顺序调用 MCP 工具完成阅卷。完整说明见仓库 skills/vibelawyer-review/SKILL.md。"
        ),
        "case_id": case_id,
        "common_rules": COMMON_RULES,
        "mcp_call_hint": MCP_CALL_HINT,
        "steps": REVIEW_STEPS,
        "skill_path": "skills/vibelawyer-review/SKILL.md",
    }


def playbook_markdown() -> str:
    """渲染为 Markdown（写入 Skill 或 CLI 指引时可复用）."""
    lines = [
        "# 刑事案件阅卷工作流（宿主 Agent）",
        "",
        MCP_CALL_HINT,
        "",
        COMMON_RULES,
        "",
        "## 标准步骤",
        "",
    ]
    for i, step in enumerate(REVIEW_STEPS, 1):
        lines.append(f"### {i}. {step['title']} (`{step['id']}`)")
        lines.append("")
        lines.append(f"**目标：** {step['goal']}")
        lines.append("")
        lines.append(f"**工具：** {', '.join(f'`{t}`' for t in step['tools'])}")
        lines.append("")
        lines.append(f"**完成判据：** {step['done_when']}")
        lines.append("")
        lines.append(step["detail"])
        lines.append("")
    return "\n".join(lines)
