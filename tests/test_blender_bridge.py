from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_agent.blender_bridge import BlenderBridge, BlenderBridgeError


def _bridge(tmp_path: Path, fake_run):
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"test executable placeholder")
    workspace = tmp_path / "workspace"
    return BlenderBridge(executable, workspace, popen=fake_run), workspace


def test_rejects_unknown_task_without_launching(tmp_path: Path) -> None:
    calls = []
    bridge, _ = _bridge(tmp_path, lambda *a, **k: calls.append(a))
    with pytest.raises(BlenderBridgeError, match="Unsupported Blender task"):
        bridge.run_task("execute_arbitrary_python", project_name="mia")
    assert calls == []


@pytest.mark.parametrize("name", ["../escape", "..", "has spaces", "a/b", ""])
def test_rejects_unsafe_project_names(tmp_path: Path, name: str) -> None:
    calls = []
    bridge, _ = _bridge(tmp_path, lambda *a, **k: calls.append(a))
    with pytest.raises(BlenderBridgeError, match="Project name"):
        bridge.run_task("forest_preview", project_name=name)
    assert calls == []


def test_runs_only_fixed_blender_script_and_validates_outputs(tmp_path: Path) -> None:
    def fake_run(command, **kwargs):
        assert command[1:3] == ["--background", "--factory-startup"]
        assert command[3] == "--python"
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is False
        project_dir = Path(kwargs["cwd"])
        (project_dir / "forest_starter.blend").write_bytes(b"blend placeholder")
        (project_dir / "forest_preview.png").write_bytes(b"png placeholder")
        (project_dir / "blender_result.json").write_text(json.dumps({
            "status": "completed",
            "blend_path": str(project_dir / "forest_starter.blend"),
            "preview_path": str(project_dir / "forest_preview.png"),
            "engine": "BLENDER_EEVEE_NEXT",
            "resolution": [720, 1280],
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    bridge, workspace = _bridge(tmp_path, fake_run)
    result = bridge.run_task("forest_preview", project_name="mia_forest")
    assert result["status"] == "completed"
    assert result["resolution"] == [720, 1280]
    assert (workspace / "mia_forest" / "forest_starter.blend").is_file()


def test_missing_preview_is_reported(tmp_path: Path) -> None:
    def fake_run(command, **kwargs):
        project_dir = Path(kwargs["cwd"])
        (project_dir / "forest_starter.blend").write_bytes(b"blend placeholder")
        (project_dir / "blender_result.json").write_text(json.dumps({
            "status": "completed",
            "blend_path": str(project_dir / "forest_starter.blend"),
            "preview_path": str(project_dir / "forest_preview.png"),
            "engine": "BLENDER_EEVEE_NEXT",
            "resolution": [720, 1280],
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    bridge, _ = _bridge(tmp_path, fake_run)
    with pytest.raises(BlenderBridgeError, match="preview render is missing"):
        bridge.run_task("forest_preview", project_name="forest")



def test_existing_outputs_are_not_overwritten_without_explicit_opt_in(tmp_path: Path) -> None:
    calls = []
    bridge, workspace = _bridge(tmp_path, lambda *a, **k: calls.append(a))
    project_dir = workspace / "mia"
    project_dir.mkdir(parents=True)
    original = project_dir / "forest_starter.blend"
    original.write_bytes(b"important existing project")
    with pytest.raises(BlenderBridgeError, match="already has generated outputs"):
        bridge.run_task("forest_preview", project_name="mia")
    assert original.read_bytes() == b"important existing project"
    assert calls == []
