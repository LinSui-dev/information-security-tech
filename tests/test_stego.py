import pytest
import zlib
from unittest.mock import patch
from lsb_lab import stego
from lsb_lab.contracts import StegoFrame
from lsb_lab.errors import InvalidPayloadError

class MockBmpImage:
    def __init__(self, carrier_pixel_count: int):
        self._data = bytearray([0xAA] * carrier_pixel_count)
    def copy(self):
        return MockBmpImage(len(self._data))
    def get_pixel_byte(self, offset: int) -> int:
        return self._data[offset]
    def set_pixel_byte(self, offset: int, value: int) -> None:
        self._data[offset] = value & 0xFF

def mock_iter_offsets(img: MockBmpImage):
    return range(len(img._data))

@pytest.fixture(autouse=True)
def patch_carrier_iter():
    with patch("lsb_lab.bmp.iter_carrier_offsets", side_effect=mock_iter_offsets):
        yield

def test_embed_extract_basic():
    img = MockBmpImage(500)
    msg = "hello world"
    s = stego.embed_text(img, msg)
    assert stego.extract_text(s) == msg

def test_embed_extract_empty_text():
    # 空消息帧=13字节=104bit，像素>=104
    img = MockBmpImage(110)
    s = stego.embed_text(img, "")
    assert stego.extract_text(s) == ""

def test_embed_extract_cn_emoji_newline_space():
    img = MockBmpImage(800)
    msg = "测试中文\n😀 末尾空格   "
    s = stego.embed_text(img, msg)
    assert stego.extract_text(s) == msg

def test_capacity_exact_boundary():
    msg = "A" * 20
    frame = StegoFrame.pack(msg)
    need_bits = len(frame)*8
    img = MockBmpImage(need_bits)
    s = stego.embed_text(img, msg)
    assert stego.extract_text(s) == msg

def test_capacity_insufficient_raise():
    msg = "A" * 100
    frame = StegoFrame.pack(msg)
    need_bits = len(frame)*8
    img = MockBmpImage(need_bits - 1)
    with pytest.raises(InvalidPayloadError) as exc:
        stego.embed_text(img, msg)
    assert "carrier space insufficient" in str(exc.value)

def test_crc_tamper_raise():
    img = MockBmpImage(500)
    msg = "secret"
    s = stego.embed_text(img, msg)
    s._data[2] ^= 0x01
    with pytest.raises(InvalidPayloadError) as exc:
        stego.extract_text(s)
    assert "crc32 check failed" in str(exc.value)

def test_invalid_magic_raise():
    img = MockBmpImage(500)
    bad = b"\x05\x00\x00\x00" + b"\x00\x00\x00\x00" + b"BADXX" + b"abcde"
    bits = []
    for b in bad:
        for i in range(8):
            bits.append((b >> i) & 1)
    for idx, bit in enumerate(bits):
        pix = img.get_pixel_byte(idx)
        img.set_pixel_byte(idx, (pix & 0xFE) | bit)
    with pytest.raises(InvalidPayloadError):
        stego.extract_text(img)

def test_unused_bytes_unchanged():
    img = MockBmpImage(500)
    msg = "abc"
    s = stego.embed_text(img, msg)
    frame = StegoFrame.pack(msg)
    used_bits = len(frame)*8
    for off in range(used_bits, len(img._data)):
        assert s._data[off] == img._data[off]

def test_invalid_utf8_payload_raise():
    img = MockBmpImage(500)
    bad_payload = b"\xff\xfe\xfd"
    crc = zlib.crc32(bad_payload)&0xFFFFFFFF
    raw = len(bad_payload).to_bytes(4,"little") + crc.to_bytes(4,"little") + b"LSBv1" + bad_payload
    bits = []
    for b in raw:
        for i in range(8):
            bits.append((b >> i) & 1)
    for idx, bit in enumerate(bits):
        pix = img.get_pixel_byte(idx)
        img.set_pixel_byte(idx, (pix & 0xFE) | bit)
    with pytest.raises(InvalidPayloadError) as exc:
        stego.extract_text(img)
    assert "payload is not valid utf-8" in str(exc.value)

def test_original_image_not_modified():
    img = MockBmpImage(500)
    orig = bytes(img._data)
    _ = stego.embed_text(img, "test")
    assert bytes(img._data) == orig
