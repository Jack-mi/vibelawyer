"""[LEGACY] 需 pip install 'vibelawyer[legacy-agent]' + 本机 Claude Code CLI。

最小冒烟测试：验证 主agent MCP工具调用 + Task委派子agent + 子agent 工具访问。
默认产品路径请用 scripts/diag.py + vibelawyer-mcp + skills/vibelawyer-review/SKILL.md。
用法: python scripts/smoke_test.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vibelawyer.config import load_case
from vibelawyer.orchestrator import build_options
from vibelawyer.tools import init_tools
from vibelawyer.workspace import get_workspace
from claude_agent_sdk import query


async def main() -> int:
    cfg = load_case()
    ws = init_tools(cfg)
    opts = build_options(cfg, effort="medium", max_turns=15)

    prompt = (
        "冒烟测试，请严格按序执行并简短回报：\n"
        "1. 调用 list_volumes 报告卷宗数量与名称。\n"
        "2. 用 Task 工具委派 'case-indexer' 子 agent：让它调用 list_volumes 并返回卷宗清单。\n"
        "3. 调用 get_workspace_summary 报告当前工作区状态。\n"
        "完成后用一句话总结：主agent工具是否可用、子agent是否成功调用工具。"
    )

    saw_tools = False
    saw_subagent = False
    final = ""
    async for msg in query(prompt=prompt, options=opts):
        from claude_agent_sdk import AssistantMessage, ToolUseBlock, TextBlock, ResultMessage
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock) and b.text:
                    final = b.text
                    print(f"[assistant] {b.text[:300]}", flush=True)
                elif isinstance(b, ToolUseBlock):
                    saw_tools = True
                    print(f"  [tool→] {b.name} {str(b.input)[:120]}", flush=True)
                    if b.name.lower() in ("task", "agent"):
                        saw_subagent = True
        elif isinstance(msg, ResultMessage):
            print(f"[result] {msg.subtype} cost=${getattr(msg,'total_cost_usd',0) or 0:.4f}", flush=True)

    print("\n" + "=" * 50)
    print(f"主agent调用工具: {'✓' if saw_tools else '✗'}")
    print(f"委派子agent(Task): {'✓' if saw_subagent else '✗'}")
    print(f"工作区卷数登记: {ws.volume_count}")
    ok = saw_tools and ws.volume_count > 0
    print("结论:", "通过 —— 可进入完整阅卷" if ok else "需排查")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
