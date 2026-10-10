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


def test_rejects_boolean_protocol_version():
    raw = _task("doctor", {})
    value = json.loads(raw)
    value["protocol_version"] = True
    with pytest.raises(ProtocolError, match="protocol version"):
        parse_task(json.dumps(value))


@pytest.mark.parametrize("created_at,expires_at", [
    ("2026-10-09T10:00:00", "2026-10-09T10:05:00Z"),
    ("not-a-time", "2026-10-09T10:05:00Z"),
    ("2026-10-09T10:05:00Z", "2026-10-09T10:00:00Z"),
    ("2026-10-09T10:00:00Z", "2026-10-10T11:00:00Z"),
])
def test_rejects_invalid_task_timestamp_windows(created_at, expires_at):
    value = json.loads(_task("doctor", {}))
    value["created_at"] = created_at
    value["expires_at"] = expires_at
    with pytest.raises(ProtocolError):
        parse_task(json.dumps(value))


def test_remote_approval_is_rejected_for_typed_blender_preview():
    value = json.loads(_task("blender_forest_preview", {"project_name": "mia"}))
    value["requires_local_approval"] = False
    with pytest.raises(ProtocolError, match="require local approval"):
        parse_task(json.dumps(value))

def test_remote_approval_rejected_for_patch_operation():
    value = json.loads(_task("apply_patch", {"patch": "diff --git a/a.txt b/a.txt\\n"}))
    value["requires_local_approval"] = False
    with pytest.raises(ProtocolError, match="require local approval"):
        parse_task(json.dumps(value))


def test_rejects_non_string_operation_without_uncaught_type_error():
    value = json.loads(_task("doctor", {}))
    value["operation"] = ["doctor"]
    with pytest.raises(ProtocolError, match="not allowlisted"):
        parse_task(json.dumps(value))


def test_rejects_unexpected_arguments_for_diagnostic_task():
    value = json.loads(_task("doctor", {}))
    value["arguments"] = {"project_name": "ignored"}
    with pytest.raises(ProtocolError, match="does not accept arguments"):
        parse_task(json.dumps(value))


def test_accepts_blender_knowledge_search():
    task = parse_task(_task("blender_knowledge_search", {"query": "риггинг кости", "limit": 5}))
    assert task.operation == "blender_knowledge_search"
    assert task.arguments["limit"] == 5


@pytest.mark.parametrize("arguments", [
    {},
    {"query": ""},
    {"query": "x" * 1001},
    {"query": "render", "limit": 0},
    {"query": "render", "limit": 11},
    {"query": "render", "limit": True},
    {"query": "render", "script": "print(1)"},
])
def test_rejects_invalid_blender_knowledge_search(arguments):
    with pytest.raises(ProtocolError):
        parse_task(_task("blender_knowledge_search", arguments))


def test_blender_knowledge_search_requires_local_approval():
    value = json.loads(_task("blender_knowledge_search", {"query": "render"}))
    value["requires_local_approval"] = False
    with pytest.raises(ProtocolError, match="require local approval"):
        parse_task(json.dumps(value))

def test_accepts_blender_preflight_task():
    task = parse_task(_task("blender_preflight", {}))
    assert task.operation == "blender_preflight"


def test_rejects_blender_preflight_arguments():
    with pytest.raises(ProtocolError):
        parse_task(_task("blender_preflight", {"unexpected": "value"}))


def test_accepts_blender_mia_blockout_task():
    task = parse_task(_task("blender_mia_blockout", {"project_name": "mia_character"}))
    assert task.operation == "blender_mia_blockout"


@pytest.mark.parametrize("arguments", [
    {},
    {"project_name": "../outside"},
    {"project_name": "mia", "script": "print(1)"},
])
def test_rejects_unsafe_blender_mia_blockout_arguments(arguments):
    with pytest.raises(ProtocolError):
        parse_task(_task("blender_mia_blockout", arguments))


def test_accepts_blender_open_mia_project_task():
    task = parse_task(_task("blender_open_mia_project", {"project_name": "mia_character"}))
    assert task.operation == "blender_open_mia_project"


@pytest.mark.parametrize("arguments", [
    {},
    {"project_name": "../outside"},
    {"project_name": "mia", "path": "outside.blend"},
])
def test_rejects_unsafe_blender_open_mia_project_arguments(arguments):
    with pytest.raises(ProtocolError):
        parse_task(_task("blender_open_mia_project", arguments))


def test_accepts_blender_inspect_mia_project_task():
    task = parse_task(_task("blender_inspect_mia_project", {"project_name": "mia_character"}))
    assert task.operation == "blender_inspect_mia_project"


@pytest.mark.parametrize("arguments", [{}, {"project_name": "../outside"}, {"project_name": "mia", "script": "print(1)"}])
def test_rejects_unsafe_blender_inspect_mia_project_arguments(arguments):
    with pytest.raises(ProtocolError):
        parse_task(_task("blender_inspect_mia_project", arguments))



def test_accepts_blender_mia_skeleton_task():
    task = parse_task(_task("blender_mia_skeleton", {"project_name": "mia_character"}))
    assert task.operation == "blender_mia_skeleton"


@pytest.mark.parametrize("arguments", [
    {},
    {"project_name": "../outside"},
    {"project_name": "mia", "script": "print(1)"},
])
def test_rejects_unsafe_blender_mia_skeleton_arguments(arguments):
    with pytest.raises(ProtocolError):
        parse_task(_task("blender_mia_skeleton", arguments))


def test_blender_mia_skeleton_requires_local_approval():
    value = json.loads(_task("blender_mia_skeleton", {"project_name": "mia_character"}))
    value["requires_local_approval"] = False
    with pytest.raises(ProtocolError, match="require local approval"):
        parse_task(json.dumps(value))