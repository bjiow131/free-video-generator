from __future__ import annotations

import struct
import zlib

from local_agent import blender_workflow as workflow


def _write_png(path, width=360, height=640):
    def chunk(kind, payload):
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = zlib.compress((b"\x00" + b"\x00" * (width * 3)) * height)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", data) + chunk(b"IEND", b""))


def test_png_validator_accepts_complete_png_chunks(tmp_path):
    path = tmp_path / "preview.png"
    _write_png(path)
    ok, reason, dimensions = workflow._validate_png(path, (360, 640))
    assert ok is True
    assert reason == "ok"
    assert dimensions == [360, 640]


def test_png_validator_rejects_corrupt_chunk_crc(tmp_path):
    path = tmp_path / "preview.png"
    _write_png(path)
    payload = bytearray(path.read_bytes())
    payload[29] ^= 0x01
    path.write_bytes(payload)
    ok, reason, _ = workflow._validate_png(path, (360, 640))
    assert ok is False
    assert reason == "png_chunk_crc_mismatch"


def test_png_validator_rejects_truncated_png(tmp_path):
    path = tmp_path / "preview.png"
    _write_png(path)
    path.write_bytes(path.read_bytes()[:-5])
    ok, reason, _ = workflow._validate_png(path, (360, 640))
    assert ok is False
    assert reason == "png_chunk_truncated"


def test_png_validator_rejects_wrong_dimensions(tmp_path):
    path = tmp_path / "preview.png"
    _write_png(path, width=720, height=1280)
    ok, reason, dimensions = workflow._validate_png(path, (360, 640))
    assert ok is False
    assert reason == "png_dimensions_mismatch"
    assert dimensions == [720, 1280]
