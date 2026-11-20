"""成员一实现。接口规范见 docs/architecture.md，字段级错误归类见 docs/integration.md §4。"""
import os
import struct
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

from .errors import InvalidBmpError, UnsupportedBmpError
from .models import BmpImage, PixelFormat, PreviewData

_SIGNATURE = b"BM"
_FILE_HEADER = struct.Struct("<2sIHHI")       # 签名/bfSize/保留1/保留2/bfOffBits
_INFO_HEADER = struct.Struct("<IiiHHIIiiII")  # biSize..biClrImportant，宽高有符号
_MIN_FILE = 18                                # 文件头 14 + biSize 4，读取 DIB 长度所需
_MIN_HEADER_FILE = 54                         # 文件头 14 + 40 字节 BITMAPINFOHEADER
_PALETTE_OFFSET = 54
_PALETTE_SIZE = 1024
_GRAY_PIXEL_OFFSET = 1078                     # 54 + 1024 调色板
_MAX_SIDE = 512
_SUPPORTED_BITS = (8, 24)
_GRAY_LUT = b"".join(bytes((i, i, i)) for i in range(256))
_GRAY_PALETTE = b"".join(bytes((i, i, i, 0)) for i in range(256))

# 不参与任何支持判定的字段（docs/integration.md §4：保持原样）：
# bfReserved1/2、调色板每项第 4 字节（保留字节）、biXPelsPerMeter、biYPelsPerMeter、
# biClrImportant。勿"顺手加严"。


def _row_stride(width: int, bit_count: int) -> int:
    return ((width * bit_count + 31) // 32) * 4


def _check_gray_palette(raw: bytes) -> None:
    """校验固定位于 54..1078 的灰度调色板：第 i 项 B=G=R=i；保留字节不查。

    调色板切片必然完整：调用前提是 bfOffBits >= 1078 且像素区未越界（见
    load_bmp 校验顺序第 8、9 步），故 len(raw) >= 1078。若重排校验顺序，
    需先保证该前提，否则引入越界读。
    """
    palette = raw[_PALETTE_OFFSET:_PALETTE_OFFSET + _PALETTE_SIZE]
    if palette == _GRAY_PALETTE:
        return
    for i in range(256):
        base = i * 4
        if palette[base] != i or palette[base + 1] != i or palette[base + 2] != i:
            raise UnsupportedBmpError(
                f"调色板第 {i} 项不是 B=G=R=索引的灰度（不支持伪彩色或重排灰度）")


def _parse(raw: bytes) -> BmpImage:
    """全部二进制校验；Invalid=结构损坏，Unsupported=超出课程支持范围。"""
    # 1-2：至少 18 字节才能读 DIB 长度；签名必须是 BM（截断与签名均先于 DIB 判定）
    if len(raw) < _MIN_FILE:
        raise InvalidBmpError(f"文件不足 {_MIN_FILE} 字节，头部截断")
    if raw[:2] != _SIGNATURE:
        raise InvalidBmpError("文件签名不是 BM，不是 BMP 文件")
    # 3：仅接受 40 字节 BITMAPINFOHEADER，其他 DIB 版本明确拒绝
    dib_size = struct.unpack_from("<I", raw, 14)[0]
    if dib_size != _INFO_HEADER.size:
        raise UnsupportedBmpError(f"DIB 头大小为 {dib_size}，仅支持 40 字节 BITMAPINFOHEADER")
    # 4：40 字节 DIB 要求文件至少 54 字节
    if len(raw) < _MIN_HEADER_FILE:
        raise InvalidBmpError(f"文件不足 {_MIN_HEADER_FILE} 字节，BITMAPINFOHEADER 截断")

    _, bf_size, _, _, bf_off_bits = _FILE_HEADER.unpack_from(raw, 0)
    (_, width, height, planes, bit_count, compression, size_image,
     _, _, clr_used, _) = _INFO_HEADER.unpack_from(raw, 14)

    # 5：bfSize 应与实际长度一致
    if bf_size != len(raw):
        raise InvalidBmpError(f"bfSize={bf_size} 与实际文件长度 {len(raw)} 不符")
    # 6：宽高为 0 属结构损坏
    if width == 0 or height == 0:
        raise InvalidBmpError(f"宽或高为 0（width={width}, height={height}）")
    # 7：其余超出支持范围的字段
    if width < 0:
        raise UnsupportedBmpError(f"宽度为负数 {width}")
    if width > _MAX_SIDE or abs(height) > _MAX_SIDE:
        raise UnsupportedBmpError(
            f"尺寸超限 {width}x{height}，宽高绝对值不得超过 {_MAX_SIDE}")
    if width % 4 != 0:
        raise UnsupportedBmpError(f"宽度 {width} 不是 4的倍数")
    if bit_count not in _SUPPORTED_BITS:
        raise UnsupportedBmpError(f"位深 {bit_count} 不在支持范围（仅 8/24）")
    if planes != 1:
        raise UnsupportedBmpError(f"biPlanes={planes}，仅支持 1")
    if compression != 0:
        raise UnsupportedBmpError(f"压缩方式 {compression} 不支持，仅支持 BI_RGB(0)")
    # 8：像素偏移不得落入文件头或调色板（24 位允许 [54,1078) 的额外间隔）
    min_off = _GRAY_PIXEL_OFFSET if bit_count == 8 else _MIN_HEADER_FILE
    if bf_off_bits < min_off:
        raise InvalidBmpError(
            f"bfOffBits={bf_off_bits} 落入文件头或调色板（该位深下限为 {min_off}）")
    # 9：像素区不得越界/截断
    stride = _row_stride(width, bit_count)
    abs_height = abs(height)
    if bf_off_bits + stride * abs_height > len(raw):
        raise InvalidBmpError("像素区越界或文件截断")
    # 10：BI_RGB 的 biSizeImage 可为 0 或实际像素区长度（stride*height）
    if size_image != 0 and size_image != stride * abs_height:
        raise InvalidBmpError(
            f"biSizeImage={size_image} 非 0 且不等于像素区长度 {stride * abs_height}")
    # 11：仅 8 位查调色板（24 位无调色板区，biClrUsed 不参与判定）
    pixel_format = PixelFormat.GRAY8 if bit_count == 8 else PixelFormat.BGR24
    if bit_count == 8:
        if clr_used not in (0, 256):
            raise UnsupportedBmpError(f"biClrUsed={clr_used}，8 位图仅支持 0 或 256")
        _check_gray_palette(raw)
    # 12：高度为负表示 top-down；models 约定 height 恒为正
    return BmpImage(width, abs_height, pixel_format, height < 0,
                    bf_off_bits, stride, raw)


def load_bmp(path: str | Path) -> BmpImage:
    """读取并完整校验 BMP；系统 IO 错误保留为 OSError，不包装。"""
    raw = Path(path).read_bytes()
    return _parse(raw)


def save_bmp(image: BmpImage, path: str | Path) -> None:
    """原样写出 raw_bytes：不重建头、不加扩展名、不建父目录、不弹覆盖确认。

    写同目录临时文件后原子替换，任一步失败清理临时文件并透传原异常。
    """
    target = Path(path)
    tmp = target.with_name(f".{target.name}.tmp-{os.getpid()}-{os.urandom(4).hex()}")
    try:
        with open(tmp, "xb") as f:  # 独占创建，残留临时文件不会导致覆盖
            f.write(image.raw_bytes)
        os.replace(tmp, target)
    except BaseException:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def iter_carrier_offsets(image: BmpImage) -> Iterator[int]:
    """按文件行顺序遍历有效像素字节偏移，排除填充、头部和调色板。

    恰好产生 carrier_count 个偏移；正负高度都使用文件顺序，保证读写一致。
    """
    per_row = image.width * image.channel_count
    for row in range(image.height):
        start = image.pixel_offset + row * image.row_stride
        for byte_index in range(per_row):
            yield start + byte_index


def to_preview(image: BmpImage) -> PreviewData:
    """按视觉方向逐行转为 RGB，输出 P6 PPM 字节（Tkinter 仅用于显示）。"""
    width, height = image.width, image.height
    per_row = width * image.channel_count
    rows = []
    for row in range(height):
        start = image.pixel_offset + row * image.row_stride
        seg = image.raw_bytes[start:start + per_row]  # 按行宽截取，排除填充
        if image.pixel_format is PixelFormat.GRAY8:
            rows.append(b"".join(_GRAY_LUT[v * 3:v * 3 + 3] for v in seg))
        else:  # BGR -> RGB：从原始 bytes 取值赋给 bytearray，避免交换后串读
            swapped = bytearray(seg)
            swapped[0::3] = seg[2::3]
            swapped[2::3] = seg[0::3]
            rows.append(bytes(swapped))
    if not image.top_down:  # bottom-up 存储需反转成视觉方向
        rows.reverse()
    header = b"P6\n" + f"{width} {height}\n255\n".encode("ascii")
    return PreviewData(header + b"".join(rows))
