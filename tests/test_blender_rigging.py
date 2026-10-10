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
    assert "exec(" not in rigging._RIG_SCRIPT
