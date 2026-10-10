from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from local_agent.scene_edit import SceneEditError, _parse
from local_agent.update_manager import UpdateError, apply_update_folder


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("добавь куб", {"action": "add", "replacement": "cube"}),
        ("создай стол", {"action": "add", "replacement": "table"}),
        ("замени дерево на стол", {"action": "replace", "target": "дерево", "replacement": "table"}),
        ("исправить в этом участке дерево на стол", {"action": "replace", "target": "дерево", "replacement": "table"}),
    ],
)
def test_allowlisted_existing_scene_operations(prompt, expected):
    assert _parse(prompt) == expected


def test_unsupported_existing_scene_task_is_rejected():
    with pytest.raises(SceneEditError, match="пока не поддерживается"):
        _parse("сделай красивее и добавь сложную анимацию")


def test_delete_requires_a_named_object():
    assert _parse("удали объект Tree_Main") == {"action": "delete", "target": "tree_main"}


def test_update_installs_hash_verified_file_and_keeps_backup(tmp_path: Path):
    install = tmp_path / "install"
    (install / "local_agent").mkdir(parents=True)
    target = install / "local_agent" / "example.py"
    target.write_text("old\n", encoding="utf-8")
    package = tmp_path / "update"
    payload = package / "payload" / "local_agent"
    payload.mkdir(parents=True)
    source = payload / "example.py"
    source.write_text("new\n", encoding="utf-8")
    manifest = {"schema_version": 1, "files": [{
        "path": "local_agent/example.py",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }]}
    (package / "update_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = apply_update_folder(package, install)
    assert result["updated_count"] == 1
    assert target.read_text(encoding="utf-8") == "new\n"
    backups = list((install / "update_backups").rglob("example.py"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "old\n"


def test_update_rejects_path_traversal(tmp_path: Path):
    package = tmp_path / "update"
    (package / "payload").mkdir(parents=True)
    content = "unsafe"
    (package / "payload" / "unsafe.py").write_text(content, encoding="utf-8")
    manifest = {"schema_version": 1, "files": [{
        "path": "../outside.py",
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
    }]}
    (package / "update_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(UpdateError):
        apply_update_folder(package, tmp_path / "install")


def test_update_rejects_hash_mismatch(tmp_path: Path):
    install = tmp_path / "install"
    package = tmp_path / "update"
    payload = package / "payload" / "local_agent"
    payload.mkdir(parents=True)
    source = payload / "example.py"
    source.write_text("tampered", encoding="utf-8")
    (package / "update_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "files": [{"path": "local_agent/example.py", "sha256": "0" * 64}],
    }), encoding="utf-8")
    with pytest.raises(UpdateError, match="SHA-256 mismatch"):
        apply_update_folder(package, install)
