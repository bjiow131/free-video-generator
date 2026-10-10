"""Install the Season 1 passport set into a local Blender Agent library.

Run from the repository root:
    python scripts/prepare_season1_library.py
The script downloads only the three explicitly catalogued CC0 photo references;
it does not download/extract third-party 3D model archives automatically.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_agent.character_library import import_character_passport
from local_agent.scene01_reference_pack import download_scene01_reference_pack

PASSPORT_DIR = ROOT / "docs" / "season1" / "character_passports"
CATALOG_PATH = ROOT / "docs" / "season1" / "asset_catalog.json"
INVENTORY_PATH = ROOT / "docs" / "season1" / "scene_inventory.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    library = Path(os.environ.get("LOCAL_AGENT_CHARACTER_LIBRARY", str(Path.home() / "BlenderAgentLibrary"))).expanduser()
    library.mkdir(parents=True, exist_ok=True)
    database = library / "characters.json"
    if database.is_symlink():
        raise RuntimeError("characters.json is a symbolic link; refusing to overwrite it.")

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    pack = download_scene01_reference_pack(library, include_character_pack=False)
    cards = json.loads(database.read_text(encoding="utf-8")) if database.exists() else []
    if not isinstance(cards, list):
        raise RuntimeError("characters.json has an unsupported format; no changes were applied.")
    by_id = {str(card.get("id")): card for card in cards if isinstance(card, dict)}

    imported = []
    skipped = []
    for passport_path in sorted(PASSPORT_DIR.glob("*.json")):
        passport = json.loads(passport_path.read_text(encoding="utf-8"))
        character_id = passport["character_id"]
        digest = sha256(passport_path)
        existing = by_id.get(character_id)
        if existing and existing.get("season1_source_passport_sha256") == digest:
            skipped.append(character_id)
            continue
        result = import_character_passport(passport_path, library, display_name=passport["display_name"])
        imported.append(result)
        by_id = {str(card.get("id")): card for card in json.loads(database.read_text(encoding="utf-8")) if isinstance(card, dict)}
        card = by_id[character_id]
        card["kind"] = "Животное" if passport.get("category") == "animal" else "Персонаж"
        card["profile_type"] = "Животное" if passport.get("category") == "animal" else "Человек"
        card["visual_style"] = "Стилизованный 3D"
        card["description"] = passport.get("role", "")
        card["season1_source_passport_sha256"] = digest
        card["reference_sources"] = passport.get("reference_sources", [])
        card["season"] = 1
        atomic_write(database, list(by_id.values()))

    cards = json.loads(database.read_text(encoding="utf-8")) if database.exists() else []
    by_id = {str(card.get("id")): card for card in cards if isinstance(card, dict)}
    pack_dir = Path(pack["pack_dir"])
    snail_card = by_id.get("snail-spiral")
    if snail_card:
        refs = list(snail_card.get("references", []))
        labels = dict(snail_card.get("reference_labels", {}))
        for filename, label in (
            ("snail_moss_cc0.jpg", "Анатомия улитки — на мху"),
            ("garden_snail_wood_cc0.jpg", "Ракушка и боковой вид"),
        ):
            candidate = pack_dir / filename
            if candidate.is_file():
                resolved = str(candidate.resolve())
                if resolved not in refs:
                    refs.append(resolved)
                labels[resolved] = label
        snail_card["references"] = refs
        snail_card["reference_labels"] = labels
        snail_card["reference_sources"] = json.loads(
            (PASSPORT_DIR / "snail-spiral.json").read_text(encoding="utf-8")
        ).get("reference_sources", [])

    path_card = by_id.get("scene01_path_refs")
    if not path_card:
        path_card = {
            "id": "scene01_path_refs",
            "name": "Лесная тропинка — референсы сезона 1",
            "kind": "Окружение",
            "profile_type": "Объект / предмет",
            "visual_style": "Фотореференс",
            "description": "CC0-фотографии для композиции окружения; это не готовые 3D-модели.",
            "references": [],
            "reference_labels": {},
            "season": 1,
        }
        cards.append(path_card)
        by_id["scene01_path_refs"] = path_card
    refs = list(path_card.get("references", []))
    labels = dict(path_card.get("reference_labels", {}))
    path_image = pack_dir / "woodland_path_cc0.jpg"
    if path_image.is_file():
        resolved = str(path_image.resolve())
        if resolved not in refs:
            refs.append(resolved)
        labels[resolved] = "Лесная тропинка — композиция окружения"
    path_card["references"] = refs
    path_card["reference_labels"] = labels
    path_card["reference_sources"] = [
        item for item in catalog["source_packs"] if item["id"] in {"forest_path_photo", "trees", "wilderness"}
    ]

    atomic_write(database, cards)
    manifest = {
        "schema_version": 1,
        "series": inventory["season"],
        "character_count": len(inventory["character_ids"]),
        "character_ids": inventory["character_ids"],
        "imported_this_run": imported,
        "skipped_unchanged": skipped,
        "reference_pack_manifest": str(Path(pack["manifest_path"]).resolve()),
        "catalog_path": str(CATALOG_PATH.resolve()),
        "inventory_path": str(INVENTORY_PATH.resolve()),
        "notes": [
            "Passports describe intended designs; no character model or rig is asserted to exist.",
            "Open each source page and verify exact license and file compatibility before adopting 3D assets.",
            "Only CC0 photo references are downloaded automatically. Model archives are intentionally not extracted or imported."
        ]
    }
    atomic_write(library / "season1_manifest.json", manifest)
    print(f"Season 1 library ready: {len(inventory['character_ids'])} passports; imported={len(imported)}, unchanged={len(skipped)}")
    print(f"Local library: {library}")
    print(f"Manifest: {library / 'season1_manifest.json'}")
    if pack.get("failures"):
        print(f"Reference download failures: {len(pack['failures'])}; see pack manifest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
