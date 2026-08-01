"""vibelawyer FastMCP Server —— 本地阅卷工具箱（不依赖 Claude Code CLI）.

工具面（均带 case_id）:
  生命周期: create_case / list_cases / get_case_status
  读卷:     list_volumes / get_volume_outline / read_pages / search_volumes / get_page_image
  登记:     set_case_basic / record_party / record_indictment / add_charged_fact / record_statement
            / record_procedural_doc / record_documentary_evidence / add_transaction
            / add_catalog_entry / record_conclusions / record_funds_summary
  校验导出: validate_citations / get_workspace_summary / write_outputs / download_output
  工作流:   start_review（下发 playbook，由宿主 Agent 按步执行）/ get_review_progress

实现方式（薄封装）: 读/登记/校验/导出类工具直接复用 tools.py 的 ToolSpec.handler，
bind 会话后 `await tool.handler(args)`，零逻辑重复。

启动:
  stdio（默认）: VIBELAWYER_MCP_TRANSPORT=stdio python -m vibelawyer.mcp_server
  http:          VIBELAWYER_MCP_TRANSPORT=http VIBELAWYER_MCP_PORT=8000 python -m vibelawyer.mcp_server
  鉴权（可选）:  VIBELAWYER_MCP_TOKEN=<secret> 启用 StaticTokenVerifier
"""
from __future__ import annotations

import os
import typing
from typing import Any

from fastmcp import FastMCP
from fastmcp.utilities.types import File

from .config import DEFAULT_OUTPUT_DIR, load_case
from .playbook import get_playbook
from .sessions import MANAGER, CaseSession
from .tools import bind_session, get_tools

# MCP 服务默认开启视觉（get_page_image 可用）；按部署环境可经 env 关闭
_VISION = os.environ.get("VIBELAWYER_MCP_VISION", "1") != "0"

# 复用 tools.py 的 ToolSpec 集
_TOOLS: dict[str, Any] = {t.name: t for t in get_tools(_VISION)}


def _make_auth() -> Any:
    """按 env VIBELAWYER_MCP_TOKEN 启用 StaticTokenVerifier；未设则无鉴权（本机 stdio）."""
    token = os.environ.get("VIBELAWYER_MCP_TOKEN")
    if not token:
        return None
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
    return StaticTokenVerifier(tokens={token: {}})


mcp = FastMCP(
    "vibelawyer",
    instructions=(
        "刑事案件阅卷 MCP 工具箱（本机处理卷宗，不依赖 Claude Code）。"
        "流程：create_case → start_review 获取 playbook → 按 steps 调用读卷/登记工具 → "
        "validate_citations → write_outputs → download_output。"
        "完整步骤见仓库 skills/vibelawyer-review/SKILL.md。"
        "LLM 推理由宿主 Agent（Cursor / Kimi / OpenCode / Codex 等）提供。"
    ),
    auth=_make_auth(),
)


def _bind_or_reject(case_id: str) -> CaseSession:
    """绑定活动会话."""
    session = MANAGER.get(case_id)
    bind_session(session)
    return session


# ==========================================================================
# 读卷 / 登记 / 校验导出工具：动态注册，薄封装复用 tools.py handler
# ==========================================================================

_PASSTHROUGH = [
    "list_volumes", "get_volume_outline", "read_pages", "search_volumes", "get_page_image",
    "set_case_basic", "record_party", "record_indictment", "add_charged_fact", "record_statement",
    "record_procedural_doc", "record_documentary_evidence", "add_transaction", "add_catalog_entry",
    "record_conclusions", "record_funds_summary", "validate_citations", "get_workspace_summary",
    "write_outputs",
]


def _schema_hint(typed_dict_cls: Any) -> str:
    """从 TypedDict 提取字段名+必填性+Annotated 描述，生成可读 args 结构提示."""
    if typed_dict_cls is None:
        return "{}"
    try:
        hints = typing.get_type_hints(typed_dict_cls, include_extras=True)
    except Exception:
        hints = getattr(typed_dict_cls, "__annotations__", {}) or {}
    required = set(getattr(typed_dict_cls, "__required_keys__", set()) or set())
    parts: list[str] = []
    for k, ann in hints.items():
        desc = ""
        args = typing.get_args(ann)
        for m in args[1:] if args else []:
            if isinstance(m, str):
                desc = m
                break
        mark = "(必填)" if k in required else ""
        parts.append(f"{k}{mark}: {desc}" if desc else f"{k}{mark}")
    return "{" + "; ".join(parts) + "}" if parts else "{}"


def _register_passthrough(name: str) -> None:
    tool = _TOOLS[name]
    desc = tool.description or ""
    full_desc = f"{desc}\n\n参数结构（args 字段）: {_schema_hint(tool.input_schema)}"

    async def _fn(case_id: str, args: dict[str, Any] | None = None) -> dict:
        session = _bind_or_reject(case_id)
        session.log(f"[mcp] {name}")
        return await tool.handler(args or {})

    _fn.__name__ = name
    _fn.__doc__ = full_desc
    mcp.add_tool(_fn)


for _t in _PASSTHROUGH:
    _register_passthrough(_t)


# ==========================================================================
# 生命周期工具（本模块专有）
# ==========================================================================

async def _create_case(case_dir: str, output_dir: str = "",
                       defendant_hint: str = "", charge_hint: str = "",
                       vision_available: bool = True) -> dict:
    """创建案件会话：发现 case_dir 下卷宗 PDF，登记页数。返回 case_id 与卷宗清单.
    随后可 start_review 获取宿主执行 playbook，或直接调用读卷/登记工具。"""
    cfg = load_case(
        case_dir=case_dir,
        output_dir=output_dir or DEFAULT_OUTPUT_DIR,
        defendant_hint=defendant_hint or None,
        charge_hint=charge_hint or None,
        vision_available=vision_available,
    )
    session = MANAGER.create(cfg, verbose=False)
    return {
        "case_id": session.case_id,
        "case_dir": str(cfg.case_dir),
        "output_dir": str(cfg.output_dir),
        "volumes": [{"name": v.name, "file": v.path.name, "pages": v.pages} for v in cfg.volumes],
        "volume_count": len(cfg.volumes),
        "message": (
            "已建会话。请调用 start_review 获取标准阅卷 playbook，"
            "或直接按 skills/vibelawyer-review/SKILL.md 调用读卷/登记工具。"
        ),
    }


async def _list_cases() -> dict:
    """列出全部案件会话及状态."""
    return {"cases": [
        {
            "case_id": s.case_id,
            "case_dir": str(s.cfg.case_dir),
            "defendant": s.workspace.defendant or "",
            "charge": s.workspace.charge or "",
            "volume_count": s.cfg.volumes and len(s.cfg.volumes),
            "status": s.job_status,
            "step": s.job_step or "",
        }
        for s in MANAGER.list()
    ]}


async def _get_case_status(case_id: str) -> dict:
    """查询案件会话当前状态（含工作区登记计数）."""
    session = MANAGER.get(case_id)
    ws = session.workspace
    tx_count = sum(len(e.transactions) for e in ws.documentary_evidence)
    return {
        "case_id": case_id,
        "case_name": ws.case_name,
        "defendant": ws.defendant,
        "charge": ws.charge,
        "total_amount": ws.total_amount,
        "volume_count": ws.volume_count,
        "section_counts": {
            "目录": len(ws.catalog),
            "当事人": 1 if ws.party.name else 0,
            "起诉书": 1 if ws.indictment.doc_type else 0,
            "指控事实": len(ws.indictment.facts),
            "被告人供述": len(ws.defendant_statements),
            "同案人供述": len(ws.codefendant_statements),
            "证人证言": len(ws.witness_statements),
            "程序性文书": len(ws.procedural_docs),
            "书证": len(ws.documentary_evidence),
            "资金流水笔数": tx_count,
        },
        "job_status": session.job_status,
        "job_step": session.job_step,
        "log_tail": session.job_log[-10:],
        "job_error": session.job_error,
    }


for _fn in (_create_case, _list_cases, _get_case_status):
    _fn.__name__ = _fn.__name__.lstrip("_")
    mcp.add_tool(_fn)


# ==========================================================================
# 工作流工具：下发 playbook（宿主 Agent 自行编排，无后台 LLM job）
# ==========================================================================

async def _start_review(case_id: str, model: str = "", effort: str = "high",
                        max_turns: int = 100) -> dict:
    """下发标准阅卷 playbook，由宿主 Agent 按 steps 顺序调用 MCP 工具完成阅卷.

    不再启动后台 Claude/LLM job（不依赖 Claude Code CLI）。
    model / effort / max_turns 由宿主自行决定，本参数仅保留兼容、写入提示。
    进度请用 get_case_status / get_workspace_summary 查看登记计数。
    """
    session = MANAGER.get(case_id)
    session.job_status = "idle"
    session.job_step = "host_agent_playbook"
    session.job_result = None
    session.job_error = None
    session.log(
        f"[playbook] case_id={case_id} "
        f"(host agent; model/effort hints ignored by server: {model or '-'} / {effort})"
    )
    playbook = get_playbook(case_id=case_id)
    playbook["status"] = "idle"
    playbook["host_hints"] = {
        "model": model or None,
        "effort": effort,
        "max_turns": max_turns,
        "note": "由宿主 Agent 使用自身模型执行；服务端不调用 LLM。",
    }
    return playbook


async def _get_review_progress(case_id: str) -> dict:
    """查询阅卷进度：无后台 job；请结合 get_case_status 的 section_counts 判断宿主执行进度."""
    session = MANAGER.get(case_id)
    return {
        "case_id": case_id,
        "status": "idle",
        "mode": "host_agent",
        "step": session.job_step or "host_agent_playbook",
        "message": (
            "本服务不运行后台阅卷 job。请按 start_review 返回的 playbook / "
            "skills/vibelawyer-review/SKILL.md 逐步调用工具；"
            "用 get_case_status 查看各部分登记计数。"
        ),
        "log_tail": session.job_log[-15:],
        "result": session.job_result,
        "error": session.job_error,
        "playbook": get_playbook(case_id=case_id),
    }


async def _download_output(case_id: str, fmt: str = "docx") -> File:
    """下载已生成的阅卷笔录(docx)或阅卷目录(xlsx)；若文件未生成则按当前工作区即时渲染兜底.
    fmt: 'docx' | 'xlsx'."""
    session = MANAGER.get(case_id)
    ws = session.workspace
    out_dir = session.cfg.ensure_output_dir()
    safe = (ws.case_name or case_id).replace("/", "_").replace(" ", "")
    if fmt == "docx":
        path = out_dir / f"{safe}_阅卷笔录.docx"
        if not path.exists():
            bind_session(session)
            from .generators.docx_notes import generate_review_notes
            path = generate_review_notes(ws, out_dir)
    elif fmt == "xlsx":
        path = out_dir / f"{safe}_阅卷目录.xlsx"
        if not path.exists():
            bind_session(session)
            from .generators.xlsx_catalog import generate_catalog_xlsx
            path = generate_catalog_xlsx(ws, out_dir)
    else:
        raise ValueError("fmt 仅支持 docx / xlsx")
    return File(data=path.read_bytes(), name=path.name)


for _fn in (_start_review, _get_review_progress, _download_output):
    _fn.__name__ = _fn.__name__.lstrip("_")
    mcp.add_tool(_fn)


# ==========================================================================
# 启动入口
# ==========================================================================

def main() -> None:
    """启动 vibelawyer MCP Server（stdio 本机 / http 对外部署，由 env 切换）."""
    transport = os.environ.get("VIBELAWYER_MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.run(
            transport="http",
            host=os.environ.get("VIBELAWYER_MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("VIBELAWYER_MCP_PORT", "8000")),
            path=os.environ.get("VIBELAWYER_MCP_PATH", "/mcp"),
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
