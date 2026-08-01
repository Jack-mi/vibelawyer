"""可选 legacy 编排：经 Claude Agent SDK + Claude Code CLI 跑全流程.

默认产品路径是 FastMCP + 宿主 Agent Skill（见 playbook.py / skills/vibelawyer-review）。
本模块仅在 `pip install vibelawyer[legacy-agent]` 且本机有 Claude Code CLI 时可用。
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

from .agents import STEP_PROMPTS, SUBAGENT_ORDER
from .config import CaseConfig
from .playbook import COMMON_RULES, REVIEW_STEPS
from .sessions import MANAGER, CaseSession
from .tools import bind_session, get_tools, init_tools
from .workspace import get_workspace

MCP_SERVER_NAME = "vibelawyer"

_DISALLOWED_TOOLS = [
    "Bash", "Read", "Edit", "Write", "NotebookEdit",
    "Grep", "Glob", "LS",
    "WebFetch", "WebSearch", "Skill",
    "TaskOutput", "TaskStop",
]

_LEGACY_HINT = (
    "legacy 全流程需要：pip install 'vibelawyer[legacy-agent]'，且本机已安装并登录 Claude Code CLI。"
    "推荐改用 MCP：vibelawyer-mcp + skills/vibelawyer-review/SKILL.md。"
)


def _require_sdk():
    try:
        from claude_agent_sdk import (  # noqa: F401
            ClaudeAgentOptions,
            create_sdk_mcp_server,
            query,
        )
        return ClaudeAgentOptions, create_sdk_mcp_server, query
    except ImportError as e:
        raise ImportError(_LEGACY_HINT) from e


def _sdk_tools(vision_available: bool):
    """把本地 ToolSpec 适配为 SDK create_sdk_mcp_server 可接受的工具列表."""
    ClaudeAgentOptions, create_sdk_mcp_server, query = _require_sdk()  # noqa: F841
    from claude_agent_sdk import tool as sdk_tool

    specs = get_tools(vision_available)
    out = []
    for spec in specs:
        # 用 SDK @tool 重新包装同一 handler，避免 SdkMcpTool 类型不匹配
        wrapped = sdk_tool(spec.name, spec.description, spec.input_schema)(spec.handler)
        out.append(wrapped)
    return out


def _agent_ns(name: str) -> SimpleNamespace:
    meta = STEP_PROMPTS[name]
    return SimpleNamespace(
        description=meta["description"],
        prompt=meta["prompt"],
        maxTurns=60,
    )


def _flow_tasks() -> list[tuple[str, str]]:
    """与 playbook 对齐的顺序任务（不含 validate-and-export，由本函数收尾）."""
    return [
        (s["id"], s["detail"].replace("\n", " "))
        for s in REVIEW_STEPS
        if s["id"] != "validate-and-export"
    ]


MAIN_SYSTEM_PROMPT = """你是「刑事案件阅卷主 Agent」，负责编排整个阅卷梳理流程。
（legacy 模式；推荐改用宿主 Agent + MCP Skill。）

按序委派子步骤完成目录、起诉书、供述、证言、程序、书证、结论，再校验并导出。
""" + "\n" + COMMON_RULES


def build_options(cfg: CaseConfig, *, model: str | None = None, effort: str = "high",
                  max_turns: int = 100):
    """装配主 agent 运行选项（legacy）."""
    ClaudeAgentOptions, create_sdk_mcp_server, _query = _require_sdk()
    tools = _sdk_tools(cfg.vision_available)
    mcp_server = create_sdk_mcp_server(MCP_SERVER_NAME, "1.0.0", tools=tools)
    allowed = [f"mcp__{MCP_SERVER_NAME}__{t.name}" for t in tools] + ["Task", "TodoWrite"]
    opts = ClaudeAgentOptions(
        system_prompt=MAIN_SYSTEM_PROMPT + _vision_note(cfg.vision_available),
        mcp_servers={MCP_SERVER_NAME: mcp_server},
        allowed_tools=allowed,
        disallowed_tools=_DISALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        cwd=str(cfg.case_dir),
        add_dirs=[str(cfg.case_dir)],
        max_turns=max_turns,
        effort=effort,  # type: ignore[arg-type]
        max_buffer_size=16 * 1024 * 1024,
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
    """端到端运行阅卷流程（legacy：Claude Code CLI 多会话）."""
    ClaudeAgentOptions, create_sdk_mcp_server, query = _require_sdk()

    def _emit(msg: str) -> None:
        if progress is not None:
            progress(msg)
        if verbose:
            print(msg, flush=True)

    if session is not None:
        MANAGER.ensure_docling_cache(session, verbose=verbose)
        ws = bind_session(session).workspace
    else:
        ws = init_tools(cfg, use_docling=True, verbose=verbose)
    server = create_sdk_mcp_server(
        MCP_SERVER_NAME, "1.0.0", tools=_sdk_tools(cfg.vision_available)
    )
    hint = (
        f"{'当事人：' + cfg.defendant_hint + '。' if cfg.defendant_hint else ''}"
        f"{'涉嫌罪名：' + cfg.charge_hint + '。' if cfg.charge_hint else ''}"
    )

    sub_summary = []
    catalog_briefing = ""
    for name, task in _flow_tasks():
        if name not in STEP_PROMPTS:
            continue
        _emit(f"\n========== 委派子 agent: {name} ==========")
        ad = _agent_ns(name)
        full_task = task + " " + hint
        if name != "case-indexer" and catalog_briefing:
            full_task += (
                "\n\n【卷宗目录摘要（case-indexer 已编制，据此定位文书，勿遗漏任何卷）】\n"
                + catalog_briefing
            )
        ok, summary = await _run_subagent(
            ad, full_task, cfg, server, query, ClaudeAgentOptions,
            model=model, effort=effort, verbose=verbose,
        )
        sub_summary.append((name, ok, summary))
        ws_now = get_workspace()
        counts = _section_counts(ws_now)
        _emit(f"[核实] {name} 后工作区: {counts}")
        if name == "case-indexer" and not catalog_briefing:
            catalog_briefing = _build_catalog_briefing(ws_now)

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
                        query, ClaudeAgentOptions, *, model: str | None = None,
                        effort: str = "high", verbose: bool = True) -> tuple[bool, str]:
    tools = _sdk_tools(cfg.vision_available)
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
        stderr=lambda s: print(
            f"[cli:{agent_def.description[:12]}] {s}", file=sys.stderr
        ) if s.strip() else None,
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
    if not ws.catalog:
        return ""
    lines = []
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
        "结论核心/矛盾/疑点": (
            f"{len(ws.conclusions.core_facts)}/"
            f"{len(ws.conclusions.contradictions)}/"
            f"{len(ws.conclusions.doubts)}"
        ),
    }


def _extract_result_text(content) -> str:
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
    if isinstance(msg, dict):
        if msg.get("type") == "assistant":
            for block in msg.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
    return ""


def _log_message(msg) -> None:
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
            for b in (getattr(msg, "content", None) or []):
                if isinstance(b, ToolResultBlock):
                    content = getattr(b, "content", None)
                    txt = _extract_result_text(content)
                    print(f"  [tool←] {txt[:140]}", flush=True)
        elif isinstance(msg, ResultMessage):
            print(
                f"\n[result] {msg.subtype} cost=${getattr(msg, 'total_cost_usd', 0) or 0:.4f} "
                f"turns={getattr(msg, 'num_turns', '?')}",
                flush=True,
            )
    except Exception:
        pass


# 避免 unused import 告警：SUBAGENT_ORDER 供外部发现步骤
__all__ = ["run_case", "build_options", "SUBAGENT_ORDER", "MCP_SERVER_NAME"]
