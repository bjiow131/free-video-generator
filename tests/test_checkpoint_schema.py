import json

import pytest

from local_agent.checkpoint import CheckpointStore


@pytest.mark.parametrize("schema_version", [True, 1.0, "1", None])
def test_checkpoint_rejects_non_integer_schema_version(tmp_path, schema_version):
    store = CheckpointStore(tmp_path, "schema-test")
    state = {
        "schema_version": 1,
        "project_id": "schema-test",
        "manifest": {"project_id": "schema-test", "scenes": []},
        "status": "queued",
        "scenes": {},
    }
    store.path.write_text(json.dumps(state), encoding="utf-8")
    loaded = json.loads(store.path.read_text(encoding="utf-8"))
    loaded["schema_version"] = schema_version
    store.path.write_text(json.dumps(loaded), encoding="utf-8")

    with pytest.raises(ValueError, match="malformed or uses an unsupported schema"):
        store.load()


def test_checkpoint_accepts_supported_integer_schema_version(tmp_path):
    store = CheckpointStore(tmp_path, "schema-test")
    state = {
        "schema_version": 1,
        "project_id": "schema-test",
        "manifest": {"project_id": "schema-test", "scenes": []},
        "status": "queued",
        "scenes": {},
    }
    store.path.write_text(json.dumps(state), encoding="utf-8")

    assert store.load()["schema_version"] == 1


def test_checkpoint_rejects_symlink_to_external_file(tmp_path):
    store = CheckpointStore(tmp_path / "workspace", "symlink-test")
    outside = tmp_path / "outside.json"
    outside.write_text('{"do_not_touch": true}', encoding="utf-8")
    try:
        store.path.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="Checkpoint file must not be a symlink"):
        store.load()
    assert outside.read_text(encoding="utf-8") == '{"do_not_touch": true}'


def test_event_log_rejects_symlink_to_external_file(tmp_path):
    store = CheckpointStore(tmp_path / "workspace", "symlink-test")
    outside = tmp_path / "outside.jsonl"
    outside.write_text("preserve this log\\n", encoding="utf-8")
    try:
        store.events_path.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="Event log must not be a symlink"):
        store.event("test_event", {"value": "must not be written"})
    assert outside.read_text(encoding="utf-8") == "preserve this log\\n"
