"""成员二实现；仅依赖共享模型及成员一的像素偏移迭代器。"""
from .models import BmpImage, ExtractionResult


def embed_text(image: BmpImage, text: str) -> BmpImage:
    """写入 v1 帧，返回新图，不修改输入。"""
    raise NotImplementedError("待实现顺序 LSB 嵌入")


def extract_text(image: BmpImage) -> ExtractionResult:
    """依次校验帧头、长度、CRC32、UTF-8；失败抛 InvalidPayloadError。"""
    raise NotImplementedError("待实现顺序 LSB 提取")
