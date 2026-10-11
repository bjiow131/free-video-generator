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


def configured_project(monkeypatch, tmp_path):
    exe = tmp_path / "blender.exe"
    exe.write_bytes(b"placeholder")
    project = tmp_path / "workspace" / "mia"
    project.mkdir(parents=True)
    (project / "mia_blockout.blend").write_bytes(b"original")
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(exe))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(project.parent))
    return project


def test_inspection_does_not_reuse_stale_success(monkeypatch, tmp_path):
    from types import SimpleNamespace
    project = configured_project(monkeypatch, tmp_path)
    report = project / "mia_inspection.json"
    old = json.dumps({"status": "completed", "blend_path": str(project / "mia_blockout.blend")})
    report.write_text(old)
    monkeypatch.setattr(workflow.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr=""))
    assert workflow.inspect_mia_project("mia")["status"] == "failed"
    assert report.read_text() == old


def test_inspection_publishes_only_fresh_valid_report(monkeypatch, tmp_path):
    from pathlib import Path
    from types import SimpleNamespace
    project = configured_project(monkeypatch, tmp_path)
    def run(command, **kwargs):
        assert command.index("--python-exit-code") < command.index("--python")
        source, report = command[command.index("--") + 1:]
        Path(report).write_text(json.dumps({"status": "completed", "blend_path": source}))
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(workflow.subprocess, "run", run)
    assert workflow.inspect_mia_project("mia")["status"] == "completed"
    assert json.loads((project / "mia_inspection.json").read_text())["status"] == "completed"


def test_workflows_reject_internal_project_alias(monkeypatch, tmp_path):
    import pytest
    project = configured_project(monkeypatch, tmp_path)
    try:
        (project.parent / "alias").symlink_to(project, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink privilege unavailable")
    for operation in (workflow.create_mia_blockout, workflow.open_mia_project, workflow.inspect_mia_project):
        with pytest.raises(workflow.BlenderWorkflowError, match="symlink|real folder"):
            operation("alias")


def test_blockout_rejects_log_symlink_before_launch(monkeypatch, tmp_path):
    import pytest
    project = configured_project(monkeypatch, tmp_path)
    (project / "mia_blockout.blend").unlink()
    protected = tmp_path / "protected.txt"
    protected.write_text("keep")
    try:
        (project / "blender_stdout.log").symlink_to(protected)
    except OSError:
        pytest.skip("Symlink privilege unavailable")
    monkeypatch.setattr(workflow.subprocess, "run", lambda *a, **k: pytest.fail("Must reject before launch"))
    with pytest.raises(workflow.BlenderWorkflowError, match="symlink"):
        workflow.create_mia_blockout("mia")
    assert protected.read_text() == "keep"


def test_failed_blockout_overwrite_preserves_prior_project(monkeypatch, tmp_path):
    from types import SimpleNamespace
    project = configured_project(monkeypatch, tmp_path)
    old = {"mia_blockout.blend": b"original", "mia_blockout.png": b"original preview", "blender_result.json": b"original report"}
    for name, value in old.items():
        (project / name).write_bytes(value)
    def run(*args, **kwargs):
        (project / "mia_blockout.blend").write_bytes(b"partial new output")
        return SimpleNamespace(returncode=1, stdout="", stderr="render failed")
    monkeypatch.setattr(workflow.subprocess, "run", run)
    assert workflow.create_mia_blockout("mia", overwrite=True)["status"] == "failed"
    for name, value in old.items():
        assert (project / name).read_bytes() == value


def test_windows_reparse_point_detection_without_path_is_junction():
    import stat
    from types import SimpleNamespace
    from local_agent.path_names import is_link_or_junction
    path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT))
    assert is_link_or_junction(path)


def test_windows_internal_junction_rejected(monkeypatch, tmp_path):
    import os
    import subprocess
    import pytest
    if os.name != "nt":
        pytest.skip("Windows junction acceptance test")
    project = configured_project(monkeypatch, tmp_path)
    alias = project.parent / "alias"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(project)], check=True, capture_output=True)
    try:
        with pytest.raises(workflow.BlenderWorkflowError, match="junction"):
            workflow.open_mia_project("alias")
    finally:
        alias.rmdir()
