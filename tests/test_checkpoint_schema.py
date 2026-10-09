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
