import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from lsb_lab.controller import LabController
from lsb_lab import bmp
from lsb_lab.errors import CapacityError, InvalidPayloadError
from bmp_factory import make_gray_bmp, make_color_bmp


class IntegrationTests(unittest.TestCase):
    def test_disk_roundtrip_both_formats_directions_and_fresh_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for factory in (make_gray_bmp, make_color_bmp):
                for top_down in (False, True):
                    with self.subTest(factory=factory.__name__, top_down=top_down):
                        source, output = root/'source.bmp', root/'stego.bmp'
                        raw = factory(32, 16, top_down=top_down, gap=b'GAP', trailing=b'TAIL')
                        source.write_bytes(raw)
                        c = LabController()
                        c.open_source(source)
                        text = '独立磁盘验证\n😀  '
                        c.embed(text)
                        c.save_stego(output)
                        self.assertEqual(source.read_bytes(), raw)
                        self.assertEqual(LabController().extract_from(output).text, text)
                        run = subprocess.run([sys.executable, '-c',
                            'from lsb_lab.controller import LabController; import sys; '
                            'sys.stdout.buffer.write(LabController().extract_from(sys.argv[1]).payload)',
                            str(output)], capture_output=True, check=True)
                        self.assertEqual(run.stdout, text.encode())
                        saved = bmp.load_bmp(output)
                        self.assertEqual(saved.raw_bytes[:saved.pixel_offset], raw[:saved.pixel_offset])
                        self.assertEqual(saved.raw_bytes[-4:], b'TAIL')
                        preview = c.get_result_preview().ppm_bytes
                        self.assertEqual(len(preview), len(b'P6\n32 16\n255\n') + 32*16*3)

    def test_capacity_and_corrupt_disk_preserve_state(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'source.bmp'
            source.write_bytes(make_gray_bmp(16, 8))
            c = LabController()
            c.open_source(source)
            c.embed('中')
            old = c.state
            with self.assertRaises(CapacityError):
                c.embed('中a')
            self.assertIs(c.state, old)
            bad = bytearray(c.state.stego.raw_bytes)
            bad[c.state.stego.pixel_offset + 104] ^= 1
            source.with_name('bad.bmp').write_bytes(bad)
            with self.assertRaises(InvalidPayloadError):
                c.extract_from(source.with_name('bad.bmp'))
            self.assertIs(c.state, old)
