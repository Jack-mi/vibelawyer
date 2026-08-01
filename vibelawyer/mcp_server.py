"""vibelawyer FastMCP Server —— 把阅卷系统封装为可对外部署的 MCP 服务.

工具面（均带 case_id，对应 `output/OpenCode会话任务轨迹.md` 任务 #3）:
  生命周期: create_case / list_cases / get_case_status
  读卷:     list_volumes / get_volume_outline / read_pages / search_volumes / get_page_image
  登记:     set_case_basic / record_party / record_indictment / add_charged_fact / record_statement
            / record_procedural_doc / record_documentary_evidence / add_transaction
            / add_catalog_entry / record_conclusions / record_funds_summary
  校验导出: validate_citations / get_workspace_summary / write_outputs / download_output
  全流程:   start_review（后台线程跑 run_case，立即返回）/ get_review_progress

实现方式（薄封装）: 读/登记/校验/导出类工具直接复用 tools.py 的 SdkMcpTool.handler，
bind 会话后 `await tool.handler(args)`，零逻辑重复；仅生命周期与全流程工具为本模块专有。
并发约束（v1）: 全流程阅卷 job 运行期间，其他案件的交互式工具调用会被拒绝
（进程内 SDK 工具依赖模块级活动会话绑定，切换会串号）；同一案件的查询不受影响。

启动:
  stdio（本机调试）: VIBELAWYER_MCP_TRANSPORT=stdio python -m vibelawyer.mcp_server
  http（对外部署）:  VIBELAWYER_MCP_TRANSPORT=http VIBELAWYER_MCP_PORT=8000 python -m vibelawyer.mcp_server
  鉴权（可选）:      VIBELAWYER_MCP_TOKEN=<secret> 启用 StaticTokenVerifier
"""
from __future__ import annotations

import asyncio
import os
import threading
import typing
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.utilities.types import File

from .config import DEFAULT_OUTPUT_DIR, load_case
from .orchestrator import run_case
from .sessions import MANAGER, CaseSession
from .tools import bind_session, get_tools

# MCP 服务默认开启视觉（get_page_image 可用）；按部署环境可经 env 关闭
_VISION = os.environ.get("VIBELAWYER_MCP_VISION", "1") != "0"

# 复用 tools.py 的 SDK 工具集；SdkMcpTool = {name, description, input_schema, handler}
_SDK_TOOLS: dict[str, Any] = {t.name: t for t in get_tools(_VISION)}


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
        "刑事案件阅卷 Agent 服务。先 create_case 登记 case_dir，再按需调用读卷/登记工具，"
        "或 start_review 一键跑全流程后 get_review_progress 轮询、download_output 取件。"
        "全流程 job 运行期间不支持他案并发调用。"
    ),
    auth=_make_auth(),
)


def _bind_or_reject(case_id: str) -> CaseSession:
    """绑定活动会话；若他案 job 正在运行则拒绝（v1 单进程单 job）."""
    session = MANAGER.get(case_id)  # KeyError → 客户端可见 404 文案
    running = MANAGER.running_session()
    if running is not None and running.case_id != case_id and running.job_status == "running":
        raise RuntimeError(
            f"他案阅卷 job 正在运行（case_id={running.case_id}），v1 暂不支持并发，请稍后重试"
        )
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
    tool = _SDK_TOOLS[name]
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
    """创建案件会话：发现 case_dir 下卷宗 PDF，登记页数（不预转换 docling，首次 start_review 约 4 分钟/54 页）.
    返回 case_id 与卷宗清单。"""
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
        "message": "已建会话。可交互式调用读卷/登记工具，或 start_review 一键全流程。",
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
    """查询案件会话当前状态（含工作区登记计数与 job 状态）."""
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
# 全流程工具（本模块专有）
# ==========================================================================

async def _start_review(case_id: str, model: str = "", effort: str = "high",
                        max_turns: int = 100) -> dict:
    """启动全流程阅卷 job（后台线程跑 run_case），立即返回；期间用 get_review_progress 轮询.
    v1 单进程同时只允许一个 job；job 期间他案交互式调用会被拒绝，同案查询不受影响。
    """
    session = MANAGER.get(case_id)
    running = MANAGER.running_session()
    if running is not None and running.job_status == "running":
        raise RuntimeError(
            f"已有阅卷 job 在运行（case_id={running.case_id}），v1 单进程单 job，请待其完成或重启服务"
        )
    session.job_status = "running"
    session.job_step = "启动阅卷流程"
    session.job_log = []
    session.job_result = None
    session.job_error = None
    session.log(f"[start] case_id={case_id} model={model or 'default'} effort={effort}")

    def _run() -> None:
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                run_case(
                    session.cfg,
                    model=model or None,
                    effort=effort,
                    max_turns=max_turns,
                    verbose=True,
                    session=session,
                    progress=lambda m: session.log(m),
                )
            )
            session.job_status = "done"
            session.job_result = result
            session.log("[done] 阅卷流程完成")
        except Exception as e:  # noqa: BLE001
            session.job_status = "error"
            session.job_error = str(e)
            session.log(f"[error] {e}")
        finally:
            loop.close()

    threading.Thread(target=_run, daemon=True, name=f"vibelawyer-{case_id}").start()
    return {"case_id": case_id, "status": "running",
            "message": "阅卷 job 已启动；用 get_review_progress 轮询进度。"}


async def _get_review_progress(case_id: str) -> dict:
    """轮询全流程阅卷 job 进度：status/step/log 尾部/结果/错误."""
    session = MANAGER.get(case_id)
    return {
        "case_id": case_id,
        "status": session.job_status,
        "step": session.job_step,
        "log_tail": session.job_log[-15:],
        "result": session.job_result,
        "error": session.job_error,
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
