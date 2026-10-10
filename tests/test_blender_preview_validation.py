from __future__ import annotations

import json
import struct
import zlib

from local_agent import blender_workflow as workflow


def test_discover_blender_reports_missing_executable(monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(tmp_path / "missing-blender.exe"))
    monkeypatch.setattr(workflow.shutil, "which", lambda name: None)
    result = workflow.discover_blender()
    assert result["status"] == "needs_setup"
    assert result["available"] is False


def test_discover_blender_queries_version(monkeypatch, tmp_path):
    exe = tmp_path / "blender.exe"
    exe.write_text("placeholder")
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(exe))
    class Result:
        returncode = 0
        stdout = "Blender 4.5.0\n"
        stderr = ""
    monkeypatch.setattr(workflow.subprocess, "run", lambda *a, **k: Result())
    result = workflow.discover_blender()
    assert result["status"] == "ready"
    assert result["version"] == "Blender 4.5.0"


def test_blockout_requires_local_configuration(monkeypatch):
    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    result = workflow.create_mia_blockout("mia")
    assert result["status"] == "blocked"


def test_blockout_rejects_traversal_name(monkeypatch):
    import pytest
    with pytest.raises(workflow.BlenderWorkflowError):
        workflow.create_mia_blockout("../outside")


def test_blockout_does_not_overwrite_existing_outputs(monkeypatch, tmp_path):
    exe = tmp_path / "blender.exe"; exe.write_text("placeholder")
    workspace = tmp_path / "workspace"; workspace.mkdir()
    project = workspace / "mia"; project.mkdir()
    original = project / "mia_blockout.blend"; original.write_bytes(b"important")
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(exe))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    result = workflow.create_mia_blockout("mia")
    assert result["status"] == "blocked"
    assert original.read_bytes() == b"important"



def _write_png(path, width=360, height=640):
    def chunk(kind, payload):
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = zlib.compress(b"\x00\x00\x00\x00")
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
