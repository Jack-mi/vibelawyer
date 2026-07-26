"""docling 转换脚本（在 full docling venv 中执行，非 conda base）.

由 vibelawyer.docling_cache 通过子进程调用：读入一组 PDF 路径，用 docling
（RapidOCR + 布局模型）转换为按页文本，输出 JSON 到 stdout：
  {"volumes": [{"name":..., "path":..., "pages": {"1": "文本", "2": "文本", ...}}], "error": null}

模型只加载一次，批量转换全部卷宗，避免重复加载开销。
"""
from __future__ import annotations

import json
import sys
import time


def main(pdf_paths: list[str]) -> None:
    from docling.document_converter import DocumentConverter

    conv = DocumentConverter()
    volumes = []
    t0 = time.time()
    for path in pdf_paths:
        try:
            res = conv.convert(path)
            doc = res.document
            pages: dict[str, str] = {}
            for item, _level in doc.iterate_items():
                txt = getattr(item, "text", None) or ""
                if not txt:
                    continue
                provs = getattr(item, "prov", None) or []
                for p in provs:
                    pno = getattr(p, "page_no", 1)
                    pages.setdefault(str(pno), "")
                    pages[str(pno)] += txt
            import os
            name = os.path.splitext(os.path.basename(path))[0]
            # 清理 (2) 之类后缀，与 config._pretty_volume_name 一致
            import re
            name = re.sub(r"\(\d+\)$", "", name)
            name = re.sub(r"[\s_]+", "", name).strip() or name
            volumes.append({"name": name, "path": path, "pages": pages, "page_count": len(pages)})
            print(f"[docling] {name}: {len(pages)} pages", file=sys.stderr, flush=True)
        except Exception as e:
            import os
            volumes.append({"name": os.path.basename(path), "path": path, "pages": {}, "error": str(e)})
            print(f"[docling] ERROR {path}: {e}", file=sys.stderr, flush=True)
    out = {"volumes": volumes, "elapsed_sec": round(time.time() - t0, 1)}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        # 从 stdin 读 JSON 路径列表
        paths = json.loads(sys.stdin.read())
    main(paths)
