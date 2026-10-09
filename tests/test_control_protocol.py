from __future__ import annotations

import json

import pytest

from local_agent.control_protocol import ProtocolError, parse_task


def _task(operation: str, arguments: dict) -> str:
    return json.dumps({
        "protocol_version": 1,
        "task_id": "forest-001",
        "operation": operation,
        "created_at": "2026-10-09T10:00:00Z",
        "expires_at": "2026-10-09T10:05:00Z",
        "requires_local_approval": True,
        "arguments": arguments,
    })


def test_accepts_typed_blender_forest_preview_task():
    task = parse_task(_task("blender_forest_preview", {
        "project_name": "mia_forest",
        "render": True,
        "preview": True,
        "cycles": False,
    }))
    assert task.operation == "blender_forest_preview"
    assert task.arguments["project_name"] == "mia_forest"


@pytest.mark.parametrize("arguments", [
    {"project_name": "../outside"},
    {"project_name": "mia forest"},
    {"project_name": "mia", "script": "import os; os.remove('x')"},
    {"project_name": "mia", "cycles": "yes"},
    {"project_name": "mia", "executable": "C:\\Windows\\System32\\cmd.exe"},
    {"render": True},
])
def test_rejects_unsafe_blender_task_arguments(arguments):
    with pytest.raises(ProtocolError):
        parse_task(_task("blender_forest_preview", arguments))


def test_still_requires_local_approval_for_blender_task():
    value = json.loads(_task("blender_forest_preview", {"project_name": "mia"}))
    value["requires_local_approval"] = False
    with pytest.raises(ProtocolError, match="require local approval"):
        parse_task(json.dumps(value))
