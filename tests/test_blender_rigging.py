from __future__ import annotations

import json

from local_agent import blender_rigging as rigging


def test_skeleton_requires_local_configuration(monkeypatch):
    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    result = rigging.create_mia_skeleton("mia")
    assert result["status"] == "blocked"


def test_skeleton_rejects_traversal_name():
    result = rigging.create_mia_skeleton("../outside")
    assert result == {"status": "rejected", "reason": "invalid_project_name"}


def test_skeleton_requires_existing_blockout(monkeypatch, tmp_path):
    blender = tmp_path / "blender.exe"
    blender.write_text("placeholder")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project = workspace / "mia"
    project.mkdir()
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(blender))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    result = rigging.create_mia_skeleton("mia")
    assert result["status"] == "blocked"
    assert result["reason"] == "mia_blockout_project_not_found"


def test_skeleton_does_not_overwrite_existing_output(monkeypatch, tmp_path):
    blender = tmp_path / "blender.exe"
    blender.write_text("placeholder")
    workspace = tmp_path / "workspace"
    project = workspace / "mia"
    project.mkdir(parents=True)
    (project / "mia_blockout.blend").write_bytes(b"blockout")
    (project / "mia_skeleton.blend").write_bytes(b"keep")
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(blender))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    result = rigging.create_mia_skeleton("mia")
    assert result["status"] == "blocked"
    assert result["reason"] == "skeleton_outputs_exist_no_overwrite"
    assert (project / "mia_skeleton.blend").read_bytes() == b"keep"


def test_skeleton_script_is_fixed_and_declares_unbound_meshes():
    assert "bpy.ops.wm.open_mainfile" in rigging._RIG_SCRIPT
    assert "pose_smoke_test" in rigging._RIG_SCRIPT
    assert "mesh_binding" in rigging._RIG_SCRIPT
    assert "rigid_per_part_weights" in rigging._RIG_SCRIPT
    assert "vertex_groups.new" in rigging._RIG_SCRIPT
    assert "bound_object_count" in rigging._RIG_SCRIPT
    assert "exec(" not in rigging._RIG_SCRIPT



def test_skeleton_workflow_validates_report_and_keeps_source(monkeypatch, tmp_path):
    blender = tmp_path / "blender.exe"
    blender.write_text("placeholder")
    workspace = tmp_path / "workspace"
    project = workspace / "mia"
    project.mkdir(parents=True)
    source = project / "mia_blockout.blend"
    source.write_bytes(b"original blockout")
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(blender))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))

    def fake_run(command, **kwargs):
        assert command[0] == str(blender.resolve())
        assert "--disable-autoexec" in command
        assert kwargs["shell"] is False
        marker = command.index("--")
        source_arg, output_arg, report_arg = map(__import__("pathlib").Path, command[marker + 1:])
        assert source_arg == source
        __import__("pathlib").Path(output_arg).write_bytes(b"rigged project")
        __import__("pathlib").Path(report_arg).write_text(json.dumps({
            "status": "completed",
            "stage": "rigged_proxy_smoke_test",
            "bone_count": 13,
            "pose_smoke_test": "passed_and_reset",
            "bound_object_count": 12,
            "unbound_objects": [],
        }), encoding="utf-8")
        class Result:
            returncode = 0
            stderr = ""
        return Result()

    monkeypatch.setattr(rigging.subprocess, "run", fake_run)
    result = rigging.create_mia_skeleton("mia")
    assert result["status"] == "completed"
    assert result["bone_count"] == 13
    assert result["mesh_binding"] == "rigid_per_part_weights"
    assert source.read_bytes() == b"original blockout"
