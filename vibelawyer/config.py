"""路径与案件配置.

案件 = 一个存放卷宗文件的目录。系统自动发现目录下的 PDF 作为卷宗，
不假定固定案名或当事人 —— 当事人/罪名/金额均由 agent 阅读卷宗后回填，
从而对任意刑事案件通用。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
# 本地 tessdata 目录（含 chi_sim 等语言包）；存在则自动设为 TESSDATA_PREFIX，
# 使 tesseract 对扫描件做中文 OCR。无需视觉模型即可提取扫描卷宗文本。
LOCAL_TESSDATA_DIR = PROJECT_ROOT / "tessdata"

# 可被当作卷宗的文件后缀
VOLUME_SUFFIXES = (".pdf",)

# 页面文本提取的字符阈值：低于该值视为“文本层缺失/扫描件”，触发 OCR 或视觉识别
TEXT_LAYER_MIN_CHARS = 20


def ensure_ocr_env() -> bool:
    """确保中文 OCR 可用：若本地 tessdata 目录含 chi_sim，设置 TESSDATA_PREFIX。

    扫描件卷宗无文本层时，pypdfium2 提取不到文字；本函数让 tesseract 能找到
    chi_sim 语言包做本地 OCR，从而不依赖任何视觉模型即可提取文本。
    返回是否检测到 chi_sim 可用。
    """
    import os

    td = LOCAL_TESSDATA_DIR
    if td.is_dir() and (td / "chi_sim.traineddata").exists():
        os.environ["TESSDATA_PREFIX"] = str(td)
        return True
    # 已有全局 chi_sim 的情况
    if os.environ.get("TESSDATA_PREFIX"):
        return True
    return False


@dataclass
class VolumeSpec:
    """一册卷宗的描述（发现阶段仅知路径与页数，内容惰性提取）."""

    name: str  # 卷宗名称，如“刑事侦查案卷”
    path: Path
    pages: int = 0  # 页数，发现时填充

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass
class CaseConfig:
    """一个案件的运行配置."""

    case_dir: Path
    output_dir: Path
    defendant_hint: str | None = None  # 可选：当事人姓名提示，缺省时由 agent 自行识别
    charge_hint: str | None = None  # 可选：涉嫌罪名提示
    vision_available: bool = False  # 视觉识别是否可用；False 时仅用本地 OCR
    volumes: list[VolumeSpec] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.case_dir = Path(self.case_dir)
        self.output_dir = Path(self.output_dir)

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir


def discover_volumes(case_dir: Path) -> list[VolumeSpec]:
    """发现目录下的卷宗文件（按文件名排序，保持稳定的卷序）."""
    case_dir = Path(case_dir)
    volumes: list[VolumeSpec] = []
    if not case_dir.is_dir():
        raise FileNotFoundError(f"案件目录不存在: {case_dir}")
    for p in sorted(case_dir.iterdir(), key=lambda x: x.name):
        if p.is_file() and p.suffix.lower() in VOLUME_SUFFIXES:
            # 过滤 macOS 的 .textClipping 等噪音
            if ".textClipping" in p.name or p.name.startswith("._"):
                continue
            name = _pretty_volume_name(p.stem)
            volumes.append(VolumeSpec(name=name, path=p))
    return volumes


def _pretty_volume_name(stem: str) -> str:
    """把文件名清理成更可读的卷宗名（去掉 (2) 之类后缀）."""
    name = re.sub(r"\(\d+\)$", "", stem)  # 张小双(2) -> 张小双
    name = re.sub(r"[\s_]+", "", name).strip()
    return name or stem


def load_case(
    case_dir: Path | str = DEFAULT_DATA_DIR,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    defendant_hint: str | None = None,
    charge_hint: str | None = None,
    vision_available: bool = False,
) -> CaseConfig:
    case_dir = Path(case_dir).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    cfg = CaseConfig(
        case_dir=case_dir,
        output_dir=output_dir,
        defendant_hint=defendant_hint,
        charge_hint=charge_hint,
        vision_available=vision_available,
    )
    cfg.volumes = discover_volumes(case_dir)
    if not cfg.volumes:
        raise FileNotFoundError(f"案件目录下未发现任何卷宗 PDF: {case_dir}")
    # 确保中文 OCR 可用（扫描件必备）
    ensure_ocr_env()
    # 统计页数（惰性打开，仅读页数）
    from .pdf_volume import VolumeStore  # 延迟导入，避免循环依赖

    store = VolumeStore(cfg)
    for v in cfg.volumes:
        v.pages = store.page_count(v.name)
    return cfg
