from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEASON = ROOT / "docs" / "season1"


def test_season1_has_complete_versioned_passports_with_open_references():
    passport_files = sorted((SEASON / "character_passports").glob("*.json"))
    assert len(passport_files) >= 12
    ids = set()
    for path in passport_files:
        passport = json.loads(path.read_text(encoding="utf-8"))
        assert passport["schema_version"] == 1
        assert passport["character_id"] == path.stem
        assert passport["character_id"] not in ids
        ids.add(passport["character_id"])
        assert passport["display_name"]
        assert passport["role"]
        assert passport["visual_identity"]
        assert passport["animation_requirements"]
        assert passport["rig"]["status"] == "not_created"
        assert passport["status"] == "design_ready_model_not_built"
        refs = passport["reference_sources"]
        assert refs
        assert all(item["url"].startswith("https://") and item["license"] for item in refs)


def test_season1_asset_catalog_and_reusable_inventory_are_consistent():
    catalog = json.loads((SEASON / "asset_catalog.json").read_text(encoding="utf-8"))
    inventory = json.loads((SEASON / "scene_inventory.json").read_text(encoding="utf-8"))
    assert catalog["schema_version"] == inventory["schema_version"] == 1
    assert inventory["target_episodes"] == 30
    assert 5 <= inventory["episode_duration_minutes"][0] <= inventory["episode_duration_minutes"][1] <= 10
    assert "жёлтый самокат Мии" in inventory["prop_groups"][0]["items"]
    assert any(item["id"] == "snail_moss_photo" for item in catalog["source_packs"])
    assert any("not a child likeness" in item["use"] for item in catalog["source_packs"] if item["id"] in {"human_men", "human_women"})
