"""卷宗 PDF 访问层（基于 pypdfium2）.

pypdfium2 是 Google PDFium 的 Python 绑定，纯 wheel、无重依赖，可同时：
  - 提取内嵌文本层（数字生成的 PDF 多有文本层）
  - 渲染任意页为 PNG 图像（供视觉识别）

提取策略（逐页）:
  1. 优先用文本层。注意：部分扫描/特殊字体的 PDF 文本层 CJK 编码损坏
     （表现为乱码或 ?????），此时 char_count 可能虚高但内容不可用 ——
     检测到全 ?/乱码比例过高时，标记 needs_ocr 走视觉。
  2. 文本层不足或乱码时，由 agent 调用 get_page_image 渲染图像用视觉识别
     （Claude 对中文 OCR 准确率远高于 tesseract，且无需 chi_sim 语言包）。
  3. 若本机 tesseract 且有 chi_sim，亦可本地 OCR 作为可选预提取。

所有读取均带页码，确保引用可回溯。跨卷检索支持关键词与正则。
"""
from __future__ import annotations

import base64
import io
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import CaseConfig, TEXT_LAYER_MIN_CHARS, VolumeSpec

try:
    import pypdfium2 as pdfium  # type: ignore
except ImportError as e:  # pragma: no cover
    raise ImportError("需要安装 pypdfium2: pip install pypdfium2") from e

try:
    from PIL import Image  # noqa: F401
    import numpy as np  # noqa: F401
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


def _tesseract_has_chinese() -> bool:
    if not shutil.which("tesseract"):
        return False
    try:
        out = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10
        ).stdout
        return "chi_sim" in out
    except Exception:
        return False


# 注意：不做模块级缓存。chi_sim 是否可用取决于运行时 TESSDATA_PREFIX，
# 该变量由 config.ensure_ocr_env() 在 load_case 时设置，晚于本模块导入。
# 因此每次按需探测，避免缓存到 False。


def _is_garbled(text: str) -> bool:
    """检测 OCR/文本层是否 CJK 编码损坏（常见为大量 ? 占位、汉字丢失）。

    判据：中文法律页面应以汉字为主。若 ? 占位符较多、且汉字占比偏低，视为乱码，
    应回退到其他解析路径。具体：? 数量 > 20 且 汉字/(汉字+?) < 0.5 → 乱码。
    """
    if not text:
        return False
    cjk = len(re.findall(r"[一-鿿]", text))
    qmarks = text.count("?")
    if qmarks > 20 and cjk / max(cjk + qmarks, 1) < 0.5:
        return True
    # 无任何汉字且 ? 多
    if cjk == 0 and qmarks > 20:
        return True
    return False


@dataclass
class PageText:
    volume: str
    page: int  # 1-based
    text: str
    char_count: int
    needs_ocr: bool  # 文本层是否不足/乱码，需视觉识别


class Volume:
    """单册卷宗."""

    def __init__(self, spec: VolumeSpec) -> None:
        self.spec = spec
        self._doc: "pdfium.PdfDocument | None" = None
        self._lock = threading.Lock()
        self._text_cache: dict[int, PageText] = {}
        self._docling_cache_dir: Path | None = None  # 由 VolumeStore 注入

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def path(self) -> Path:
        return self.spec.path

    def _open(self):
        if self._doc is None:
            self._doc = pdfium.PdfDocument(str(self.path))
        return self._doc

    def page_count(self) -> int:
        return len(self._open())

    def get_page_text(self, page: int) -> PageText:
        if page in self._text_cache:
            return self._text_cache[page]
        with self._lock:
            if page in self._text_cache:
                return self._text_cache[page]
            doc = self._open()
            idx = page - 1
            n = len(doc)
            if idx < 0 or idx >= n:
                raise IndexError(f"页码超出范围: {self.name} P{page}（共 {n} 页）")

            text = ""
            needs_ocr = False
            # 1) 优先 docling 缓存（RapidOCR，质量最高）；但需校验非乱码
            if self._docling_cache_dir is not None:
                from . import docling_cache
                dt = docling_cache.get_page_text(self.name, page, self._docling_cache_dir)
                if dt and len(dt.strip()) >= TEXT_LAYER_MIN_CHARS and not _is_garbled(dt):
                    text = dt.strip()
            # 2) 回退：pypdfium2 文本层
            if len(text) < TEXT_LAYER_MIN_CHARS:
                page_obj = doc[idx]
                try:
                    tp = page_obj.get_textpage()
                    raw = tp.get_text_range() or ""
                    tp.close()
                finally:
                    page_obj.close()
                if raw and not _is_garbled(raw) and len(raw.strip()) >= TEXT_LAYER_MIN_CHARS:
                    text = raw.strip()
                else:
                    needs_ocr = True
            # 3) 最后回退：tesseract chi_sim（docling 不可用时）
            if needs_ocr and _tesseract_has_chinese():
                ocr = _tesseract_ocr(self, idx)
                if len(ocr) >= TEXT_LAYER_MIN_CHARS and not _is_garbled(ocr):
                    text = ocr
                    needs_ocr = False
            pt = PageText(volume=self.name, page=page, text=text,
                          char_count=len(text), needs_ocr=needs_ocr)
            self._text_cache[page] = pt
            return pt

    def get_page_image_b64(self, page: int, scale: float = 1.5, max_dim: int = 1500,
                           jpeg_quality: int = 72) -> tuple[str, str]:
        """渲染指定页为 (base64 JPEG, mimeType).

        用 JPEG 而非 PNG 以大幅压缩体积（扫描页文本在 q72 下仍清晰可辨），
        并限制最长边以控制 token；确保 base64 不超过 SDK 的 JSON 消息缓冲上限。
        返回的 mimeType 与实际编码一致，供工具回传给模型。
        """
        doc = self._open()
        idx = page - 1
        page_obj = doc[idx]
        try:
            bitmap = page_obj.render(scale=scale)
            pil = bitmap.to_pil()
        finally:
            page_obj.close()
        if pil.mode != "RGB":
            pil = pil.convert("RGB")
        # 限制最长边
        longest = max(pil.width, pil.height)
        if longest > max_dim:
            ratio = max_dim / longest
            pil = pil.resize((max(1, int(pil.width * ratio)), max(1, int(pil.height * ratio))))
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"

    def search(self, query: str) -> list[dict]:
        """在本卷内搜索关键词，返回命中页与片段。"""
        doc = self._open()
        n = len(doc)
        hits: list[dict] = []
        for idx in range(n):
            pt = self.get_page_text(idx + 1)
            if not pt.text or pt.needs_ocr:
                continue  # 乱码/扫描页文本不可靠，不参与文本检索
            for m in re.finditer(re.escape(query), pt.text):
                start = max(0, m.start() - 40)
                end = min(len(pt.text), m.end() + 40)
                snippet = pt.text[start:end].replace("\n", " ")
                hits.append({"volume": self.name, "page": idx + 1, "snippet": snippet})
                break  # 每页只取首个命中片段
        return hits


def _tesseract_ocr(vol: "Volume", idx: int) -> str:
    doc = vol._open()  # noqa: SLF001
    page_obj = doc[idx]
    try:
        bitmap = page_obj.render(scale=300 / 72)
        pil = bitmap.to_pil()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        img_bytes = buf.getvalue()
    finally:
        page_obj.close()
    try:
        proc = subprocess.run(
            ["tesseract", "-", "-", "-l", "chi_sim", "--psm", "6"],
            input=img_bytes, capture_output=True, timeout=60,
        )
        return proc.stdout.decode("utf-8", "ignore").strip()
    except Exception:
        return ""


class VolumeStore:
    """全部卷宗的统一访问入口."""

    def __init__(self, cfg: CaseConfig, docling_cache_dir: Path | None = None) -> None:
        self.cfg = cfg
        self._docling_cache_dir = docling_cache_dir
        self._volumes: dict[str, Volume] = {}
        for v in cfg.volumes:
            vol = Volume(v)
            vol._docling_cache_dir = docling_cache_dir  # noqa: SLF001
            self._volumes[v.name] = vol

    def names(self) -> list[str]:
        return list(self._volumes.keys())

    def get(self, name: str) -> Volume:
        if name in self._volumes:
            return self._volumes[name]
        for n, v in self._volumes.items():
            if name in n or v.path.name == name or v.path.stem == name:
                return v
        raise KeyError(f"未找到卷宗: {name}；现有卷宗: {list(self._volumes)}")

    def page_count(self, name: str) -> int:
        return self.get(name).page_count()

    def read_pages(self, name: str, start: int, end: int) -> list[PageText]:
        vol = self.get(name)
        start = max(1, start)
        end = min(end, vol.page_count())
        return [vol.get_page_text(p) for p in range(start, end + 1)]

    def search_all(self, query: str) -> list[dict]:
        hits: list[dict] = []
        for name, vol in self._volumes.items():
            hits.extend(vol.search(query))
        return hits

    def volume_inventory(self) -> list[dict]:
        out = []
        for name, vol in self._volumes.items():
            out.append({"name": name, "file": vol.path.name, "pages": vol.page_count()})
        return out
