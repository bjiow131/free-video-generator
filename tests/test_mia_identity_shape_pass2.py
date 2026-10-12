"""Fixed second-pass edits operate on volumetric Mia mesh, never on video."""
from __future__ import annotations
import ast
import json
import pytest
from local_agent.control_protocol import parse_task, ProtocolError
from local_agent.blender_workflow import (
    create_mia_identity_shape_pass_two, _mia_identity_shape_pass_two_script,
)


def manifest(arguments=None):
    return json.dumps({
        "protocol_version": 1,
        "task_id": "mia-pass-two-01",
        "operation": "mia_identity_pass_two",
        "created_at": "2026-10-13T01:00:00+00:00",
        "expires_at": "2026-10-13T01:25:00+00:00",
        "requires_local_approval": True,
        "arguments": {} if arguments is None else arguments,
    })


def test_only_fixed_operation_without_external_commands():
    assert parse_task(manifest()).operation == "mia_identity_pass_two"
    for bad in ({"script": "evil"}, {"path": "../somewhere"},
                {"prompt": "make a new girl"}, {"duration": 5}):
        with pytest.raises(ProtocolError):
            parse_task(manifest(bad))


def test_real_mesh_edits_and_all_static_views_are_bundled():
    script = _mia_identity_shape_pass_two_script()
    ast.parse(script)
    assert "eye_mesh_groups" in script
    assert "jaw_vertices" in script
    assert "side_fringe_mesh_groups" in script
    assert "v.co.x" in script and "v.co.z" in script
    assert 'bpy.ops.wm.save_as_mainfile(filepath=blend)' in script
    assert 'for name, location in views' in script
    assert "bpy.ops.render.render(write_still=True)" in script
    assert "animation" not in script.lower()
    assert "mp4" not in script.lower()


def test_does_not_launch_without_proven_parent_checkpoint(monkeypatch, tmp_path):
    from local_agent import blender_workflow as workflow
    executable = tmp_path / "blender.exe"
    executable.write_text("fake")
    monkeypatch.setattr(workflow, "find_blender_executable", lambda: executable)
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(tmp_path))
    result = create_mia_identity_shape_pass_two(task_id="mia-shape-test")
    assert result["status"] == "blocked"
    assert not (tmp_path / "MIA_REFERENCE_REVIEW" / "mia-shape-test").exists()


def test_reject_unsafe_task_identifier(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(tmp_path))
    assert create_mia_identity_shape_pass_two(task_id="../unsafe")["reason"] == "invalid_review_identifier"
