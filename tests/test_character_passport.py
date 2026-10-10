from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_agent import character_passport as passport


def test_requires_safe_project_and_character_ids():
    with pytest.raises(ValueError):
        passport.create_or_update_passport("../outside", "mia")
    with pytest.raises(ValueError):
        passport.create_or_update_passport("mia", "../other")


def test_blocks_when_workspace_is_not_configured(monkeypatch):
    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    assert passport.create_or_update_passport("mia", "mia") == {
        "status": "blocked", "reason": "set_LOCAL_AGENT_WORKSPACE_locally"
    }


def test_source_resolution_blocks_ambiguous_blend_files(tmp_path: Path):
    project = tmp_path / "mia"
    project.mkdir()
    (project / "one.blend").write_bytes(b"one")
    (project / "two.blend").write_bytes(b"two")
    assert passport._source_file(project, None) is None


def test_refuses_registry_symlink(tmp_path: Path):
    project = tmp_path / "mia"
    project.mkdir()
    target = project / "target.json"
    target.write_text("{}", encoding="utf-8")
    registry = project / "character_passports.json"
    try:
        registry.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not supported in this environment.")
    with pytest.raises(ValueError):
        passport._safe_registry_path(project)


def test_registry_write_is_atomic_and_preserves_json(tmp_path: Path):
    registry = tmp_path / "character_passports.json"
    payload = {"schema_version": 1, "characters": {"mia": {"history": []}}}
    passport._write_registry(registry, payload)
    assert json.loads(registry.read_text(encoding="utf-8")) == payload
    assert not registry.with_suffix(".json.lock").exists()
    assert not list(tmp_path.glob(".character-passports-*.tmp"))


def test_refuses_existing_lock(tmp_path: Path):
    registry = tmp_path / "character_passports.json"
    lock = registry.with_suffix(".json.lock")
    lock.write_text("busy", encoding="utf-8")
    with pytest.raises(RuntimeError, match="passport_registry_locked_retry_later"):
        passport._write_registry(registry, {"schema_version": 1, "characters": {}})
