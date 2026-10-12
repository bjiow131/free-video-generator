"""Read-only library reconciliation for character references, props and environments."""
from __future__ import annotations
from pathlib import Path
from collections import Counter
from local_agent.asset_registry import scan_project_assets, AssetRegistryError

CATEGORIES = {"characters", "references", "props", "environments", "animals"}

def inspect_library(workspace: str, project_name: str) -> dict:
    """Reindex local assets, classify folders, and report gaps without replacing assets."""
    result = scan_project_assets(workspace, project_name)
    root = (Path(workspace).expanduser().resolve() / project_name).resolve()
    import json
    registry = json.loads((root / "asset_registry.json").read_text(encoding="utf-8"))
    groups = {key: [] for key in sorted(CATEGORIES)}
    unclassified = []
    for asset in registry["assets"]:
        path = asset["path"].split("/")
        category = next((part.lower() for part in path[1:-1] if part.lower() in CATEGORIES), None)
        item = {"asset_id": asset["asset_id"], "path": asset["path"]}
        (groups[category] if category else unclassified).append(item)
    result.update({
        "categories": {key: len(items) for key, items in groups.items()},
        "unclassified_count": len(unclassified),
        "missing_categories": [key for key, items in groups.items() if not items],
        "mode": "inventory_only",
        "character_cards_modified": False,
        "original_assets_modified": False,
        "next_action": "Review inventory before linking or modifying character cards.",
    })
    return result
