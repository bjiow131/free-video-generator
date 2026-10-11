"""Install the Season 1 passport set into a local Blender Agent library.

Run from the repository root:
    python scripts/prepare_season1_library.py
The script imports metadata only; it never downloads third-party visual assets.
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
# Third-party downloader intentionally not imported.

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
    atomic_write(database, cards)
    manifest = {
        "schema_version": 1,
        "series": inventory["season"],
        "character_count": len(inventory["character_ids"]),
        "character_ids": inventory["character_ids"],
        "imported_this_run": imported,
        "skipped_unchanged": skipped,
        "reference_pack_manifest": None,
        "catalog_path": str(CATALOG_PATH.resolve()),
        "inventory_path": str(INVENTORY_PATH.resolve()),
        "notes": [
            "Passports describe intended designs; no character model or rig is asserted to exist.",
            "Do not import third-party visual assets into the production library.",
            "No external images or models are downloaded; import original project-specific references separately."
        ]
    }
    atomic_write(library / "season1_manifest.json", manifest)
    print(f"Season 1 library ready: {len(inventory['character_ids'])} passports; imported={len(imported)}, unchanged={len(skipped)}")
    print(f"Local library: {library}")
    print(f"Manifest: {library / 'season1_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
