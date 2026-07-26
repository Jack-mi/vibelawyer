"""命令行入口：vibelawyer / python -m vibelawyer.run

示例:
    python -m vibelawyer.run --case-dir ./data --output-dir ./output
    python -m vibelawyer.run --case-dir ./data --defendant 张小双 --verbose
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from .config import DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR, load_case
from .orchestrator import run_case


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="vibelawyer", description="通用化刑事案件阅卷 Agent")
    p.add_argument("--case-dir", default=str(DEFAULT_DATA_DIR), help="卷宗所在目录（默认 ./data）")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录（默认 ./output）")
    p.add_argument("--defendant", default=None, help="可选：当事人姓名提示")
    p.add_argument("--charge", default=None, help="可选：涉嫌罪名提示")
    p.add_argument("--vision", action="store_true", help="启用视觉识别（get_page_image）；缺省仅用本地 OCR")
    p.add_argument("--no-docling", action="store_true", help="禁用 docling，仅用 pypdfium2+tesseract OCR")
    p.add_argument("--model", default=None, help="主 agent 模型（如 opus/sonnet；缺省用 CLI 默认）")
    p.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--max-turns", type=int, default=100)
    p.add_argument("--verbose", action="store_true", default=True)
    p.add_argument("--quiet", action="store_true", help="不打印流式进度")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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

    verbose = args.verbose and not args.quiet
    if args.no_docling:
        # 运行期禁用 docling：覆盖 init_tools 默认。通过环境标记传递。
        import os
        os.environ["VIBELAWYER_NO_DOCLING"] = "1"
    result = asyncio.run(
        run_case(cfg, model=args.model, effort=args.effort, max_turns=args.max_turns, verbose=verbose)
    )

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
