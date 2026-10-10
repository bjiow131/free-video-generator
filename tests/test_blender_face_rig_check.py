from __future__ import annotations

from pathlib import Path
import pytest

from local_agent import blender_face_rig_check as audit


def test_requires_local_blender_configuration(monkeypatch):
    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    assert audit.check_face_rig("mia") == {
        "status": "blocked",
        "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally",
    }


def test_rejects_invalid_project_name():
    with pytest.raises(ValueError):
        audit.check_face_rig("../outside")


def test_reports_ambiguous_blend_files_without_running_blender(monkeypatch, tmp_path: Path):
    project = tmp_path / "mia"
    project.mkdir()
    (project / "a.blend").write_bytes(b"blend")
    (project / "b.blend").write_bytes(b"blend")
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(tmp_path / "blender.exe"))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(Path, "is_file", lambda self: self.name == "blender.exe" or (self.exists() and not self.is_dir()))
    result = audit.check_face_rig("mia")
    assert result["status"] == "blocked"
    assert result["reason"] == "source_blend_missing_or_ambiguous"
    assert result["candidates"] == ["a.blend", "b.blend"]


def test_refuses_to_overwrite_report(monkeypatch, tmp_path: Path):
    project = tmp_path / "mia"
    project.mkdir()
    (project / "mia_blockout.blend").write_bytes(b"blend")
    (project / "face_rig_check_result.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(tmp_path / "blender.exe"))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(Path, "is_file", lambda self: self.name in {"blender.exe", "mia_blockout.blend"})
    result = audit.check_face_rig("mia")
    assert result["status"] == "blocked"
    assert result["reason"] == "report_exists_refusing_to_overwrite"
