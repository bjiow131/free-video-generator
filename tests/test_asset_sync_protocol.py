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
