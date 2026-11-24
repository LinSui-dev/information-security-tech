from typing import Iterator
from . import bmp
from .contracts import StegoFrame, FRAME_HEADER_SIZE, MAGIC
from .errors import InvalidPayloadError


def _bytes_to_bits(bs: bytes) -> Iterator[int]:
    """字节转比特流：bit0(最低位) 先输出，bit7最后输出"""
    for b in bs:
        for i in range(8):
            yield (b >> i) & 1


def _bits_to_bytes(bits: Iterator[int]) -> bytes:
    buf = bytearray()
    current_byte = 0
    bit_pos = 0
    for bit in bits:
        current_byte |= (bit & 1) << bit_pos
        bit_pos += 1
        if bit_pos == 8:
            buf.append(current_byte)
            current_byte = 0
            bit_pos = 0
    return bytes(buf)


def embed_text(img: bmp.BmpImage, text: str) -> bmp.BmpImage:
    """
    将文本嵌入载体LSB，返回全新BmpImage，原图不修改
    仅依赖 bmp.iter_carrier_offsets 获取载体位置
    """
    try:
        frame_bytes = StegoFrame.pack(text)
    except Exception as e:
        raise InvalidPayloadError(f"frame pack failed: {e}") from e

    offsets = list(bmp.iter_carrier_offsets(img))
    total_bits = len(offsets)
    required_bits = len(frame_bytes) * 8
    if required_bits > total_bits:
        raise InvalidPayloadError("carrier space insufficient")

    new_img = img.copy()
    bit_stream = _bytes_to_bits(frame_bytes)

    for idx, bit in enumerate(bit_stream):
        offset = offsets[idx]
        orig = new_img.get_pixel_byte(offset)
        new_val = (orig & 0xFE) | (bit & 1)
        new_img.set_pixel_byte(offset, new_val)
    return new_img


def extract_text(img: bmp.BmpImage) -> str:
    """
    从载体提取v1帧，校验协议，返回utf8文本
    所有校验失败抛出 InvalidPayloadError
    """
    offsets = list(bmp.iter_carrier_offsets(img))
    total_bits = len(offsets)
    header_bits = FRAME_HEADER_SIZE * 8
    if total_bits < header_bits:
        raise InvalidPayloadError("not enough bits for frame header")

    # 读取【头部13字节】比特流，单独解析头部，不再调用unpack！
    header_bit_iter = (img.get_pixel_byte(offsets[i]) & 1 for i in range(header_bits))
    header_raw = _bits_to_bytes(header_bit_iter)
    payload_len = int.from_bytes(header_raw[0:4], "little")
    crc_stored = int.from_bytes(header_raw[4:8], "little")
    magic = header_raw[8:13]
    if magic != MAGIC:
        raise InvalidPayloadError("header parse fail: invalid magic header, not LSBv1 frame")

    full_frame_bits = (FRAME_HEADER_SIZE + payload_len) * 8
    if total_bits < full_frame_bits:
        raise InvalidPayloadError("carrier too short for full payload")

    # 读取完整帧比特，交给unpack校验
    full_bit_iter = (img.get_pixel_byte(offsets[i]) & 1 for i in range(full_frame_bits))
    full_raw = _bits_to_bytes(full_bit_iter)
    try:
        frame = StegoFrame.unpack(full_raw)
    except ValueError as e:
        raise InvalidPayloadError(f"frame invalid: {e}") from e

    try:
        return frame.payload.decode("utf-8")
    except UnicodeDecodeError as e:
        raise InvalidPayloadError("payload is not valid utf-8") from e
