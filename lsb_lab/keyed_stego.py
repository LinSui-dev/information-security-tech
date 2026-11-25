"""带密钥的随机间隔 LSB（KLS1 协议）。完整协议、设计依据与文献见 docs/keyed-stego.md。

与顺序 LSB v1 相互独立：独立 magic、独立帧格式，不复用或修改 v1 标记。
只依赖共享模型/异常和 bmp.iter_carrier_offsets；不读写文件，不弹窗。

安全边界：随机位置不是加密。正文按 UTF-8 明文位写入，本模块不承诺抗 JPEG、
噪声、剪裁，也不承诺能抵抗统计分析。
"""
from collections.abc import Iterable, Iterator
from dataclasses import replace
import hashlib
import hmac
from itertools import chain, islice
import secrets
import struct
import zlib

from . import bmp
from .errors import CapacityError, InvalidPayloadError
from .models import BmpImage, Capacity, ExtractionResult

MAGIC = b"KLS1"
VERSION = 1
SALT_BYTES = 16
TAG_BYTES = 16
META = struct.Struct("<4sB16sII")  # magic + version + salt + length + crc32
META_BYTES = META.size             # 29，也是 MAC 输入的前缀
BOOTSTRAP_BYTES = META_BYTES + TAG_BYTES  # 45
BOOTSTRAP_CHANNELS = BOOTSTRAP_BYTES * 8  # 360，占据固定前缀通道
GROUP_SIZE = 8                     # 每组通道数，每组承载 1 个正文位
_DOMAIN = MAGIC + bytes([VERSION])  # 子密钥派生的域分隔前缀
_SALT_SLICE = slice(5, 5 + SALT_BYTES)  # 元数据中盐的位置


def _check_key(key: object) -> None:
    if not isinstance(key, str) or not key:
        raise ValueError("key 必须是非空字符串")


def _embed_salt(salt: bytes | bytearray | memoryview | None) -> bytes:
    if salt is None:
        return secrets.token_bytes(SALT_BYTES)
    if not isinstance(salt, (bytes, bytearray, memoryview)):
        raise ValueError("salt 必须是 16 字节的 bytes")
    salt = bytes(salt)
    if len(salt) != SALT_BYTES:
        raise ValueError(f"salt 必须恰为 {SALT_BYTES} 字节，实际 {len(salt)} 字节")
    return salt


def _mac256(key: bytes, message: bytes) -> bytes:
    return hmac.digest(key, message, hashlib.sha256)


def _derive_key(key: str, label: bytes, salt: bytes) -> bytes:
    """子密钥 = HMAC-SHA256(key 的 UTF-8 字节, 域前缀 + 用途标签 + 盐)。

    只依赖 hashlib/hmac，不使用 Python hash()，跨进程、跨平台稳定。
    """
    return _mac256(key.encode("utf-8"), _DOMAIN + label + salt)


def _keystream(stream_key: bytes) -> Iterator[int]:
    """HMAC-SHA256 计数器模式：第 j 块 = HMAC(stream_key, j 的 8 字节大端)。"""
    counter = 0
    while True:
        yield from _mac256(stream_key, counter.to_bytes(8, "big"))
        counter += 1


def _positions(key: str, salt: bytes, bit_count: int) -> tuple[int, ...]:
    """第 i 个正文位的逻辑通道索引：360 + i×8 + (keystream[i] mod 8)。"""
    stream = _keystream(_derive_key(key, b"pos", salt))
    return tuple(BOOTSTRAP_CHANNELS + i * GROUP_SIZE + byte % GROUP_SIZE
                 for i, byte in enumerate(islice(stream, bit_count)))


def _compute_tag(key: str, meta: bytes, payload: bytes) -> bytes:
    """HMAC-SHA256 截断为 16 字节，输入为全部元数据（含盐、长度、CRC）加正文。"""
    mac_key = _derive_key(key, b"mac", meta[_SALT_SLICE])
    return _mac256(mac_key, meta + payload)[:TAG_BYTES]


def _bytes_to_bits(data: bytes) -> Iterator[int]:
    for value in data:
        for shift in range(7, -1, -1):  # 先 bit7 后 bit0
            yield (value >> shift) & 1


def _bits_to_bytes(bits: Iterable[int]) -> bytes:
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


def _select_offsets(image: BmpImage, positions: Iterable[int]) -> Iterator[int]:
    """按升序且唯一的逻辑通道索引，经官方迭代器取对应文件偏移。"""
    offsets = bmp.iter_carrier_offsets(image)
    index = 0
    for target in positions:
        while index < target:
            next(offsets)
            index += 1
        yield next(offsets)
        index += 1


def _read_bytes(image: BmpImage, positions: Iterable[int]) -> bytes:
    bits = (image.raw_bytes[offset] & 1 for offset in _select_offsets(image, positions))
    return _bits_to_bytes(bits)


def _read_meta(image: BmpImage) -> tuple[bytes, bytes]:
    """读取并校验 bootstrap 的结构：标记、版本、长度上界。不验证正文。"""
    capacity = capacity_for_keyed(image)
    if not capacity.can_store_header:
        raise InvalidPayloadError("载体无法容纳完整的带密钥帧头")
    frame = _read_bytes(image, range(BOOTSTRAP_CHANNELS))
    meta, tag = frame[:META_BYTES], frame[META_BYTES:]
    magic, version, _, length, _ = META.unpack(meta)
    if magic != MAGIC:
        raise InvalidPayloadError("未识别的带密钥 LSB 标记")
    if version != VERSION:
        raise InvalidPayloadError(f"不支持的带密钥协议版本 {version}")
    if length > capacity.max_payload_bytes:
        raise InvalidPayloadError("帧中声明的文本长度超过载体容量")
    return meta, tag


def capacity_for_keyed(image: BmpImage) -> Capacity:
    """容量只由图像和协议参数决定，对任何合法 key/salt 都成立。

    header_bytes 是完整帧的固定元数据字节数（45，含盐、长度、CRC、MAC）。
    正文每 8 个剩余通道承载 1 位，最后不足 8 个通道的分组不使用。
    """
    spare = max(0, image.carrier_count - BOOTSTRAP_CHANNELS)
    max_payload = spare // GROUP_SIZE // 8
    return Capacity(image.carrier_count, BOOTSTRAP_BYTES, max_payload,
                    image.carrier_count >= BOOTSTRAP_CHANNELS)


def embed_text(image: BmpImage, text: str, *, key: str,
               salt: bytes | None = None) -> BmpImage:
    """嵌入并返回新图；只改 bootstrap 与正文占用位置的 LSB。"""
    _check_key(key)
    if not isinstance(text, str):
        raise ValueError("text 必须是 str")
    salt = _embed_salt(salt)
    payload = text.encode("utf-8")  # 原样编码，不 strip、不归一化
    capacity = capacity_for_keyed(image)
    if not capacity.can_store_header or len(payload) > capacity.max_payload_bytes:
        raise CapacityError("UTF-8 文本或帧头超过图片容量")
    meta = META.pack(MAGIC, VERSION, salt, len(payload), zlib.crc32(payload))
    frame = meta + _compute_tag(key, meta, payload) + payload
    positions = chain(range(BOOTSTRAP_CHANNELS), _positions(key, salt, len(payload) * 8))
    data = bytearray(image.raw_bytes)
    for offset, bit in zip(_select_offsets(image, positions), _bytes_to_bits(frame), strict=True):
        data[offset] = (data[offset] & 0xFE) | bit
    return replace(image, raw_bytes=bytes(data))


def extract_text(image: BmpImage, *, key: str) -> ExtractionResult:
    """读 bootstrap、按同一规则定位正文，依次校验 CRC、MAC 和 UTF-8。

    密钥正确且正文完好时才成功；错误密钥以极高概率在 MAC 步骤失败。
    """
    _check_key(key)
    meta, tag = _read_meta(image)
    _, _, salt, length, crc = META.unpack(meta)
    positions = _positions(key, salt, length * 8)
    # 偏移迭代器从头开始，故连同 bootstrap 一起读出，再切掉固定前缀
    payload = _read_bytes(image, chain(range(BOOTSTRAP_CHANNELS), positions))[BOOTSTRAP_BYTES:]
    # 先验证 MAC：错误密钥会定位到错误的正文位，必须在此步失败并如实报告。
    # CRC32 位于 MAC 之后，只是冗余核对，不提供安全保证。
    if not hmac.compare_digest(_compute_tag(key, meta, payload), tag):
        raise InvalidPayloadError("密钥错误，或帧内容已损坏/被篡改")
    if zlib.crc32(payload) != crc:
        raise InvalidPayloadError("正文 CRC32 校验失败")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidPayloadError("正文不是有效的 UTF-8") from exc
    return ExtractionResult(text, payload, crc)


def payload_positions(image: BmpImage, *, key: str) -> tuple[int, ...]:
    """按嵌入顺序返回正文承载位置的逻辑通道索引，不含 bootstrap。

    只解析并校验 bootstrap 的结构和声明长度，不读取正文、不验证 MAC，
    因此不能单独证明密钥正确；完整提取才负责鉴别。
    """
    _check_key(key)
    meta, _ = _read_meta(image)
    _, _, salt, length, _ = META.unpack(meta)
    return _positions(key, salt, length * 8)
