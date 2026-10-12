import json

from local_agent.control_protocol import parse_task


def test_pinned_asset_sync_is_a_protocol_operation_with_local_approval():
    task = parse_task(json.dumps({
        "protocol_version": 1,
        "task_id": "asset-sync-episode1-test",
        "operation": "sync_approved_assets",
        "created_at": "2026-10-12T00:00:00Z",
        "expires_at": "2026-10-12T00:10:00Z",
        "requires_local_approval": True,
        "arguments": {"project_name": "episode1"},
    }))
    assert task.operation == "sync_approved_assets"
    assert task.requires_local_approval is True


def test_episode1_scene_export_is_fixed_and_requires_local_approval():
    task = parse_task(json.dumps({
        "protocol_version": 1,
        "task_id": "episode1-scene-export-test",
        "operation": "export_mia_scene_review",
        "created_at": "2026-10-12T00:00:00Z",
        "expires_at": "2026-10-12T00:10:00Z",
        "requires_local_approval": True,
        "arguments": {"project_name": "S01E01_SC01_DRAFT"},
    }))
    assert task.operation == "export_mia_scene_review"
    assert task.requires_local_approval is True


def test_episode1_scene_export_rejects_other_projects():
    import pytest
    from local_agent.control_protocol import ProtocolError
    with pytest.raises(ProtocolError, match="fixed Episode 1 draft"):
        parse_task(json.dumps({
            "protocol_version": 1,
            "task_id": "episode1-scene-export-bad",
            "operation": "export_mia_scene_review",
            "created_at": "2026-10-12T00:00:00Z",
            "expires_at": "2026-10-12T00:10:00Z",
            "requires_local_approval": True,
            "arguments": {"project_name": "other"},
        }))
