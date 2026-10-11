import hashlib
import json

import pytest

from local_agent.character_library import CharacterPassportImportError, import_character_passport


def test_imports_original_reference_with_view(tmp_path):
    library = tmp_path / "library"
    original = tmp_path / "original"
    original.mkdir()
    image = original / "front.png"
    image.write_bytes(b"generated-image-fixture")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    manifest = original / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1, "asset_id": "mia", "origin": "project_generated",
        "view": "front", "file": "front.png", "sha256": digest,
    }), encoding="utf-8")
    passport = tmp_path / "mia.json"
    passport.write_text(json.dumps({"schema_version": 1, "character_id": "mia", "display_name": "Мия"}), encoding="utf-8")
    result = import_character_passport(passport, library, original_reference_manifests=[manifest], original_asset_root=original)
    assert result["references_added"] == 1
    card = json.loads((library / "characters.json").read_text(encoding="utf-8"))[0]
    assert card["original_reference_metadata"][0]["view"] == "front"
    assert card["original_reference_metadata"][0]["sha256"] == digest
    assert card["original_reference_metadata"][0]["provenance_claim_verified"] is False
    assert len(card["references"]) == 1


def test_rejects_unverified_direct_image(tmp_path):
    passport = tmp_path / "mia.json"
    passport.write_text(json.dumps({"schema_version": 1, "character_id": "mia"}), encoding="utf-8")
    image = tmp_path / "front.png"
    image.write_bytes(b"image")
    with pytest.raises(CharacterPassportImportError):
        import_character_passport(passport, tmp_path / "library", reference_paths=[image])


def test_rejects_reference_for_other_character(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    image = original / "front.png"
    image.write_bytes(b"image")
    manifest = original / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "asset_id": "stepa",
        "origin": "project_generated", "view": "front", "file": "front.png",
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}), encoding="utf-8")
    passport = tmp_path / "mia.json"
    passport.write_text(json.dumps({"schema_version": 1, "character_id": "mia"}), encoding="utf-8")
    with pytest.raises(CharacterPassportImportError):
        import_character_passport(passport, tmp_path / "library",
            original_reference_manifests=[manifest], original_asset_root=original)
