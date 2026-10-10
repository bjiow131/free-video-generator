from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_agent.character_library import CharacterPassportImportError, import_character_passport


def _passport(character_id: str = "mia", status: str = "ready") -> dict:
    return {
        "schema_version": 1,
        "character_id": character_id,
        "status": status,
        "source": {"filename": "mia.blend", "sha256": "abc123"},
        "rig": {
            "mesh_count": 4,
            "armatures": ["MiaRig"],
            "shape_keys": ["mouthOpen"],
            "facial_bones": ["jaw"],
            "mouth_related_drivers": ["Mouth_Open"],
        },
        "audit": {"summary": "Rig controls detected"},
    }


def test_import_creates_card_and_versioned_passport(tmp_path: Path):
    source = tmp_path / "passport.json"
    source.write_text(json.dumps(_passport(), ensure_ascii=False), encoding="utf-8")
    library = tmp_path / "library"

    result = import_character_passport(source, library, display_name="Мия")

    cards = json.loads((library / "characters.json").read_text(encoding="utf-8"))
    assert result["character_id"] == "mia"
    assert result["passport_version"] == 1
    assert cards[0]["name"] == "Мия"
    assert cards[0]["passport_status"] == "ready"
    assert cards[0]["rig_summary"]["mesh_count"] == 4
    assert (library / "mia" / "passport_versions" / "v0001.json").is_file()
    assert source.is_file()


def test_reimport_updates_existing_card_without_losing_references(tmp_path: Path):
    source = tmp_path / "passport.json"
    library = tmp_path / "library"
    source.write_text(json.dumps(_passport()), encoding="utf-8")
    import_character_passport(source, library, display_name="Мия")
    db = library / "characters.json"
    cards = json.loads(db.read_text(encoding="utf-8"))
    cards[0]["references"] = ["keep-this-reference.png"]
    db.write_text(json.dumps(cards), encoding="utf-8")

    source.write_text(json.dumps(_passport(status="needs_review")), encoding="utf-8")
    result = import_character_passport(source, library)

    cards = json.loads(db.read_text(encoding="utf-8"))
    assert result["passport_version"] == 2
    assert cards[0]["references"] == ["keep-this-reference.png"]
    assert cards[0]["name"] == "Мия"
    assert cards[0]["passport_status"] == "needs_review"
    assert (library / "mia" / "passport_versions" / "v0002.json").is_file()


def test_import_selects_character_from_registry(tmp_path: Path):
    source = tmp_path / "registry.json"
    source.write_text(json.dumps({
        "schema_version": 1,
        "characters": {
            "mia": {"history": [_passport("mia")]},
            "snail": {"history": [_passport("snail")]},
        },
    }), encoding="utf-8")

    result = import_character_passport(source, tmp_path / "library", character_id="snail")
    assert result["character_id"] == "snail"


def test_multi_character_registry_requires_explicit_id(tmp_path: Path):
    source = tmp_path / "registry.json"
    source.write_text(json.dumps({
        "schema_version": 1,
        "characters": {"mia": {"history": [_passport("mia")]}, "snail": {"history": [_passport("snail")]}},
    }), encoding="utf-8")
    with pytest.raises(CharacterPassportImportError, match="несколько персонажей"):
        import_character_passport(source, tmp_path / "library")


@pytest.mark.parametrize("bad_id", ["../outside", "", "two words", ".hidden"])
def test_rejects_unsafe_character_ids(tmp_path: Path, bad_id: str):
    source = tmp_path / "passport.json"
    source.write_text(json.dumps(_passport(bad_id)), encoding="utf-8")
    with pytest.raises(CharacterPassportImportError):
        import_character_passport(source, tmp_path / "library")


def test_rejects_unknown_schema_and_non_json(tmp_path: Path):
    source = tmp_path / "passport.json"
    source.write_text(json.dumps({"schema_version": 2, "character_id": "mia"}), encoding="utf-8")
    with pytest.raises(CharacterPassportImportError, match="схемы"):
        import_character_passport(source, tmp_path / "library")
    source.write_text("{broken", encoding="utf-8")
    with pytest.raises(CharacterPassportImportError, match="корректный"):
        import_character_passport(source, tmp_path / "library")


def test_corrupt_existing_database_is_not_overwritten(tmp_path: Path):
    source = tmp_path / "passport.json"
    source.write_text(json.dumps(_passport()), encoding="utf-8")
    library = tmp_path / "library"
    library.mkdir()
    db = library / "characters.json"
    db.write_text("{broken", encoding="utf-8")
    with pytest.raises(CharacterPassportImportError, match="повреждён"):
        import_character_passport(source, library)
    assert db.read_text(encoding="utf-8") == "{broken"
