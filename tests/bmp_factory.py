"""三人共享的标准库 BMP 测试夹具（仅测试用途）。

不 import lsb_lab.bmp——成员二可在 bmp.py 完成前直接使用本模块，只依赖共享 models。
默认像素为确定性非均匀图案（docs/integration.md §5：夹具必须含非均匀像素，
不能只用全零图验证方向）。

不变量：支持范围内（宽为 4 的倍数）row_stride 恰等于每行字节数，磁盘文件不存在
行填充；需要验证"忽略行填充"时应手工构造 BmpImage（stride 大于行字节数），
不要试图用本模块生成带填充的"合法"文件。

在 tests/ 下的测试文件中导入本模块：`python -m unittest discover -s tests`
模式下可直接 `from bmp_factory import ...`；若用包式调用
（`python -m unittest tests.test_xxx`）需 `from tests.bmp_factory import ...`，
且要求本机 site-packages 中没有同名的 `tests` 包（部分环境存在，会遮蔽本地
命名空间包）。推荐统一使用 discover 模式。
"""
import struct

from lsb_lab.models import BmpImage, PixelFormat

FILE_HEADER = struct.Struct("<2sIHHI")        # 14 字节文件头
INFO_HEADER = struct.Struct("<IiiHHIIiiII")   # 40 字节 BITMAPINFOHEADER
GRAY_PIXEL_OFFSET = 1078                      # 54 + 1024 调色板
COLOR_PIXEL_OFFSET = 54

_FIELDS = ("signature", "bf_size", "reserved1", "reserved2", "bf_off_bits",
           "dib_size", "bi_width", "bi_height", "planes", "bit_count",
           "compression", "size_image", "xppm", "yppm", "clr_used", "clr_important")


def gray_palette() -> bytes:
    """标准 256 项灰度调色板：第 i 项 B=G=R=i，保留字节 0。"""
    out = bytearray()
    for i in range(256):
        out += bytes((i, i, i, 0))
    return bytes(out)


def row_stride(width: int, bit_count: int) -> int:
    """契约规定的行跨度公式，供测试引用的权威实现。"""
    return ((width * bit_count + 31) // 32) * 4


def default_gray_pixels(width: int, height: int) -> bytes:
    """确定性非均匀灰度像素（文件序，长度 width*height）。"""
    return bytes(((r * width + c) * 7 + 1) & 0xFF
                 for r in range(height) for c in range(width))


def default_color_pixels(width: int, height: int) -> bytes:
    """确定性非均匀 BGR 像素（文件序，长度 width*height*3，B/G/R 彼此错开）。"""
    out = bytearray()
    for r in range(height):
        for c in range(width):
            b = (r * 31 + c * 7) & 0xFF
            g = (b + 60) & 0xFF
            red = (b + 120) & 0xFF
            out += bytes((b, g, red))
    return bytes(out)


def build_bmp(width: int, height: int, bit_count: int, pixels: bytes | None = None,
              *, top_down: bool = False, palette: bytes | None = None,
              gap: bytes = b"", trailing: bytes = b"",
              **overrides: int | bytes) -> bytes:
    """按契约布局构造 BMP 字节，用于构造合法、非法及不支持样例。

    布局：文件头 + 信息头 +（仅 8 位）调色板 + gap + pixels + trailing；
    bfOffBits/bfSize 自动计算。pixels 长度必须等于 row_stride(width,
    bit_count)*height，否则 ValueError（夹具自保护）。

    bit_count 可取 1/4/8/16/24/32（大于 8 时不放置调色板），用于构造
    不支持位深的样例。width/height 为逻辑尺寸（width 必须为正），负宽、
    零尺寸等非法头字段通过 overrides 传入。

    **overrides 在布局计算完成后覆写头字段，专造单点非法样例（覆写后
    头部与数据区不再自洽，这正是用途）。可用键：signature/bf_size/
    reserved1/reserved2/bf_off_bits/dib_size/bi_width/bi_height/planes/
    bit_count/compression/size_image/xppm/yppm/clr_used/clr_important；
    其中宽高用 bi_width/bi_height（避免与布局参数 width/height 撞名）；
    未知键抛 ValueError。
    """
    unknown = set(overrides) - set(_FIELDS)
    if unknown:
        raise ValueError(f"未知头字段覆写: {sorted(unknown)}")
    if width <= 0:
        raise ValueError("width 必须为正；负宽请用 overrides 覆写")
    if height <= 0:
        raise ValueError("height 必须为正；零高度请用 overrides 覆写")
    if bit_count not in (1, 4, 8, 16, 24, 32):
        raise ValueError(f"不支持的夹具位深 {bit_count}")
    if pixels is None:
        pixels = (default_gray_pixels(width, height) if bit_count == 8
                  else default_color_pixels(width, height))
    if len(pixels) != row_stride(width, bit_count) * height:
        raise ValueError("pixels 长度必须等于 row_stride(width, bit_count)*height")
    if bit_count == 8:
        if palette is None:
            palette = gray_palette()
        if len(palette) != 1024:
            raise ValueError("8 位调色板必须为 1024 字节")

    signed_height = -height if top_down else height
    has_palette = bit_count == 8
    off_bits = FILE_HEADER.size + INFO_HEADER.size + (len(palette) if has_palette else 0) + len(gap)
    total = off_bits + len(pixels) + len(trailing)
    fields: dict[str, int | bytes] = {
        "signature": b"BM",
        "bf_size": total,
        "reserved1": 0,
        "reserved2": 0,
        "bf_off_bits": off_bits,
        "dib_size": INFO_HEADER.size,
        "bi_width": width,
        "bi_height": signed_height,
        "planes": 1,
        "bit_count": bit_count,
        "compression": 0,
        "size_image": len(pixels),
        "xppm": 0,
        "yppm": 0,
        "clr_used": 256 if has_palette else 0,
        "clr_important": 0,
    }
    fields.update(overrides)
    file_header = FILE_HEADER.pack(fields["signature"], fields["bf_size"],
                                   fields["reserved1"], fields["reserved2"],
                                   fields["bf_off_bits"])
    info_header = INFO_HEADER.pack(fields["dib_size"], fields["bi_width"],
                                   fields["bi_height"], fields["planes"],
                                   fields["bit_count"], fields["compression"],
                                   fields["size_image"], fields["xppm"],
                                   fields["yppm"], fields["clr_used"],
                                   fields["clr_important"])
    palette_bytes = palette if has_palette else b""
    return file_header + info_header + palette_bytes + gap + pixels + trailing


def make_gray_bmp(width: int, height: int, pixels: bytes | None = None, *,
                  top_down: bool = False, palette: bytes | None = None,
                  gap: bytes = b"", trailing: bytes = b"",
                  **overrides: int | bytes) -> bytes:
    """8 位 256 级灰度 BMP 薄封装。"""
    return build_bmp(width, height, 8, pixels, top_down=top_down, palette=palette,
                     gap=gap, trailing=trailing, **overrides)


def make_color_bmp(width: int, height: int, pixels: bytes | None = None, *,
                   top_down: bool = False, gap: bytes = b"", trailing: bytes = b"",
                   **overrides: int | bytes) -> bytes:
    """24 位真彩 BMP 薄封装。"""
    return build_bmp(width, height, 24, pixels, top_down=top_down,
                     gap=gap, trailing=trailing, **overrides)


def gray_image(width: int, height: int, pixels: bytes | None = None, *,
               top_down: bool = False) -> BmpImage:
    """内存 BmpImage，字段与 load_bmp 写盘读取结果完全一致（含 raw_bytes）。

    供成员二免磁盘单测（integration.md §1 允许"测试构造的 BmpImage"）。
    """
    raw = make_gray_bmp(width, height, pixels, top_down=top_down)
    return BmpImage(width, height, PixelFormat.GRAY8, top_down,
                    GRAY_PIXEL_OFFSET, row_stride(width, 8), raw)


def color_image(width: int, height: int, pixels: bytes | None = None, *,
                top_down: bool = False) -> BmpImage:
    """同 gray_image 的 24 位版本。"""
    raw = make_color_bmp(width, height, pixels, top_down=top_down)
    return BmpImage(width, height, PixelFormat.BGR24, top_down,
                    COLOR_PIXEL_OFFSET, row_stride(width, 24), raw)
