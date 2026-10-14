from __future__ import annotations

import json
import struct

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
