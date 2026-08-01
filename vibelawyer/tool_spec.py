"""本地 MCP 工具注册器（不依赖 claude-agent-sdk）.

提供与历史 SdkMcpTool 相同的表面：name / description / input_schema / handler，
供 FastMCP passthrough 与 diag 脚本直接调用 handler。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Awaitable


Handler = Callable[[dict], Awaitable[dict]]


@dataclass(frozen=True)
class ToolSpec:
    """原子工具规格：元数据 + 异步 handler."""

    name: str
    description: str
    input_schema: Any  # TypedDict 类或 {}
    handler: Handler


def tool(name: str, description: str, input_schema: Any = None):
    """装饰异步 handler，返回 ToolSpec（可放入 get_tools() 列表）."""

    def decorator(fn: Handler) -> ToolSpec:
        return ToolSpec(
            name=name,
            description=description,
            input_schema=input_schema if input_schema is not None else {},
            handler=fn,
        )

    return decorator
