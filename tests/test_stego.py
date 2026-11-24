import unittest
import zlib
from dataclasses import replace
from lsb_lab import bmp, stego
from lsb_lab.contracts import pack_header
from lsb_lab.errors import CapacityError, InvalidPayloadError
from bmp_factory import gray_image, color_image


class StegoTests(unittest.TestCase):
    def raw_frame(self, image, raw):
        data = bytearray(image.raw_bytes)
        for off, bit in zip(bmp.iter_carrier_offsets(image), stego._bytes_to_bits(raw)):
            data[off] = (data[off] & 254) | bit
        return replace(image, raw_bytes=bytes(data))

    def test_roundtrip(self):
        for factory in (gray_image, color_image):
            for text in ('', 'hello world', '中文\n😀 尾部  '):
                with self.subTest(factory=factory.__name__, text=text):
                    image = factory(32, 16)
                    result = stego.extract_text(stego.embed_text(image, text))
                    self.assertEqual(result.text, text)
                    self.assertEqual(result.payload, text.encode())
                    self.assertEqual(result.checksum, zlib.crc32(text.encode()))

    def test_capacity(self):
        image = gray_image(16, 8)
        self.assertEqual(stego.extract_text(stego.embed_text(image, '中')).text, '中')
        for image, text in ((image, '中a'), (gray_image(4, 2), ''), (gray_image(4, 4), '')):
            with self.assertRaises(CapacityError):
                stego.embed_text(image, text)

    def test_wire_order_and_preservation(self):
        image = color_image(16, 8, bytes(range(256)) + bytes(range(128)))
        original = image.raw_bytes
        result = stego.embed_text(image, 'a')
        start = image.pixel_offset
        self.assertEqual(result.raw_bytes[start:start+6], bytes([0, 1, 2, 2, 5, 5]))
        self.assertEqual(image.raw_bytes, original)
        self.assertEqual(result.raw_bytes[:start], original[:start])
        used = (13 + 1) * 8
        self.assertEqual(result.raw_bytes[start+used:], original[start+used:])
        self.assertTrue(all((a ^ b) <= 1 for a, b in zip(original, result.raw_bytes)))

    def test_invalid_frames(self):
        image = gray_image(32, 16)
        valid = pack_header(b'abc') + b'abc'
        invalid = [b'BAD!' + valid[4:], valid[:4] + b'\x02' + valid[5:],
                   valid[:5] + (99999).to_bytes(4, 'little') + valid[9:],
                   valid[:-1] + b'd', pack_header(b'\xff') + b'\xff']
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(InvalidPayloadError):
                stego.extract_text(self.raw_frame(image, raw))
        with self.assertRaises(InvalidPayloadError):
            stego.extract_text(gray_image(4, 2))

    def test_small_teaching_bits(self):
        for width, height, payload in ((4, 2, b'?'), (4, 4, b'?S')):
            image = self.raw_frame(gray_image(width, height), payload)
            bits = (image.raw_bytes[o] & 1 for o in bmp.iter_carrier_offsets(image))
            self.assertEqual(stego._bits_to_bytes(bits), payload)
