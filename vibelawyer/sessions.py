"""案件会话注册表（CaseSession / SessionManager）.

把「运行配置 CaseConfig + 卷宗存储 VolumeStore + 工作区 CaseWorkspace + 全流程任务状态」
打包为一个按 case_id 隔离的会话。本地 CLI（run.py）一次只跑一个案件，FastMCP 服务
（mcp_server.py）则可同时登记多个案件会话；工具层通过 bind_session 切换“活动会话”。

并发约束（v1）：全流程阅卷 job 运行期间，其他案件的交互式工具调用会被拒绝
（进程内 SDK 工具依赖模块级活动会话绑定，切换会串号）；同一案件的查询不受影响。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import CaseConfig
from .pdf_volume import VolumeStore
from .workspace import CaseWorkspace


@dataclass
class CaseSession:
    """一个案件的完整运行态."""

    case_id: str
    cfg: CaseConfig
    store: VolumeStore
    workspace: CaseWorkspace
    created_at: float
    docling_dir: Path | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)
    # 全流程阅卷任务状态（start_review 填充）
    job_status: str = "idle"  # idle / running / done / error
    job_step: str = ""
    job_log: list[str] = field(default_factory=list)
    job_result: dict | None = None
    job_error: str = ""

    def log(self, msg: str) -> None:
        with self.lock:
            self.job_log.append(msg)
            if len(self.job_log) > 500:
                del self.job_log[: len(self.job_log) - 500]


class SessionManager:
    """进程内会话注册表（线程安全）."""

    def __init__(self) -> None:
        self._sessions: dict[str, CaseSession] = {}
        self._lock = threading.RLock()

    def create(self, cfg: CaseConfig, *, use_docling: bool = True, verbose: bool = False) -> CaseSession:
        """建立会话：解析 docling 缓存目录（不预转换）、建卷宗存储、登记卷宗页数."""
        import os

        if os.environ.get("VIBELAWYER_NO_DOCLING"):
            use_docling = False
        docling_dir = None
        if use_docling:
            from . import docling_cache
            if docling_cache.docling_available():
                docling_dir = docling_cache.cache_dir_for(cfg.output_dir)
        store = VolumeStore(cfg, docling_cache_dir=docling_dir)
        ws = CaseWorkspace()
        for v in cfg.volumes:
            ws.register_volume(v.name, store.page_count(v.name))
        ws.volume_count = len(cfg.volumes)
        session = CaseSession(
            case_id=uuid.uuid4().hex[:12],
            cfg=cfg,
            store=store,
            workspace=ws,
            created_at=time.time(),
            docling_dir=docling_dir,
        )
        with self._lock:
            self._sessions[session.case_id] = session
        return session

    def ensure_docling_cache(self, session: CaseSession, *, verbose: bool = False) -> None:
        """按需预转换 docling 缓存（首次较慢）；无 docling 环境时静默跳过."""
        if session.docling_dir is None:
            return
        from . import docling_cache
        have = bool(session.cfg.volumes) and all(
            docling_cache.get_cached_page_count(v.name, session.docling_dir) is not None
            for v in session.cfg.volumes
        )
        if not have:
            session.log("[init] 预转换 docling 缓存（首次较慢，模型加载+OCR）...")
            docling_cache.build_docling_cache(session.cfg.volumes, session.docling_dir, verbose=verbose)

    def get(self, case_id: str) -> CaseSession:
        with self._lock:
            s = self._sessions.get(case_id)
        if s is None:
            raise KeyError(f"案件会话不存在: {case_id}（请先 create_case）")
        return s

    def list(self) -> list[CaseSession]:
        with self._lock:
            return sorted(self._sessions.values(), key=lambda s: s.created_at)

    def running_session(self) -> CaseSession | None:
        with self._lock:
            for s in self._sessions.values():
                if s.job_status == "running":
                    return s
        return None


MANAGER = SessionManager()
