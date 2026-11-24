"""顺序 LSB v1：使用共享 BMP 模型和固定帧协议。"""
from collections.abc import Iterator
from dataclasses import replace
from itertools import islice
import zlib
from . import bmp
from .contracts import HEADER_BYTES, capacity_for, encode_text, pack_header, unpack_header
from .errors import InvalidPayloadError
from .models import BmpImage, ExtractionResult


def _bytes_to_bits(data: bytes) -> Iterator[int]:
    for value in data:
        for shift in range(7, -1, -1):
            yield (value >> shift) & 1


def _bits_to_bytes(bits: Iterator[int]) -> bytes:
    result = bytearray()
    value = count = 0
    for bit in bits:
        value = (value << 1) | (bit & 1)
        count += 1
        if count == 8:
            result.append(value)
            value = count = 0
    if count:
        raise InvalidPayloadError("载体数据不足一个完整字节")
    return bytes(result)


def embed_text(image: BmpImage, text: str) -> BmpImage:
    payload = encode_text(text, capacity_for(image))
    data = bytearray(image.raw_bytes)
    for offset, bit in zip(bmp.iter_carrier_offsets(image),
                           _bytes_to_bits(pack_header(payload) + payload)):
        data[offset] = (data[offset] & 0xFE) | bit
    return replace(image, raw_bytes=bytes(data))


def extract_text(image: BmpImage) -> ExtractionResult:
    offsets = iter(bmp.iter_carrier_offsets(image))
    def read_bytes(count: int) -> bytes:
        raw = _bits_to_bytes(image.raw_bytes[o] & 1 for o in islice(offsets, count * 8))
        if len(raw) != count:
            raise InvalidPayloadError("载体数据截断")
        return raw
    length, checksum = unpack_header(read_bytes(HEADER_BYTES), capacity_for(image))
    payload = read_bytes(length)
    if zlib.crc32(payload) != checksum:
        raise InvalidPayloadError("正文 CRC32 校验失败")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidPayloadError("正文不是有效的 UTF-8") from exc
    return ExtractionResult(text, payload, checksum)
