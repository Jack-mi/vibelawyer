"""docling 缓存层：调用 full docling venv 把卷宗 PDF 转为按页文本，缓存到磁盘。

docling（RapidOCR + 布局模型）对中文扫描件的识别质量明显优于 tesseract，
故作为首选解析路径；不可用时回退到 pypdfium2 文本层 + tesseract。

设计：
  - build_docling_cache(volumes, cache_dir)：子进程调用 docling venv 一次性转换全部卷宗，
    写入 {cache_dir}/<volume>.json = {"pages": {"1":"...",...}, "page_count": N}。
  - 模型只加载一次（在子进程内），批量转换，避免重复加载 ~30s 开销。
  - get_page_text(volume_name, page, cache_dir)：从缓存读指定页文本。
  - 若 docling venv 不存在或转换失败，返回 None，调用方回退到 tesseract。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .config import LOCAL_TESSDATA_DIR, PROJECT_ROOT

# full docling venv 的 Python（含 torch/opencv/rapidocr）
DOCLING_VENV_PYTHON = Path.home() / ".local/share/docling-venv/bin/python"
DOCLING_RUNNER = Path(__file__).resolve().parent / "docling_runner.py"
DOCLING_CACHE_DIRNAME = "docling_cache"

# docling 单卷转换超时（秒）：含模型加载 + OCR
_PER_VOLUME_TIMEOUT = 600


def docling_available() -> bool:
    return DOCLING_VENV_PYTHON.exists() and DOCLING_RUNNER.exists()


def cache_dir_for(output_dir: Path | str) -> Path:
    """docling 按页文本缓存目录。

    放在项目级 .cache/docling_cache（与 output_dir 同级的项目根下），而非 output_dir 内，
    确保 output 目录只有交付物（Word/Excel），不混入缓存 JSON。
    若 output_dir 不可写或非预期路径，回退到系统临时目录。
    """
    out = Path(output_dir)
    # 项目根 = output_dir 的父目录（output 默认在项目根下）
    proj_root = out.parent if out.name == "output" else out
    d = proj_root / ".cache" / DOCLING_CACHE_DIRNAME
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        import tempfile
        d = Path(tempfile.gettempdir()) / "vibelawyer_docling_cache"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _cache_file(cache_dir: Path, volume_name: str) -> Path:
    safe = volume_name.replace("/", "_").replace(" ", "")
    return cache_dir / f"{safe}.json"


def build_docling_cache(volumes, cache_dir: Path, verbose: bool = False) -> dict:
    """子进程调用 docling venv 转换全部卷宗，写缓存。返回 {volume_name: page_count}."""
    cache_dir = Path(cache_dir)
    if not docling_available():
        if verbose:
            print("[docling] 不可用（未找到 ~/.local/share/docling-venv），跳过，回退 tesseract")
        return {}
    paths = [str(v.path) for v in volumes]
    env = dict(os.environ)
    # 不强制 TESSDATA_PREFIX（docling 自带 OCR，不依赖 tesseract）
    try:
        proc = subprocess.run(
            [str(DOCLING_VENV_PYTHON), str(DOCLING_RUNNER)] + paths,
            capture_output=True, text=True, timeout=_PER_VOLUME_TIMEOUT * max(1, len(paths)),
            env=env,
        )
    except subprocess.TimeoutExpired:
        if verbose:
            print("[docling] 转换超时")
        return {}
    if proc.returncode != 0:
        if verbose:
            print(f"[docling] 子进程失败 rc={proc.returncode}: {proc.stderr[:300]}")
        return {}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        if verbose:
            print(f"[docling] 解析输出失败: {e}; stdout[:200]={proc.stdout[:200]}")
        return {}
    result = {}
    for vol in data.get("volumes", []):
        name = vol.get("name", "")
        if vol.get("error") or not vol.get("pages"):
            if verbose:
                print(f"[docling] {name} 转换失败或无页: {vol.get('error', '空')}")
            continue
        cf = _cache_file(cache_dir, name)
        cf.write_text(json.dumps(
            {"pages": vol["pages"], "page_count": vol.get("page_count", len(vol["pages"]))},
            ensure_ascii=False,
        ), encoding="utf-8")
        result[name] = vol.get("page_count", len(vol["pages"]))
        if verbose:
            print(f"[docling] 已缓存 {name}: {result[name]} 页")
    if verbose:
        print(f"[docling] 批量转换完成，耗时 {data.get('elapsed_sec')}s，成功 {len(result)}/{len(paths)} 卷")
    return result


def get_page_text(volume_name: str, page: int, cache_dir: Path) -> str | None:
    """从 docling 缓存读指定页文本；无缓存返回 None。"""
    cf = _cache_file(Path(cache_dir), volume_name)
    if not cf.exists():
        return None
    try:
        data = json.loads(cf.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data.get("pages", {}).get(str(page))


def get_cached_page_count(volume_name: str, cache_dir: Path) -> int | None:
    cf = _cache_file(Path(cache_dir), volume_name)
    if not cf.exists():
        return None
    try:
        return json.loads(cf.read_text(encoding="utf-8")).get("page_count")
    except Exception:
        return None
