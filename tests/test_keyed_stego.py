"""带密钥随机间隔 LSB（KLS1）的单元测试。

独立于 noise/analysis、控制器和 UI，只依赖 keyed_stego、bmp、共享模型/异常与夹具。
已知向量来自 docs/keyed-stego.md 附录 A 的独立参考实现（只用 hashlib/hmac/
struct/zlib）以及 RFC 4231；不以模块自身的嵌入/提取互相验证来代替。
"""
from dataclasses import replace
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
import zlib

from lsb_lab import bmp, keyed_stego, stego
from lsb_lab.errors import CapacityError, InvalidPayloadError, LabError
from lsb_lab.models import BmpImage, Capacity, ExtractionResult
from bmp_factory import color_image, gray_image, make_color_bmp, make_gray_bmp

REPO = Path(__file__).resolve().parents[1]
KEY = "correct horse 密钥🔑"
SALT = bytes(range(16))
SALT2 = bytes([0xFF] * 16)
SAMPLE = REPO / "samples" / "lsb-demo-256x256.bmp"

# ---- 独立参考实现生成的已知向量（docs/keyed-stego.md 附录 A）----
VECTOR_KEY_1 = "vector-key-1"
VECTOR_KEY_2 = "向量密钥🔑"
V1_POSITIONS_64 = [
    360, 372, 379, 386, 392, 404, 410, 419, 424, 437, 445, 454, 458, 468, 474, 480,
    494, 496, 508, 513, 525, 531, 543, 550, 553, 560, 573, 578, 586, 593, 602, 613,
    619, 624, 633, 647, 648, 658, 665, 674, 687, 688, 703, 707, 717, 720, 733, 738,
    751, 758, 763, 772, 783, 786, 796, 800, 812, 822, 829, 837, 843, 852, 860, 868,
]
V2_POSITIONS_16 = [363, 372, 377, 391, 395, 405, 414, 416, 428, 439, 446, 455, 458, 470, 479, 486]
V3_FRAMES = {  # (key, salt, payload) -> 完整帧 hex：meta(29) + tag(16) + payload
    (VECTOR_KEY_1, SALT, b"Hi"): (
        "4b4c533101000102030405060708090a0b0c0d0e0f020000000e0e174d"
        "1378261a890222071b49ae00b42c3ba54869"),
    (VECTOR_KEY_1, SALT, b""): (
        "4b4c533101000102030405060708090a0b0c0d0e0f0000000000000000"
        "76247c61d3b41b8f9d0c13d7599944f4"),
    (VECTOR_KEY_2, SALT2, "中\n".encode()): (
        "4b4c533101ffffffffffffffffffffffffffffffff04000000618d6848"
        "092bc7f51aabe208efb05dc75f88e6a7e4b8ad0a"),
}
# key=vector-key-1, salt=00..0f, payload=b"Hi" 时，前 120 个逻辑通道的 LSB
V4_BOOTSTRAP_LSB_PREFIX = (
    "010010110100110001010011001100010000000100000000000000010000"
    "001000000011000001000000010100000110000001110000100000001001"
)
RFC4231_TC1 = "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"


def read_lsbs(image: BmpImage, logical) -> str:
    """测试自带的读位函数：直接按逻辑通道索引查官方迭代器，不经过被测模块。"""
    offsets = list(bmp.iter_carrier_offsets(image))
    return "".join(str(image.raw_bytes[offsets[i]] & 1) for i in logical)


def bits_of(data: bytes) -> str:
    return "".join(format(value, "08b") for value in data)


def flip_lsb(raw: bytes, offset: int) -> bytearray:
    data = bytearray(raw)
    data[offset] ^= 1
    return data


class KnownVectorTests(unittest.TestCase):
    """用模块之外的已知向量检验原语、帧和位置规则。"""

    def test_hmac_primitive_matches_rfc4231(self):
        # RFC 4231 §4.2 测试向量 1：key = 0x0b×20，data = "Hi There"
        self.assertEqual(keyed_stego._mac256(b"\x0b" * 20, b"Hi There").hex(), RFC4231_TC1)

    def test_positions_match_reference_vectors(self):
        cases = ((VECTOR_KEY_1, SALT, "12345678", V1_POSITIONS_64),
                 (VECTOR_KEY_2, SALT2, "ab", V2_POSITIONS_16))
        for key, salt, text, expected in cases:
            with self.subTest(key=key):
                image = keyed_stego.embed_text(gray_image(64, 32), text, key=key, salt=salt)
                self.assertEqual(list(keyed_stego.payload_positions(image, key=key)), expected)

    def test_frame_matches_reference_vectors(self):
        for (key, salt, payload), frame_hex in V3_FRAMES.items():
            with self.subTest(key=key, payload=payload):
                source = gray_image(64, 32)
                image = keyed_stego.embed_text(source, payload.decode("utf-8"), key=key, salt=salt)
                positions = list(keyed_stego.payload_positions(image, key=key))
                got = read_lsbs(image, list(range(360)) + positions)
                self.assertEqual(got, bits_of(bytes.fromhex(frame_hex)))
                # 帧内的盐与显式盐一致，且明文密钥不出现在载体中
                self.assertEqual(bytes.fromhex(frame_hex)[5:21], salt)
                self.assertNotIn(key.encode("utf-8"), image.raw_bytes)

    def test_bootstrap_bits_on_all_zero_image(self):
        # 像素全 0 的灰度图：嵌入前 LSB 全 0，嵌入后前 120 个逻辑通道即 bootstrap 的原始位
        image0 = gray_image(64, 32, pixels=bytes(64 * 32))
        self.assertEqual(read_lsbs(image0, range(64 * 32)), "0" * (64 * 32))
        image = keyed_stego.embed_text(image0, "Hi", key=VECTOR_KEY_1, salt=SALT)
        self.assertEqual(read_lsbs(image, range(120)), V4_BOOTSTRAP_LSB_PREFIX)


PROCESS_CODE = (
    "import sys\n"
    "from lsb_lab import bmp, keyed_stego\n"
    "try:\n"
    "    result = keyed_stego.extract_text(bmp.load_bmp(sys.argv[1]), key=sys.argv[2])\n"
    "except Exception as exc:\n"
    "    print('FAIL', type(exc).__name__)\n"
    "else:\n"
    "    print('OK', result.payload.hex())\n"
)


def frame_bytes(image: BmpImage) -> bytes:
    """测试自带的 bootstrap 读取：前 360 个逻辑通道按位拼成 45 字节。"""
    bits = read_lsbs(image, range(360))
    return bytes(int(bits[i:i + 8], 2) for i in range(0, 360, 8))


def check_positions(test: unittest.TestCase, positions, carrier_count: int) -> None:
    """位置规则：升序唯一、不越界、不占 bootstrap、每组恰取一位、间隔 1～15。"""
    test.assertEqual(tuple(positions), tuple(sorted(set(positions))))
    for index, position in enumerate(positions):
        test.assertTrue(360 <= position < carrier_count, f"位置 {position} 越界或落入 bootstrap")
        test.assertEqual((position - 360) // 8, index, "第 %d 位不在自己的分组内" % index)
    for before, after in zip(positions, positions[1:]):
        test.assertTrue(1 <= after - before <= 15, f"间隔 {after - before} 超出 [1, 15]")


class RoundTripTests(unittest.TestCase):
    TEXTS = ("", "hello", "中文\n😀  尾空格  ", " ", "a\r\nb\tc", "x" * 100)

    def test_roundtrip_texts_formats_directions(self):
        for factory in (gray_image, color_image):
            for top_down in (False, True):
                for text in self.TEXTS:
                    with self.subTest(factory=factory.__name__, top_down=top_down, text=text):
                        image = factory(128, 64, top_down=top_down)
                        result = keyed_stego.extract_text(
                            keyed_stego.embed_text(image, text, key=KEY, salt=SALT), key=KEY)
                        self.assertIsInstance(result, ExtractionResult)
                        self.assertEqual(result.text, text)
                        self.assertEqual(result.payload, text.encode("utf-8"))
                        self.assertEqual(result.checksum, zlib.crc32(text.encode("utf-8")))

    def test_same_key_salt_gives_identical_carrier(self):
        for source in (gray_image(64, 32), color_image(64, 32, top_down=True)):
            first = keyed_stego.embed_text(source, "秘密 message", key=KEY, salt=SALT)
            second = keyed_stego.embed_text(source, "秘密 message", key=KEY, salt=SALT)
            self.assertEqual(first.raw_bytes, second.raw_bytes)

    def test_new_salt_changes_carrier(self):
        source = gray_image(64, 32)
        base = keyed_stego.embed_text(source, "秘密", key=KEY, salt=SALT)
        self.assertNotEqual(
            keyed_stego.embed_text(source, "秘密", key=KEY, salt=SALT2).raw_bytes, base.raw_bytes)
        self.assertEqual(frame_bytes(base)[5:21], SALT)  # 盐原样写入帧头
        first = keyed_stego.embed_text(source, "秘密", key=KEY)
        second = keyed_stego.embed_text(source, "秘密", key=KEY)
        self.assertNotEqual(first.raw_bytes, second.raw_bytes)  # 默认盐每次由 secrets 生成
        salt_first, salt_second = frame_bytes(first)[5:21], frame_bytes(second)[5:21]
        self.assertEqual((len(salt_first), len(salt_second)), (16, 16))
        self.assertNotEqual(salt_first, salt_second)
        for carrier in (first, second):
            self.assertEqual(keyed_stego.extract_text(carrier, key=KEY).text, "秘密")

    def test_wrong_key_fails(self):
        wrong_keys = (KEY + " ", " " + KEY, KEY.replace(" ", ""), KEY.upper(),
                      KEY[:-1] + "🗝", "密码🔑", "correct horse")
        for text in ("", "秘密 message"):
            carrier = keyed_stego.embed_text(gray_image(64, 32), text, key=KEY, salt=SALT)
            self.assertEqual(keyed_stego.extract_text(carrier, key=KEY).text, text)
            for wrong in wrong_keys:
                with self.subTest(text=text, wrong=wrong), self.assertRaises(InvalidPayloadError):
                    keyed_stego.extract_text(carrier, key=wrong)

    def test_embed_returns_new_image_and_keeps_input(self):
        source = gray_image(64, 32)
        original = source.raw_bytes
        result = keyed_stego.embed_text(source, "秘密", key=KEY, salt=SALT)
        self.assertIsNot(result, source)
        self.assertIsInstance(result, BmpImage)
        self.assertEqual(source.raw_bytes, original)
        self.assertEqual(result, replace(source, raw_bytes=result.raw_bytes))  # 其余字段不变


class DiskAndProcessTests(unittest.TestCase):
    def run_fresh_process(self, path: Path, key: str) -> str:
        run = subprocess.run([sys.executable, "-c", PROCESS_CODE, str(path), key],
                             capture_output=True, check=True, cwd=REPO, encoding="utf-8")
        return run.stdout.strip()

    def test_disk_roundtrip_and_fresh_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for factory, name in ((make_gray_bmp, "gray"), (make_color_bmp, "color")):
                for top_down in (False, True):
                    with self.subTest(name=name, top_down=top_down):
                        raw = factory(64, 32, top_down=top_down, gap=b"GAP", trailing=b"TAIL")
                        source, target = root / "source.bmp", root / "stego.bmp"
                        source.write_bytes(raw)
                        text = "独立磁盘验证\n😀  "
                        carrier = keyed_stego.embed_text(bmp.load_bmp(source), text, key=KEY)
                        bmp.save_bmp(carrier, target)  # 默认盐；不需要原图即可提取
                        self.assertEqual(source.read_bytes(), raw)
                        out = self.run_fresh_process(target, KEY)
                        self.assertTrue(out.startswith("OK "), out)
                        self.assertEqual(bytes.fromhex(out.split()[1]), text.encode("utf-8"))
                        self.assertEqual(self.run_fresh_process(target, "wrong key"),
                                         "FAIL InvalidPayloadError")
                        saved = bmp.load_bmp(target)
                        self.assertEqual(saved.raw_bytes[:saved.pixel_offset], raw[:saved.pixel_offset])
                        self.assertEqual(saved.raw_bytes[-4:], b"TAIL")
                        # 只有 bootstrap 与正文占用字节的 LSB 发生变化
                        changed = [i for i, (a, b) in enumerate(zip(raw, saved.raw_bytes)) if a != b]
                        offsets = list(bmp.iter_carrier_offsets(saved))
                        used = set(range(360)) | set(keyed_stego.payload_positions(saved, key=KEY))
                        self.assertTrue(set(changed) <= {offsets[i] for i in used})
                        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(raw, saved.raw_bytes)))

    @unittest.skipUnless(SAMPLE.exists(), "仓库未提供共享样例")
    def test_shared_sample_roundtrip(self):
        source = bmp.load_bmp(SAMPLE)
        self.assertEqual((source.width, source.height), (256, 256))
        cap = keyed_stego.capacity_for_keyed(source)  # (256×256×3 − 360) // 8 // 8 = 3066
        self.assertEqual(cap.max_payload_bytes, 3066)
        text = "共享样例 shared sample 😀"
        self.assertEqual(keyed_stego.extract_text(
            keyed_stego.embed_text(source, text, key=KEY), key=KEY).text, text)


class CapacityTests(unittest.TestCase):
    def test_capacity_values(self):
        # 手算：max_payload = floor((通道数 − 360) / 8) // 8；header_bytes = 29 + 16 = 45
        cases = ((gray_image(16, 8), 128, 0, False), (gray_image(32, 16), 512, 2, True),
                 (color_image(32, 16), 1536, 18, True), (gray_image(4, 90), 360, 0, True),
                 (gray_image(4, 105), 420, 0, True), (gray_image(4, 106), 424, 1, True),
                 (gray_image(512, 512), 262144, 4090, True),
                 (color_image(512, 512), 786432, 12282, True))
        for image, carrier, max_payload, can_store in cases:
            with self.subTest(carrier=carrier):
                self.assertEqual(keyed_stego.capacity_for_keyed(image),
                                 Capacity(carrier, 45, max_payload, can_store))

    def test_exact_capacity_ok_and_one_more_fails(self):
        for image in (gray_image(4, 90), gray_image(4, 106), gray_image(32, 16),
                      color_image(64, 32), gray_image(512, 512), color_image(512, 512)):
            cap = keyed_stego.capacity_for_keyed(image)
            with self.subTest(carrier=cap.carrier_bits, max_payload=cap.max_payload_bytes):
                text = "a" * cap.max_payload_bytes  # 上限 0 时即合法空消息
                carrier = keyed_stego.embed_text(image, text, key=KEY, salt=SALT)
                self.assertEqual(keyed_stego.extract_text(carrier, key=KEY).payload,
                                 text.encode("utf-8"))
                with self.assertRaises(CapacityError):
                    keyed_stego.embed_text(image, text + "a", key=KEY, salt=SALT)

    def test_capacity_holds_for_any_key_and_salt(self):
        image = gray_image(64, 32)  # 上限 26 字节
        cap = keyed_stego.capacity_for_keyed(image)
        rng = random.Random(2026)
        pairs = [(f"key-{i}-中文", bytes(rng.randrange(256) for _ in range(16))) for i in range(60)]
        pairs += [("a", bytes(16)), ("🔑" * 40, SALT2)]
        for key, salt in pairs:
            carrier = keyed_stego.embed_text(image, "a" * cap.max_payload_bytes, key=key, salt=salt)
            self.assertEqual(keyed_stego.extract_text(carrier, key=key).payload, b"a" * 26, key)

    def test_small_images_rejected(self):
        for image in (gray_image(4, 2), gray_image(4, 4), gray_image(16, 8)):
            with self.subTest(carrier=image.carrier_count), self.assertRaises(CapacityError):
                keyed_stego.embed_text(image, "", key=KEY, salt=SALT)
        with self.assertRaises(CapacityError):  # 上限 2 字节
            keyed_stego.embed_text(gray_image(32, 16), "abc", key=KEY, salt=SALT)
        for operation in (keyed_stego.extract_text, keyed_stego.payload_positions):
            with self.assertRaises(InvalidPayloadError):
                operation(gray_image(16, 8), key=KEY)


class ParameterTests(unittest.TestCase):
    def test_invalid_key_raises_value_error(self):
        carrier = keyed_stego.embed_text(gray_image(64, 32), "秘密", key=KEY, salt=SALT)
        for bad in ("", None, b"key", 123):
            with self.subTest(key=bad):
                with self.assertRaises(ValueError):
                    keyed_stego.embed_text(gray_image(64, 32), "x", key=bad)
                with self.assertRaises(ValueError):
                    keyed_stego.extract_text(carrier, key=bad)
                with self.assertRaises(ValueError):
                    keyed_stego.payload_positions(carrier, key=bad)
        self.assertNotIsInstance(ValueError(), LabError)  # 参数错误不是业务错误

    def test_invalid_salt_and_text_raise_value_error(self):
        image = gray_image(64, 32)
        for bad in (SALT[:-1], SALT + b"\x00", "0123456789abcdef", 16):
            with self.subTest(salt=bad), self.assertRaises(ValueError):
                keyed_stego.embed_text(image, "x", key=KEY, salt=bad)
        for bad in (b"bytes", None, 123):
            with self.subTest(text=bad), self.assertRaises(ValueError):
                keyed_stego.embed_text(image, bad, key=KEY, salt=SALT)
        with self.assertRaises(ValueError):  # 孤立代理码无法按 UTF-8 编码
            keyed_stego.embed_text(image, "\ud800", key=KEY, salt=SALT)
        with self.assertRaises(ValueError):  # 参数错误先于容量错误
            keyed_stego.embed_text(gray_image(4, 4), "", key="", salt=SALT)

    def test_bytearray_and_memoryview_salt_accepted(self):
        image = gray_image(64, 32)
        expected = keyed_stego.embed_text(image, "x", key=KEY, salt=SALT).raw_bytes
        for salt in (bytearray(SALT), memoryview(SALT)):
            with self.subTest(salt=type(salt).__name__):
                self.assertEqual(keyed_stego.embed_text(image, "x", key=KEY, salt=salt).raw_bytes,
                                 expected)


class PositionTests(unittest.TestCase):
    def test_position_rules(self):
        for source in (gray_image(64, 32), color_image(64, 32, top_down=True), gray_image(256, 64)):
            cap = keyed_stego.capacity_for_keyed(source)
            for length in (0, 1, 2, 7, 8, cap.max_payload_bytes):
                with self.subTest(carrier=cap.carrier_bits, length=length):
                    carrier = keyed_stego.embed_text(source, "a" * length, key=KEY, salt=SALT)
                    positions = list(keyed_stego.payload_positions(carrier, key=KEY))
                    self.assertIsInstance(keyed_stego.payload_positions(carrier, key=KEY), tuple)
                    check_positions(self, positions, cap.carrier_bits)
                    self.assertEqual(len(positions), length * 8)
                    if length >= 2:
                        self.assertTrue(any(b - a > 1 for a, b in zip(positions, positions[1:])),
                                        "没有任何跳过位置，不是随机间隔")

    def test_positions_depend_on_key_and_salt(self):
        base = keyed_stego.payload_positions(
            keyed_stego.embed_text(gray_image(64, 32), "x" * 26, key=KEY, salt=SALT), key=KEY)
        self.assertEqual(len(base), 208)
        other_salt = keyed_stego.embed_text(gray_image(64, 32), "x" * 26, key=KEY, salt=SALT2)
        self.assertNotEqual(keyed_stego.payload_positions(other_salt, key=KEY), base)
        self.assertNotEqual(keyed_stego.payload_positions(other_salt, key=KEY + " "), base)
        short = keyed_stego.payload_positions(
            keyed_stego.embed_text(gray_image(64, 32), "x" * 13, key=KEY, salt=SALT), key=KEY)
        self.assertEqual(base[:len(short)], short)  # 位置只由 key、salt 和位序号决定

    def test_positions_carry_payload_bits_and_only_those_change(self):
        for source in (gray_image(64, 32), color_image(64, 32)):
            text = "位置 Position 😀"
            carrier = keyed_stego.embed_text(source, text, key=KEY, salt=SALT)
            positions = list(keyed_stego.payload_positions(carrier, key=KEY))
            self.assertEqual(read_lsbs(carrier, positions), bits_of(text.encode("utf-8")))
            offsets = list(bmp.iter_carrier_offsets(source))
            used = set(range(360)) | set(positions)
            changed = {i for i, (a, b) in enumerate(zip(source.raw_bytes, carrier.raw_bytes)) if a != b}
            self.assertTrue(changed <= {offsets[i] for i in used})  # 其余字节逐字节不变
            self.assertTrue(all((a ^ b) <= 1 for a, b in zip(source.raw_bytes, carrier.raw_bytes)))
            for logical, bit in zip(positions, bits_of(text.encode("utf-8"))):
                self.assertEqual(str(carrier.raw_bytes[offsets[logical]] & 1), bit)

    def test_offset_distribution_near_uniform(self):
        # 256×256 灰度可承载 8144 个正文位，组内偏移 0～7 各应约占 1018 个
        carrier = keyed_stego.embed_text(gray_image(256, 256), "a" * 1018, key=KEY, salt=SALT)
        positions = keyed_stego.payload_positions(carrier, key=KEY)
        self.assertEqual(len(positions), 8144)
        self.assertLessEqual(positions[-1], 360 + 8 * 8144 - 1)
        counts = [0] * 8
        gaps = set()
        for before, after in zip(positions, positions[1:]):
            gaps.add(after - before)
        for position in positions:
            counts[(position - 360) % 8] += 1
        self.assertTrue(all(abs(count - 1018) < 150 for count in counts), counts)
        self.assertEqual(sorted(gaps), list(range(1, 16)))  # 最小间隔 1、最大间隔 15 均出现

    def test_positions_ignore_visual_direction(self):
        pixels = bytes((i * 7 + 3) & 0xFF for i in range(64 * 32))
        bottom_up = keyed_stego.embed_text(gray_image(64, 32, pixels), "方向", key=KEY, salt=SALT)
        top_down = keyed_stego.embed_text(gray_image(64, 32, pixels, top_down=True), "方向",
                                          key=KEY, salt=SALT)
        self.assertEqual(keyed_stego.payload_positions(bottom_up, key=KEY),
                         keyed_stego.payload_positions(top_down, key=KEY))
        self.assertNotEqual(bottom_up.raw_bytes, top_down.raw_bytes)  # 相同逻辑位置，不同文件字节
        self.assertEqual(keyed_stego.extract_text(top_down, key=KEY).text, "方向")

    def test_payload_positions_does_not_verify_body(self):
        carrier = keyed_stego.embed_text(gray_image(64, 32), "abcdef", key=KEY, salt=SALT)
        positions = keyed_stego.payload_positions(carrier, key=KEY)
        offsets = list(bmp.iter_carrier_offsets(carrier))
        for logical in positions[::8]:  # 依次破坏每个正文的首位
            with self.subTest(logical=logical):
                damaged = replace(carrier, raw_bytes=bytes(flip_lsb(carrier.raw_bytes, offsets[logical])))
                self.assertEqual(keyed_stego.payload_positions(damaged, key=KEY), positions)
                with self.assertRaises(InvalidPayloadError):  # 完整提取负责发现损坏
                    keyed_stego.extract_text(damaged, key=KEY)

    def test_payload_positions_cannot_prove_key(self):
        # 位置由 key 和帧内盐决定：错误密钥同样返回一组"合法"位置，不会报错
        carrier = keyed_stego.embed_text(gray_image(64, 32), "x" * 26, key=KEY, salt=SALT)
        wrong = keyed_stego.payload_positions(carrier, key="another key")
        check_positions(self, wrong, carrier.carrier_count)
        self.assertNotEqual(wrong, keyed_stego.payload_positions(carrier, key=KEY))

    def test_payload_positions_rejects_foreign_or_oversized_frames(self):
        source = gray_image(64, 32)
        for foreign in (source, stego.embed_text(source, "v1 message")):
            with self.assertRaises(InvalidPayloadError):
                keyed_stego.payload_positions(foreign, key=KEY)
        carrier = keyed_stego.embed_text(source, "a" * 8, key=KEY, salt=SALT)  # 该图上限 26 字节
        offsets = list(bmp.iter_carrier_offsets(carrier))
        oversized = replace(carrier, raw_bytes=bytes(flip_lsb(carrier.raw_bytes, offsets[21 * 8])))
        for operation in (keyed_stego.payload_positions, keyed_stego.extract_text):
            with self.assertRaises(InvalidPayloadError):  # 声明长度 128 超过容量，读正文前拒绝
                operation(oversized, key=KEY)
        self.assertIsInstance(InvalidPayloadError("x"), LabError)


class CorruptionTests(unittest.TestCase):
    def test_any_single_bootstrap_bit_flip_fails(self):
        carrier = keyed_stego.embed_text(gray_image(64, 32), "bootstrap", key=KEY, salt=SALT)
        offsets = list(bmp.iter_carrier_offsets(carrier))
        self.assertEqual(keyed_stego.extract_text(carrier, key=KEY).text, "bootstrap")
        for logical in range(360):  # 标记、版本、盐、长度、CRC、标签的每一位
            with self.subTest(logical=logical):
                damaged = replace(carrier, raw_bytes=bytes(flip_lsb(carrier.raw_bytes, offsets[logical])))
                with self.assertRaises(InvalidPayloadError):
                    keyed_stego.extract_text(damaged, key=KEY)

    def test_any_single_body_bit_flip_fails(self):
        for source in (gray_image(64, 32), color_image(64, 32)):
            carrier = keyed_stego.embed_text(source, "0123456789", key=KEY, salt=SALT)
            offsets = list(bmp.iter_carrier_offsets(carrier))
            for logical in keyed_stego.payload_positions(carrier, key=KEY):
                with self.subTest(fmt=source.pixel_format.name, logical=logical):
                    damaged = replace(carrier, raw_bytes=bytes(flip_lsb(carrier.raw_bytes, offsets[logical])))
                    with self.assertRaises(InvalidPayloadError):
                        keyed_stego.extract_text(damaged, key=KEY)

    def test_damage_outside_frame_or_above_lsb_is_tolerated(self):
        source = gray_image(64, 32)
        carrier = keyed_stego.embed_text(source, "unchanged", key=KEY, salt=SALT)
        offsets = list(bmp.iter_carrier_offsets(carrier))
        used = set(range(360)) | set(keyed_stego.payload_positions(carrier, key=KEY))
        skipped = [offsets[i] for i in range(360, carrier.carrier_count) if i not in used]
        self.assertTrue(skipped)  # bootstrap 之后确有被跳过的通道
        data = bytearray(carrier.raw_bytes)
        for offset in skipped:
            data[offset] ^= 0x01  # 改写被跳过通道的 LSB 不影响提取
        self.assertEqual(keyed_stego.extract_text(replace(carrier, raw_bytes=bytes(data)), key=KEY).text,
                         "unchanged")
        data = bytearray(carrier.raw_bytes)
        for logical in sorted(used):
            data[offsets[logical]] ^= 0x02  # 占用字节的次低位不是载体位
        self.assertEqual(keyed_stego.extract_text(replace(carrier, raw_bytes=bytes(data)), key=KEY).text,
                         "unchanged")


class InteropTests(unittest.TestCase):
    def test_v1_and_keyed_frames_are_mutually_unreadable(self):
        source = gray_image(64, 32)
        keyed_carrier = keyed_stego.embed_text(source, "message", key=KEY, salt=SALT)
        v1_carrier = stego.embed_text(source, "message")
        with self.assertRaises(InvalidPayloadError):
            stego.extract_text(keyed_carrier)
        with self.assertRaises(InvalidPayloadError):
            keyed_stego.extract_text(v1_carrier, key=KEY)
        self.assertEqual(stego.extract_text(v1_carrier).text, "message")  # v1 行为未变

    def test_protocol_constants(self):
        self.assertEqual(keyed_stego.MAGIC, b"KLS1")
        self.assertEqual(keyed_stego.VERSION, 1)
        self.assertEqual(keyed_stego.BOOTSTRAP_BYTES, 45)
        self.assertEqual(keyed_stego.BOOTSTRAP_CHANNELS, 360)
        self.assertEqual(keyed_stego.GROUP_SIZE, 8)
        self.assertNotEqual(keyed_stego.MAGIC, b"LSB1")


if __name__ == "__main__":
    unittest.main()
