"""基础模式 v1 的线格式与可复用计算。"""
import struct
import zlib
from .errors import CapacityError, InvalidPayloadError
from .models import BmpImage, Capacity

MAGIC = b"LSB1"
VERSION = 1
HEADER = struct.Struct("<4sBII")
HEADER_BYTES = HEADER.size  # 13：magic + version + length + crc32


def capacity_for(image: BmpImage) -> Capacity:
    whole_bytes = image.carrier_count // 8
    return Capacity(image.carrier_count, HEADER_BYTES,
                    max(0, whole_bytes - HEADER_BYTES), whole_bytes >= HEADER_BYTES)


def encode_text(text: str, capacity: Capacity) -> bytes:
    payload = text.encode("utf-8")
    if not capacity.can_store_header or len(payload) > capacity.max_payload_bytes:
        raise CapacityError("UTF-8 文本或帧头超过图片容量")
    return payload


def pack_header(payload: bytes) -> bytes:
    return HEADER.pack(MAGIC, VERSION, len(payload), zlib.crc32(payload))


def unpack_header(data: bytes, capacity: Capacity) -> tuple[int, int]:
    if len(data) != HEADER_BYTES or not capacity.can_store_header:
        raise InvalidPayloadError("载体无法容纳完整帧头")
    magic, version, length, checksum = HEADER.unpack(data)
    if magic != MAGIC or version != VERSION:
        raise InvalidPayloadError("未识别的 LSB 标记或版本")
    if length > capacity.max_payload_bytes:
        raise InvalidPayloadError("帧中声明的文本长度超过载体容量")
    return length, checksum
