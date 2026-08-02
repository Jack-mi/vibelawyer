"""命令行入口：vibelawyer-cli / python -m vibelawyer.run

默认：打印 MCP + Skill 使用指引（不调用 Claude Code）。
可选：--legacy 在已安装 vibelawyer[legacy-agent] 且本机有 Claude Code CLI 时跑旧全流程。

注意：包主入口 `vibelawyer` / `vibelawyer-mcp` 启动 FastMCP（见 mcp_server.py），
本模块仅通过 `vibelawyer-cli` 暴露。
"""
from __future__ import annotations

import argparse
import sys

from .config import DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR, load_case
from .playbook import playbook_markdown


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="vibelawyer-cli",
        description="刑事案件阅卷：默认走 MCP + 宿主 Agent Skill；可选 --legacy 用 Claude Code",
    )
    p.add_argument("--case-dir", default=str(DEFAULT_DATA_DIR), help="卷宗所在目录（默认 ./data）")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录（默认 ./output）")
    p.add_argument("--defendant", default=None, help="可选：当事人姓名提示")
    p.add_argument("--charge", default=None, help="可选：涉嫌罪名提示")
    p.add_argument("--vision", action="store_true", help="启用视觉识别（get_page_image）")
    p.add_argument("--no-docling", action="store_true", help="禁用 docling（仅 legacy 有意义）")
    p.add_argument("--model", default=None, help="legacy：主 agent 模型")
    p.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--max-turns", type=int, default=100)
    p.add_argument("--verbose", action="store_true", default=True)
    p.add_argument("--quiet", action="store_true", help="legacy：不打印流式进度")
    p.add_argument(
        "--legacy",
        action="store_true",
        help="使用 Claude Agent SDK + Claude Code CLI 跑全流程（需 pip install 'vibelawyer[legacy-agent]'）",
    )
    p.add_argument(
        "--print-playbook",
        action="store_true",
        help="打印宿主 Agent 阅卷 playbook（Markdown）后退出",
    )
    return p.parse_args(argv)


def _print_mcp_guide(cfg_case_dir: str) -> int:
    print("=" * 60)
    print("vibelawyer —— 推荐用法：任意 Coding Agent + MCP")
    print("=" * 60)
    print("""
不依赖 Claude Code CLI。请在 Cursor / Kimi / OpenCode / Codex 等中配置：

  {
    "mcpServers": {
      "vibelawyer": {
        "command": "uvx",
        "args": ["--from", "vibelawyer", "vibelawyer-mcp"]
      }
    }
  }

然后让 Agent 阅读并执行：
  skills/vibelawyer-review/SKILL.md

典型工具流：
  create_case(case_dir="...") → start_review → 按 playbook 读卷/登记
  → validate_citations → write_outputs → download_output

本机启动 MCP：
  vibelawyer-mcp
  # 或: python -m vibelawyer.mcp_server

查看完整步骤：
  python -m vibelawyer.run --print-playbook

可选旧路径（需 Claude Code）：
  pip install 'vibelawyer[legacy-agent]'
  python -m vibelawyer.run --legacy --case-dir ./data
""")
    print(f"示例案件目录: {cfg_case_dir}")
    print("=" * 60)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.print_playbook:
        print(playbook_markdown())
        return 0

    if not args.legacy:
        return _print_mcp_guide(args.case_dir)

    # ---- legacy: Claude Agent SDK + Claude Code CLI ----
    try:
        from .orchestrator import run_case
    except ImportError as e:
        print(f"无法加载 legacy 编排: {e}", file=sys.stderr)
        print("请: pip install 'vibelawyer[legacy-agent]'", file=sys.stderr)
        return 1

    import asyncio

    cfg = load_case(
        case_dir=args.case_dir,
        output_dir=args.output_dir,
        defendant_hint=args.defendant,
        charge_hint=args.charge,
        vision_available=args.vision,
    )
    print(f"案件目录: {cfg.case_dir}")
    print(f"发现卷宗 {len(cfg.volumes)} 册：")
    for v in cfg.volumes:
        print(f"  - 《{v.name}》 {v.filename} ({v.pages} 页)")
    print(f"输出目录: {cfg.output_dir}")
    print("-" * 60)
    print("⚠ legacy 模式：依赖本机 Claude Code CLI。")

    verbose = args.verbose and not args.quiet
    if args.no_docling:
        import os
        os.environ["VIBELAWYER_NO_DOCLING"] = "1"

    try:
        result = asyncio.run(
            run_case(
                cfg, model=args.model, effort=args.effort,
                max_turns=args.max_turns, verbose=verbose,
            )
        )
    except ImportError as e:
        print(str(e), file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print("阅卷完成。")
    print(f"案件: {result['case_name']} | 当事人: {result['defendant']} | 罪名: {result['charge']}")
    print(f"阅卷笔录(Word): {result['docx']}")
    print(f"阅卷目录(Excel): {result['xlsx']}")
    if result["citation_problems"]:
        print(f"\n⚠ 来源引用校验发现 {len(result['citation_problems'])} 处问题：")
        for p in result["citation_problems"]:
            print(f"  - [{p['record']}] {p['issue']}")
    else:
        print("\n✓ 全部来源引用校验通过，无幻觉页码。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
