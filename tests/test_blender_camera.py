from __future__ import annotations

import json
import pytest

from local_agent.blender_camera import PRESETS, MOVES, control_camera
from local_agent.control_protocol import ProtocolError, parse_task


def task(args):
    return json.dumps({
        "protocol_version": 1,
        "task_id": "camera-test-001",
        "operation": "blender_camera_control",
        "created_at": "2026-10-10T10:00:00Z",
        "expires_at": "2026-10-10T10:05:00Z",
        "requires_local_approval": True,
        "arguments": args,
    })


@pytest.mark.parametrize("preset", sorted(PRESETS))
@pytest.mark.parametrize("move", sorted(MOVES))
def test_camera_task_accepts_only_typed_preset_and_move(preset, move):
    parsed = parse_task(task({"project_name": "MiaProject", "preset": preset, "move": move}))
    assert parsed.operation == "blender_camera_control"


@pytest.mark.parametrize("args", [
    {"project_name": "../escape", "preset": "medium_shot"},
    {"project_name": "Mia", "preset": "execute_python"},
    {"project_name": "Mia", "preset": "medium_shot", "move": "arbitrary"},
    {"project_name": "Mia", "preset": "medium_shot", "frames": True},
    {"project_name": "Mia", "preset": "medium_shot", "frames": 241},
    {"project_name": "Mia", "preset": "medium_shot", "script": "import os"},
    {"project_name": "Mia", "preset": "medium_shot", "create_camera_if_missing": "yes"},
])
def test_camera_task_rejects_unsafe_or_invalid_arguments(args):
    with pytest.raises(ProtocolError):
        parse_task(task(args))


def test_camera_adapter_blocks_when_local_blender_configuration_is_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    result = control_camera("MiaProject", preset="medium_shot")
    assert result == {
        "status": "blocked",
        "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally",
    }


def test_camera_adapter_rejects_invalid_preset_before_running_blender():
    with pytest.raises(ValueError, match="Unsupported camera preset"):
        control_camera("MiaProject", preset="unknown")
