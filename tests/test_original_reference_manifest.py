import hashlib
import json

import pytest

from local_agent.original_reference_manifest import (
    OriginalReferenceError, verify_original_reference,
)


def _make(tmp_path, **changes):
    image = tmp_path / "front.png"
    image.write_bytes(b"original-image-test-fixture")
    payload = {
        "schema_version": 1,
        "asset_id": "mia",
        "origin": "project_generated",
        "view": "front",
        "file": "front.png",
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
    }
    payload.update(changes)
    manifest = tmp_path / "reference.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def test_accepts_local_project_reference(tmp_path):
    manifest = _make(tmp_path)
    result = verify_original_reference(manifest, tmp_path)
    assert result["verified"] is True
    assert result["provenance_claim_verified"] is False


@pytest.mark.parametrize("changes", [
    {"origin": "internet"},
    {"source_url": "https://example.com/image.png"},
    {"file": "../escape.png"},
    {"file": "C:\\escape.png"},
    {"file": "/tmp/image.png"},
    {"view": "unknown"},
    {"asset_id": "../mia"},
    {"sha256": "0" * 64},
])
def test_rejects_untrusted_or_inconsistent_references(tmp_path, changes):
    manifest = _make(tmp_path, **changes)
    with pytest.raises(OriginalReferenceError):
        verify_original_reference(manifest, tmp_path)


def test_rejects_symlink(tmp_path):
    image = tmp_path / "front.png"
    image.write_bytes(b"test")
    (tmp_path / "linked.png").symlink_to(image)
    manifest = _make(tmp_path, file="linked.png")
    with pytest.raises(OriginalReferenceError):
        verify_original_reference(manifest, tmp_path)
