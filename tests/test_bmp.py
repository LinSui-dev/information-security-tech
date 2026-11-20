"""成员一模块测试：独立于 stego/controller/ui，仅依赖 bmp、共享契约与夹具。

覆盖矩阵见 docs/integration.md §5 与开发计划：两类 BMP、正负高度、非均匀像素、
预览方向、BGR 转 RGB、偏移与文件保留、非法文件（InvalidBmpError）、不支持格式
（UnsupportedBmpError）、512 边界、逐字节 round-trip。
跨类别组合（Invalid+Unsupported 同时命中）的用例不在本文件断言——优先级未裁决。
"""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lsb_lab.bmp import iter_carrier_offsets, load_bmp, save_bmp, to_preview
from lsb_lab.contracts import capacity_for
from lsb_lab.errors import InvalidBmpError, LabError, UnsupportedBmpError
from lsb_lab.models import BmpImage, PixelFormat, PreviewData

try:  # discover -s tests 模式：tests/ 目录在 sys.path 上
    from bmp_factory import (
        GRAY_PIXEL_OFFSET,
        COLOR_PIXEL_OFFSET,
        FILE_HEADER,
        INFO_HEADER,
        build_bmp,
        color_image,
        default_color_pixels,
        default_gray_pixels,
        gray_image,
        gray_palette,
        make_color_bmp,
        make_gray_bmp,
        row_stride,
    )
except ImportError:  # 包式调用：tests.bmp_factory（需本机无同名 site-packages 包遮蔽）
    from tests.bmp_factory import (  # type: ignore
        GRAY_PIXEL_OFFSET,
        COLOR_PIXEL_OFFSET,
        FILE_HEADER,
        INFO_HEADER,
        build_bmp,
        color_image,
        default_color_pixels,
        default_gray_pixels,
        gray_image,
        gray_palette,
        make_color_bmp,
        make_gray_bmp,
        row_stride,
    )

PADDING_SENTINEL = 0xEE


class TempDirTestCase(unittest.TestCase):
    """提供临时目录与写盘辅助。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write_bmp(self, data: bytes, name: str = "test.bmp") -> Path:
        path = self.dir / name
        path.write_bytes(data)
        return path


class LoadValidTests(TempDirTestCase):
    def test_gray_16x8_fields(self):
        raw = make_gray_bmp(16, 8)
        image = load_bmp(self.write_bmp(raw))
        self.assertEqual(image.width, 16)
        self.assertEqual(image.height, 8)
        self.assertIs(image.pixel_format, PixelFormat.GRAY8)
        self.assertFalse(image.top_down)
        self.assertEqual(image.pixel_offset, GRAY_PIXEL_OFFSET)
        self.assertEqual(image.row_stride, 16)
        self.assertEqual(image.carrier_count, 128)
        self.assertEqual(image.raw_bytes, raw)

    def test_gray_top_down_negative_height(self):
        image = load_bmp(self.write_bmp(make_gray_bmp(16, 8, top_down=True)))
        self.assertTrue(image.top_down)
        self.assertEqual(image.height, 8)  # 恒为正，方向单独记录

    def test_color_8x8_fields(self):
        raw = make_color_bmp(8, 8)
        image = load_bmp(self.write_bmp(raw))
        self.assertEqual(image.width, 8)
        self.assertEqual(image.height, 8)
        self.assertIs(image.pixel_format, PixelFormat.BGR24)
        self.assertFalse(image.top_down)
        self.assertEqual(image.pixel_offset, COLOR_PIXEL_OFFSET)
        self.assertEqual(image.row_stride, 24)
        self.assertEqual(image.carrier_count, 192)
        self.assertEqual(image.raw_bytes, raw)

    def test_color_top_down(self):
        image = load_bmp(self.write_bmp(make_color_bmp(8, 8, top_down=True)))
        self.assertTrue(image.top_down)
        self.assertEqual(image.height, 8)

    def test_gray_gap_before_pixels(self):
        raw = make_gray_bmp(16, 8, gap=b"GAP!!")  # 偏移前的额外间隔允许存在并保留
        image = load_bmp(self.write_bmp(raw))
        self.assertEqual(image.pixel_offset, GRAY_PIXEL_OFFSET + 5)
        self.assertEqual(image.raw_bytes, raw)

    def test_color_offset_between_54_and_1078_allowed(self):
        # 钉住非对称规则：24 位偏移落在 [54,1078) 是合法 gap，8 位则是 Invalid
        raw = make_color_bmp(8, 4, gap=bytes(46))  # bfOffBits = 100
        image = load_bmp(self.write_bmp(raw))
        self.assertEqual(image.pixel_offset, 100)

    def test_trailing_bytes_preserved(self):
        raw = make_gray_bmp(16, 8, trailing=b"TAIL\x00")
        image = load_bmp(self.write_bmp(raw))
        self.assertEqual(image.raw_bytes[-5:], b"TAIL\x00")
        self.assertEqual(len(image.raw_bytes), len(raw))

    def test_bi_size_image_zero_and_exact_both_ok(self):
        exact = load_bmp(self.write_bmp(make_gray_bmp(16, 8)))
        zero = load_bmp(self.write_bmp(make_gray_bmp(16, 8, size_image=0)))
        self.assertEqual(exact.row_stride * exact.height, 128)
        self.assertEqual(zero.row_stride, 16)

    def test_min_4x4_gray_loads(self):
        image = load_bmp(self.write_bmp(make_gray_bmp(4, 4)))
        self.assertEqual(image.carrier_count, 16)

    def test_min_height_1_loads(self):
        image = load_bmp(self.write_bmp(make_gray_bmp(4, 1)))
        self.assertEqual(image.height, 1)
        self.assertEqual(image.carrier_count, 4)

    def test_512_boundary_both_formats(self):
        gray = load_bmp(self.write_bmp(make_gray_bmp(512, 512), "gray512.bmp"))
        color = load_bmp(self.write_bmp(make_color_bmp(512, 512), "color512.bmp"))
        self.assertEqual(capacity_for(gray).max_payload_bytes, 32755)
        self.assertEqual(capacity_for(color).max_payload_bytes, 98291)

    def test_ignored_fields_do_not_affect_support(self):
        palette = bytearray(gray_palette())
        palette[3::4] = b"\xff" * 256  # 调色板保留字节不参与判定
        raw = make_gray_bmp(16, 8, palette=bytes(palette),
                            reserved1=7, reserved2=9, xppm=100, yppm=100,
                            clr_important=5)
        image = load_bmp(self.write_bmp(raw))
        self.assertEqual(image.width, 16)

    def test_clr_used_0_and_256_both_ok(self):
        for used in (0, 256):
            with self.subTest(clr_used=used):
                image = load_bmp(self.write_bmp(make_gray_bmp(16, 8, clr_used=used)))
                self.assertEqual(image.height, 8)

    def test_oserror_passthrough(self):
        with self.assertRaises(OSError) as ctx:
            load_bmp(self.dir / "missing.bmp")
        self.assertNotIsInstance(ctx.exception, LabError)


class LoadInvalidTests(TempDirTestCase):
    def test_empty_and_tiny_file(self):
        for raw in (b"", b"BM\x00" * 3):
            with self.subTest(raw=raw):
                with self.assertRaises(InvalidBmpError):
                    load_bmp(self.write_bmp(raw))

    def test_bad_signature(self):
        with self.assertRaises(InvalidBmpError):
            load_bmp(self.write_bmp(make_color_bmp(8, 4, signature=b"XX")))

    def test_truncated_below_54(self):
        with self.assertRaises(InvalidBmpError):
            load_bmp(self.write_bmp(make_color_bmp(8, 4)[:40]))

    def test_short_file_beats_dib_check(self):
        raw = make_color_bmp(8, 4, dib_size=12)[:12]  # <18 字节且 DIB=12
        with self.assertRaises(InvalidBmpError):  # 截断判定先于 DIB 版本
            load_bmp(self.write_bmp(raw))

    def test_non_bm_beats_dib_check(self):
        raw = make_color_bmp(8, 4, signature=b"XX", dib_size=12)
        with self.assertRaises(InvalidBmpError):  # 签名判定先于 DIB 版本
            load_bmp(self.write_bmp(raw))

    def test_bf_size_mismatch(self):
        raw = make_gray_bmp(16, 8)
        for delta in (-1, 1):
            with self.subTest(delta=delta):
                with self.assertRaises(InvalidBmpError):
                    load_bmp(self.write_bmp(make_gray_bmp(16, 8, bf_size=len(raw) + delta)))

    def test_zero_width(self):
        with self.assertRaises(InvalidBmpError):
            load_bmp(self.write_bmp(make_gray_bmp(4, 4, bi_width=0)))

    def test_zero_height(self):
        with self.assertRaises(InvalidBmpError):
            load_bmp(self.write_bmp(make_gray_bmp(4, 4, bi_height=0)))

    def test_gray_offset_into_header(self):
        with self.assertRaises(InvalidBmpError):
            load_bmp(self.write_bmp(make_gray_bmp(4, 4, bf_off_bits=53)))

    def test_gray_offset_into_palette(self):
        for off in (54, 500):  # 8 位像素起点不得落入调色板区
            with self.subTest(off=off):
                with self.assertRaises(InvalidBmpError):
                    load_bmp(self.write_bmp(make_gray_bmp(4, 4, bf_off_bits=off)))

    def test_color_offset_into_header(self):
        with self.assertRaises(InvalidBmpError):
            load_bmp(self.write_bmp(make_color_bmp(8, 4, bf_off_bits=53)))

    def _truncated(self, raw: bytes) -> bytes:
        data = bytearray(raw)
        del data[-1]
        struct.pack_into("<I", data, 2, len(data))  # bfSize 同步为新长度
        return bytes(data)

    def test_gray_pixel_area_truncated(self):
        with self.assertRaises(InvalidBmpError):
            load_bmp(self.write_bmp(self._truncated(make_gray_bmp(16, 8))))

    def test_color_pixel_area_truncated(self):
        with self.assertRaises(InvalidBmpError):
            load_bmp(self.write_bmp(self._truncated(make_color_bmp(8, 4))))

    def test_bi_size_image_too_large(self):
        raw = make_gray_bmp(16, 8)  # 像素区长度 128
        with self.assertRaises(InvalidBmpError):
            load_bmp(self.write_bmp(make_gray_bmp(16, 8, size_image=len(raw) + 1 - 1078 + 1)))

    def test_bi_size_image_too_small(self):
        with self.assertRaises(InvalidBmpError):
            load_bmp(self.write_bmp(make_gray_bmp(16, 8, size_image=127)))


class LoadUnsupportedTests(TempDirTestCase):
    def test_dib_size_variants_rejected(self):
        for dib in (12, 108, 124):
            with self.subTest(dib=dib):
                with self.assertRaises(UnsupportedBmpError):
                    load_bmp(self.write_bmp(make_color_bmp(8, 4, dib_size=dib)))

    def test_bit_depth_variants_rejected(self):
        for bits in (1, 4, 16, 32):
            with self.subTest(bits=bits):
                raw = build_bmp(16, 4, bits, pixels=bytes(row_stride(16, bits) * 4))
                with self.assertRaises(UnsupportedBmpError):
                    load_bmp(self.write_bmp(raw))

    def test_planes_not_1(self):
        with self.assertRaises(UnsupportedBmpError):
            load_bmp(self.write_bmp(make_gray_bmp(16, 8, planes=2)))

    def test_compression_rejected(self):
        for comp in (1, 3):  # RLE8 / BITFIELDS
            with self.subTest(compression=comp):
                with self.assertRaises(UnsupportedBmpError):
                    load_bmp(self.write_bmp(make_gray_bmp(16, 8, compression=comp)))

    def test_negative_width(self):
        with self.assertRaises(UnsupportedBmpError):
            load_bmp(self.write_bmp(make_gray_bmp(16, 4, bi_width=-16)))

    def test_width_not_multiple_of_4(self):
        with self.assertRaises(UnsupportedBmpError):
            load_bmp(self.write_bmp(make_gray_bmp(6, 4, pixels=bytes(row_stride(6, 8) * 4))))

    def test_oversize_dimensions(self):
        cases = {
            "width_516": make_gray_bmp(516, 4, pixels=bytes(row_stride(516, 8) * 4)),
            "height_513": make_gray_bmp(4, 513, pixels=bytes(4 * 513)),
            "height_minus_513": make_gray_bmp(4, 513, pixels=bytes(4 * 513), top_down=True),
        }
        for name, raw in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(UnsupportedBmpError):
                    load_bmp(self.write_bmp(raw))

    def test_clr_used_16(self):
        with self.assertRaises(UnsupportedBmpError):
            load_bmp(self.write_bmp(make_gray_bmp(16, 8, clr_used=16)))

    def test_palette_pseudo_color(self):
        palette = bytearray(gray_palette())
        palette[0:3] = b"\x01\x00\x00"  # 第 0 项 B=1，非 B=G=R=索引
        with self.assertRaises(UnsupportedBmpError):
            load_bmp(self.write_bmp(make_gray_bmp(16, 8, palette=bytes(palette))))

    def test_palette_reordered_gray(self):
        palette = b"".join(bytes((255 - i, 255 - i, 255 - i, 0)) for i in range(256))
        with self.assertRaises(UnsupportedBmpError):  # 重排灰度同样不支持
            load_bmp(self.write_bmp(make_gray_bmp(16, 8, palette=palette)))


class SaveTests(TempDirTestCase):
    def test_round_trip_identical_bytes(self):
        cases = {
            "gray": make_gray_bmp(16, 8, gap=b"GAP", trailing=b"T\x00"),
            "color": make_color_bmp(8, 4),
        }
        for name, raw in cases.items():
            with self.subTest(name=name):
                source = self.write_bmp(raw, f"{name}.bmp")
                target = self.dir / f"{name}-out.bmp"
                save_bmp(load_bmp(source), target)
                self.assertEqual(target.read_bytes(), raw)  # 逐字节相同

    def test_overwrites_existing_target(self):
        target = self.dir / "out.bmp"
        target.write_bytes(b"OLD-CONTENT" * 10)
        raw = make_gray_bmp(4, 4)
        save_bmp(load_bmp(self.write_bmp(raw)), target)
        self.assertEqual(target.read_bytes(), raw)

    def test_no_extension_added(self):
        raw = make_gray_bmp(4, 4)
        source = self.write_bmp(raw)
        target = self.dir / "out"  # 无扩展名路径
        save_bmp(load_bmp(source), target)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["out", "test.bmp"])  # 不加扩展名，也无其他新文件

    def test_missing_parent_raises_oserror(self):
        image = load_bmp(self.write_bmp(make_gray_bmp(4, 4)))
        with self.assertRaises(OSError):
            save_bmp(image, self.dir / "no-such-dir" / "out.bmp")

    def test_no_temp_file_left(self):
        image = load_bmp(self.write_bmp(make_gray_bmp(4, 4)))
        save_bmp(image, self.dir / "out.bmp")
        self.assertFalse(any(".tmp" in p.name for p in self.dir.iterdir()))

    def test_failure_cleans_temp(self):
        image = load_bmp(self.write_bmp(make_gray_bmp(4, 4)))
        with mock.patch("lsb_lab.bmp.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_bmp(image, self.dir / "out.bmp")
        self.assertFalse(any(".tmp" in p.name for p in self.dir.iterdir()))

    def test_accepts_str_and_path(self):
        image = load_bmp(self.write_bmp(make_gray_bmp(4, 4)))
        save_bmp(image, str(self.dir / "a.bmp"))
        save_bmp(image, self.dir / "b.bmp")
        self.assertEqual((self.dir / "a.bmp").read_bytes(), image.raw_bytes)
        self.assertEqual((self.dir / "b.bmp").read_bytes(), image.raw_bytes)


class IterOffsetsTests(TempDirTestCase):
    def _padded_image(self) -> BmpImage:
        # 手工构造带行填充的对象（支持范围内磁盘文件不存在填充，见夹具说明）
        raw = bytearray(b"\x00" * 54)
        for row in range(3):
            raw += bytes(range(row * 4, row * 4 + 4))  # 4 个像素字节
            raw += bytes([PADDING_SENTINEL]) * 4       # 4 字节填充哨兵
        return BmpImage(4, 3, PixelFormat.GRAY8, False, 54, 8, bytes(raw))

    def test_count_equals_carrier_count(self):
        for image in (gray_image(8, 8), color_image(8, 8)):
            with self.subTest(fmt=image.pixel_format):
                offsets = list(iter_carrier_offsets(image))
                self.assertEqual(len(offsets), image.carrier_count)
                self.assertEqual(len(set(offsets)), image.carrier_count)  # 无重复

    def test_first_last_offset_gray(self):
        offsets = list(iter_carrier_offsets(gray_image(16, 8)))
        self.assertEqual(offsets[0], GRAY_PIXEL_OFFSET)
        self.assertEqual(offsets[-1], GRAY_PIXEL_OFFSET + 128 - 1)

    def test_bgr_channel_order(self):
        offsets = list(iter_carrier_offsets(color_image(4, 2)))
        self.assertEqual(offsets[:3], [COLOR_PIXEL_OFFSET, COLOR_PIXEL_OFFSET + 1,
                                       COLOR_PIXEL_OFFSET + 2])  # B、G、R 逐通道连续

    def test_offsets_skip_padding(self):
        image = self._padded_image()
        offsets = list(iter_carrier_offsets(image))
        self.assertEqual(offsets, [54, 55, 56, 57, 62, 63, 64, 65, 70, 71, 72, 73])
        self.assertEqual(len(offsets), image.carrier_count)  # 填充不计入
        raw = image.raw_bytes
        self.assertTrue(all(raw[o] != PADDING_SENTINEL for o in offsets))

    def test_file_order_regardless_of_direction(self):
        pixels = bytes(range(32))
        bottom_up = list(iter_carrier_offsets(gray_image(8, 4, pixels)))
        top_down = list(iter_carrier_offsets(gray_image(8, 4, pixels, top_down=True)))
        self.assertEqual(bottom_up, top_down)  # 正负高度都使用文件顺序

    def test_all_offsets_in_pixel_area(self):
        image = color_image(8, 4)
        per_row = image.width * image.channel_count
        for offset in iter_carrier_offsets(image):
            in_row = (offset - image.pixel_offset) % image.row_stride
            self.assertLess(in_row, per_row, f"偏移 {offset} 落入填充或区外")


class PreviewTests(TempDirTestCase):
    def _padded_image(self) -> BmpImage:
        raw = bytearray(b"\x00" * 54)
        for row in range(3):
            raw += bytes(range(row * 4, row * 4 + 4))
            raw += bytes([PADDING_SENTINEL]) * 4
        return BmpImage(4, 3, PixelFormat.GRAY8, False, 54, 8, bytes(raw))

    def test_ppm_header_exact(self):
        preview = to_preview(gray_image(4, 4))
        self.assertTrue(preview.ppm_bytes.startswith(b"P6\n4 4\n255\n"))

    def test_gray_bottom_up_reverses_rows(self):
        pixels = bytes(range(16))  # 非均匀像素
        preview = to_preview(gray_image(4, 4, pixels))
        header = b"P6\n4 4\n255\n"
        self.assertEqual(preview.ppm_bytes[:len(header)], header)
        body = preview.ppm_bytes[len(header):]
        # 视觉首行 = 文件末行（12,13,14,15），像素 (i,i,i)
        self.assertEqual(body[:12], b"".join(bytes((v, v, v)) for v in (12, 13, 14, 15)))

    def test_gray_top_down_keeps_file_order(self):
        pixels = bytes(range(16))
        preview = to_preview(gray_image(4, 4, pixels, top_down=True))
        body = preview.ppm_bytes[len(b"P6\n4 4\n255\n"):]
        self.assertEqual(body[:12], b"".join(bytes((v, v, v)) for v in (0, 1, 2, 3)))

    def test_color_bgr_swapped(self):
        pixels = bytes([0, 1, 2, 3, 4, 5]) + bytes(18)  # 首两个 BGR 像素 [0,1,2],[3,4,5]
        preview = to_preview(color_image(4, 2, pixels, top_down=True))
        body = preview.ppm_bytes[len(b"P6\n4 2\n255\n"):]
        self.assertEqual(body[:6], bytes([2, 1, 0, 5, 4, 3]))  # RGB 顺序

    def test_color_bottom_up_direction_and_swap(self):
        row0 = bytes((10, 20, 30)) * 4  # 文件首行
        row1 = bytes((40, 50, 60)) * 4  # 文件末行
        preview = to_preview(color_image(4, 2, row0 + row1))  # bottom-up
        body = preview.ppm_bytes[len(b"P6\n4 2\n255\n"):]
        self.assertEqual(body[:12], bytes((60, 50, 40)) * 4)  # 反转 + BGR→RGB

    def test_gray_lookup_extremes(self):
        pixels = bytes([0, 1, 127, 128, 255, 254, 2, 3])
        preview = to_preview(gray_image(8, 1, pixels, top_down=True))
        body = preview.ppm_bytes[len(b"P6\n8 1\n255\n"):]
        expected = b"".join(bytes((v, v, v)) for v in (0, 1, 127, 128, 255, 254, 2, 3))
        self.assertEqual(body, expected)

    def test_preview_excludes_padding(self):
        preview = to_preview(self._padded_image())
        self.assertEqual(len(preview.ppm_bytes), len(b"P6\n4 3\n255\n") + 4 * 3 * 3)
        body = preview.ppm_bytes[len(b"P6\n4 3\n255\n"):]
        self.assertNotIn(bytes([PADDING_SENTINEL]), body)

    def test_returns_preview_data(self):
        preview = to_preview(color_image(4, 2))
        self.assertIsInstance(preview, PreviewData)
        self.assertIsInstance(preview.ppm_bytes, bytes)


class FactoryTests(unittest.TestCase):
    def test_gray_bytes_layout(self):
        raw = make_gray_bmp(8, 4)
        signature, bf_size, _, _, off_bits = FILE_HEADER.unpack_from(raw, 0)
        (dib, width, height, planes, bits, comp, size_image,
         _, _, clr_used, _) = INFO_HEADER.unpack_from(raw, 14)
        self.assertEqual(signature, b"BM")
        self.assertEqual(bf_size, len(raw))
        self.assertEqual(off_bits, GRAY_PIXEL_OFFSET)
        self.assertEqual((dib, width, height, planes, bits, comp), (40, 8, 4, 1, 8, 0))
        self.assertEqual(size_image, row_stride(8, 8) * 4)
        self.assertEqual(clr_used, 256)
        self.assertEqual(raw[54:1078], gray_palette())
        self.assertEqual(raw[1078:], default_gray_pixels(8, 4))

    def test_color_bytes_layout(self):
        raw = make_color_bmp(8, 4)
        _, bf_size, _, _, off_bits = FILE_HEADER.unpack_from(raw, 0)
        (_, width, height, _, bits, comp, _, _, _, clr_used, _) = INFO_HEADER.unpack_from(raw, 14)
        self.assertEqual(bf_size, len(raw))
        self.assertEqual(off_bits, COLOR_PIXEL_OFFSET)  # 24 位无调色板
        self.assertEqual((width, height, bits, comp, clr_used), (8, 4, 24, 0, 0))
        self.assertEqual(raw[54:], default_color_pixels(8, 4))

    def test_top_down_header_sign(self):
        raw = make_gray_bmp(8, 4, top_down=True)
        height = INFO_HEADER.unpack_from(raw, 14)[2]
        self.assertEqual(height, -4)  # 负高度表示 top-down

    def test_default_pixels_non_uniform(self):
        self.assertGreaterEqual(len(set(default_gray_pixels(16, 8))), 2)
        self.assertGreaterEqual(len(set(default_color_pixels(8, 4))), 2)

    def test_pixels_length_validated(self):
        with self.assertRaises(ValueError):
            make_gray_bmp(4, 4, pixels=bytes(15))
        with self.assertRaises(ValueError):
            make_gray_bmp(4, 4, nonsense=1)

    def test_overrides_land_in_file(self):
        raw = make_gray_bmp(4, 4, bf_off_bits=1234, clr_used=7)
        self.assertEqual(FILE_HEADER.unpack_from(raw, 0)[4], 1234)
        self.assertEqual(INFO_HEADER.unpack_from(raw, 14)[9], 7)

    def test_gray_image_helper_matches_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            for helper, raw in ((gray_image(16, 8), make_gray_bmp(16, 8)),
                                (color_image(8, 4), make_color_bmp(8, 4))):
                path = Path(tmp) / "t.bmp"
                path.write_bytes(raw)
                loaded = load_bmp(path)
                self.assertEqual(loaded, helper)  # dataclass 全字段相等（含 raw_bytes）

    def test_baseline_capacities_real_files(self):
        # docs/integration.md §5 基线经真实文件侧证
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.bmp"
            path.write_bytes(make_gray_bmp(16, 8))
            cap = capacity_for(load_bmp(path))
            self.assertEqual((cap.carrier_bits, cap.max_payload_bytes), (128, 3))
            path.write_bytes(make_color_bmp(8, 8))
            cap = capacity_for(load_bmp(path))
            self.assertEqual((cap.carrier_bits, cap.max_payload_bytes), (192, 11))

    def test_teaching_images_cannot_hold_header(self):
        # 4×2、4×4 是合法 BMP，可正常读取，但正式模式容量不足
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.bmp"
            for width, height in ((4, 2), (4, 4)):
                path.write_bytes(make_gray_bmp(width, height))
                cap = capacity_for(load_bmp(path))
                self.assertFalse(cap.can_store_header)


if __name__ == "__main__":
    unittest.main()
