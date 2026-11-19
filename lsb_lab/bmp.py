"""成员一实现。接口规范见 docs/architecture.md。"""
from pathlib import Path
from collections.abc import Iterator
from .models import BmpImage, PreviewData


def load_bmp(path: str | Path) -> BmpImage:
    raise NotImplementedError("待实现 BMP 读取和完整校验")


def save_bmp(image: BmpImage, path: str | Path) -> None:
    raise NotImplementedError("待实现 BMP 保存")


def iter_carrier_offsets(image: BmpImage) -> Iterator[int]:
    """按文件行顺序遍历有效像素字节偏移，排除填充、头部和调色板。"""
    raise NotImplementedError("待实现载体位置遍历")


def to_preview(image: BmpImage) -> PreviewData:
    """自行将灰度/BGR 转为从上到下的 RGB，输出 P6 PPM。"""
    raise NotImplementedError("待实现预览转换")
