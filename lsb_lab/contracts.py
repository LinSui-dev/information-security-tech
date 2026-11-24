from dataclasses import dataclass
import zlib

FRAME_HEADER_SIZE = 13
MAGIC = b"LSBv1"

@dataclass(frozen=True)
class StegoFrame:
    payload_len: int
    crc32: int
    payload: bytes

    @staticmethod
    def pack(text: str) -> bytes:
        payload = text.encode("utf-8")
        payload_len = len(payload)
        crc_val = zlib.crc32(payload) & 0xFFFFFFFF
        header = payload_len.to_bytes(4, "little") + crc_val.to_bytes(4, "little") + MAGIC
        return header + payload

    @staticmethod
    def unpack(raw: bytes) -> "StegoFrame":
        if len(raw) < FRAME_HEADER_SIZE:
            raise ValueError("frame too short")
        header = raw[:FRAME_HEADER_SIZE]
        payload_len = int.from_bytes(header[0:4], "little")
        crc_stored = int.from_bytes(header[4:8], "little")
        magic = header[8:13]
        if magic != MAGIC:
            raise ValueError("invalid magic header, not LSBv1 frame")
        if len(raw) < FRAME_HEADER_SIZE + payload_len:
            raise ValueError("payload truncated")
        payload = raw[FRAME_HEADER_SIZE: FRAME_HEADER_SIZE + payload_len]
        crc_calc = zlib.crc32(payload) & 0xFFFFFFFF
        if crc_calc != crc_stored:
            raise ValueError("crc32 check failed")
        return StegoFrame(payload_len, crc_stored, payload)
