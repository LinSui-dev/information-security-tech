import sqlite3
import unittest
from pathlib import Path

from lsb_lab.contracts import capacity_for, encode_text, pack_header, unpack_header
from lsb_lab.errors import CapacityError, InvalidPayloadError
from lsb_lab.models import BmpImage, PixelFormat


def image(width, height, fmt=PixelFormat.GRAY8):
    return BmpImage(width, height, fmt, False, 54, width, b'')


class ContractsTests(unittest.TestCase):
    def test_small_teaching_image_cannot_hold_frame(self):
        cap = capacity_for(image(4, 2))
        self.assertFalse(cap.can_store_header)
        with self.assertRaises(CapacityError):
            encode_text('', cap)

    def test_utf8_capacity_boundary(self):
        cap = capacity_for(image(16, 8))  # 16 bytes total, 3 bytes payload
        self.assertEqual(cap.max_payload_bytes, 3)
        self.assertEqual(encode_text('中', cap), '中'.encode())
        with self.assertRaises(CapacityError):
            encode_text('中a', cap)

    def test_frame_wire_format(self):
        # CRC32 of ASCII 123456789 is the standard check value 0xCBF43926.
        payload = b'123456789'
        header = pack_header(payload)
        self.assertEqual(header, b'LSB1\x01\x09\x00\x00\x00\x26\x39\xf4\xcb')
        self.assertEqual(unpack_header(header, capacity_for(image(32, 8))),
                         (9, 0xCBF43926))

    def test_untrusted_length_and_magic_rejected(self):
        cap = capacity_for(image(16, 8))
        for header in (pack_header(b'abcd'), b'BAD!' + pack_header(b'')[4:]):
            with self.assertRaises(InvalidPayloadError):
                unpack_header(header, cap)

    def test_rgb_uses_three_channels(self):
        self.assertEqual(capacity_for(image(512, 512, PixelFormat.BGR24)).max_payload_bytes,
                         98291)

    def test_optional_schema_foreign_key(self):
        schema = Path(__file__).resolve().parents[1] / 'docs' / 'schema.sql'
        with sqlite3.connect(':memory:') as db:
            db.executescript(schema.read_text(encoding='utf-8'))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO artifact (experiment_id, role, relative_path, sha256) '
                           'VALUES (?, ?, ?, ?)', ('missing', 'source', 'a.bmp', 'a' * 64))


if __name__ == '__main__':
    unittest.main()
