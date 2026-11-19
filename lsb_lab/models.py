"""跨模块数据结构；像素数据采用 BMP 文件中的原始顺序。"""
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PixelFormat(Enum):
    GRAY8 = 8
    BGR24 = 24


@dataclass(frozen=True)
class BmpImage:
    width: int
    height: int  # 正数，方向单独记录
    pixel_format: PixelFormat
    top_down: bool
    pixel_offset: int
    row_stride: int
    raw_bytes: bytes  # 完整文件；不可变，嵌入时产生新对象

    @property
    def channel_count(self) -> int:
        return 1 if self.pixel_format is PixelFormat.GRAY8 else 3

    @property
    def carrier_count(self) -> int:
        return self.width * self.height * self.channel_count


@dataclass(frozen=True)
class Capacity:
    carrier_bits: int
    header_bytes: int
    max_payload_bytes: int
    can_store_header: bool


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    payload: bytes
    checksum: int


@dataclass
class SessionState:
    source: BmpImage | None = None
    stego: BmpImage | None = None
    source_path: Path | None = None
    input_text: str = ""
    extracted_text: str = ""
    extracted_image: BmpImage | None = None
    extracted_path: Path | None = None
    dirty: bool = False


@dataclass(frozen=True)
class PreviewData:
    """交给 Tkinter PhotoImage 的 P6 PPM 字节，不是文件路径。"""
    ppm_bytes: bytes
