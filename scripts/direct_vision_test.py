"""[LEGACY] 需 pip install 'vibelawyer[legacy-agent]' + 本机 Claude Code CLI。

直接视觉测试：把图像直接放在 user message 里（而非工具返回），验证子会话是否有视觉能力。
若能看懂 → 视觉可用，问题在 MCP 工具结果传图链路；
若看不懂 → 子会话/代理本身无视觉，需改用本地 OCR。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vibelawyer.config import load_case
from vibelawyer.pdf_volume import VolumeStore
from claude_agent_sdk import ClaudeAgentOptions, query


async def main() -> int:
    cfg = load_case()
    store = VolumeStore(cfg)
    vol = store.get("北京市公安局朝阳分局刑事侦查案卷")
    b64, mime = vol.get_page_image_b64(1)
    print(f"image: {len(b64)} chars, {mime}, raw≈{len(b64)*3/4/1024:.0f}KB")

    opts = ClaudeAgentOptions(
        system_prompt="你是一个能看图的多模态助手。请如实描述看到的图像内容，看不到就说看不到。",
        permission_mode="bypassPermissions",
        max_turns=2,
        max_buffer_size=16 * 1024 * 1024,
    )

    # 直接把图像作为 user message 内容发送
    async def prompts():
        yield {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "下面是一张扫描的法律文书页面图像。请用中文如实描述：这是什么文书？能看到哪些文字（标题/人名/日期/机关）？若看不到图像请明确说‘看不到图像’。"},
                    {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                ],
            },
        }

    final = ""
    async for msg in query(prompt=prompts(), options=opts):
        from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock) and b.text:
                    final = b.text
                    print(f"[assistant] {b.text[:700]}", flush=True)
        elif isinstance(msg, ResultMessage):
            print(f"[result] {msg.subtype} cost=${getattr(msg,'total_cost_usd',0) or 0:.4f}", flush=True)

    print("\n" + "=" * 50)
    sees = not any(k in final for k in ["看不到", "无法", "未收到", "没有图像", "不可用"])
    print("子会话视觉（user-message 图像）:", "可用 ✓" if sees else "不可用 ✗")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
