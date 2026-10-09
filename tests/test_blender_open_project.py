from __future__ import annotations

from local_agent import blender_workflow as workflow


def test_open_project_requires_local_configuration(monkeypatch):
    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    assert workflow.open_mia_project("mia")["status"] == "blocked"


def test_open_project_requires_existing_project(monkeypatch, tmp_path):
    exe = tmp_path / "blender.exe"
    exe.write_text("placeholder")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(exe))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    result = workflow.open_mia_project("mia")
    assert result["status"] == "blocked"
    assert result["reason"] == "valid_mia_blockout_project_not_found"


def test_open_project_launches_only_validated_local_blend(monkeypatch, tmp_path):
    exe = tmp_path / "blender.exe"
    exe.write_text("placeholder")
    workspace = tmp_path / "workspace"
    project = workspace / "mia"
    project.mkdir(parents=True)
    blend = project / "mia_blockout.blend"
    blend.write_bytes(b"blend placeholder")
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(exe))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    calls = []
    class Process:
        pid = 1234
    monkeypatch.setattr(workflow.subprocess, "Popen", lambda command, **kwargs: (calls.append((command, kwargs)) or Process()))
    result = workflow.open_mia_project("mia")
    assert result["status"] == "started"
    assert calls[0][0] == [str(exe.resolve()), str(blend)]
    assert calls[0][1]["shell"] is False
