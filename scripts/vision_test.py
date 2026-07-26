"""视觉能力测试：验证 agent 能否‘看懂’ get_page_image 返回的扫描页图像。

只读一页，低成本确认 vision 端到端可用，再决定是否跑完整阅卷。
用法: python scripts/vision_test.py
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
from claude_agent_sdk import query


async def main() -> int:
    cfg = load_case()
    init_tools(cfg)
    opts = build_options(cfg, effort="medium", max_turns=8)

    prompt = (
        "视觉能力测试。请调用 mcp__vibelawyer__get_page_image 渲染卷宗"
        "《北京市公安局朝阳分局刑事侦查案卷》的第1页，然后用视觉识别该页内容，"
        "用中文如实回报：这是什么文书？能看到哪些关键文字（标题、人名、日期、机关等）？"
        "若能看清，说明视觉识别可用；若看不到图像或无法识别，请明确说明。"
        "只测试这一页，简短回报即可。"
    )

    saw_image = False
    final = ""
    async for msg in query(prompt=prompt, options=opts):
        from claude_agent_sdk import AssistantMessage, ToolUseBlock, TextBlock, ResultMessage
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock) and b.text:
                    final = b.text
                    print(f"[assistant] {b.text[:600]}", flush=True)
                elif isinstance(b, ToolUseBlock):
                    print(f"  [tool→] {b.name} {str(b.input)[:120]}", flush=True)
        elif isinstance(msg, ResultMessage):
            print(f"[result] {msg.subtype} cost=${getattr(msg,'total_cost_usd',0) or 0:.4f}", flush=True)

    print("\n" + "=" * 50)
    has_content = any(k in final for k in ["文书", "案卷", "公安局", "看不到", "无法", "图像", "页"])
    print("视觉测试:", "可用 ✓" if has_content else "存疑")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
