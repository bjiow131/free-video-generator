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


def test_accepts_bounded_story_plan_task():
    task = parse_task(_task("save_story_plan", {
        "story_plan": {
            "schema_version": 1,
            "project_name": "mia_snail",
            "title": "Мия и улитка",
            "logline": "Мия помогает улитке.",
            "target_duration_seconds": 30,
            "language": "ru",
            "character_bible": {},
            "scenes": [{
                "scene_id": "scene_001",
                "title": "Лесная тропинка",
                "duration_seconds": 12,
                "location": "Лес",
                "action": "Мия замечает улитку.",
                "camera": "Крупный план",
                "dialogue": [],
                "assets": ["Mia_reference_model", "snail"]
            }]
        }
    }))
    assert task.operation == "save_story_plan"
    assert task.arguments["story_plan"]["project_name"] == "mia_snail"


def test_rejects_story_plan_with_unsafe_project_name():
    with pytest.raises(ProtocolError):
        parse_task(_task("save_story_plan", {"story_plan": {
            "schema_version": 1, "project_name": "../outside"
        }}))


def test_accepts_compile_story_plan_for_safe_project():
    task = parse_task(_task("compile_story_plan", {"project_name": "mia_snail"}))
    assert task.operation == "compile_story_plan"


@pytest.mark.parametrize("arguments", [
    {},
    {"project_name": "../outside"},
    {"project_name": "mia", "path": "C:\\\\private"},
])
def test_rejects_unsafe_compile_story_plan_arguments(arguments):
    with pytest.raises(ProtocolError):
        parse_task(_task("compile_story_plan", arguments))


def test_accepts_scan_project_assets_for_safe_project():
    task = parse_task(_task("scan_project_assets", {"project_name": "mia_snail"}))
    assert task.operation == "scan_project_assets"


@pytest.mark.parametrize("arguments", [{}, {"project_name": "../outside"}, {"project_name": "mia", "path": "C:\\\\private"}])
def test_rejects_unsafe_asset_scan_arguments(arguments):
    with pytest.raises(ProtocolError):
        parse_task(_task("scan_project_assets", arguments))

def test_accepts_argument_free_preflight_task():
    task = parse_task(_task("preflight", {}))
    assert task.operation == "preflight"


def test_rejects_preflight_arguments():
    with pytest.raises(ProtocolError, match="does not accept arguments"):
        parse_task(_task("preflight", {"executable": "blender.exe"}))
