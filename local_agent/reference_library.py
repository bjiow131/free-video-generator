"""Data-only character passports and reference selection for the local application.

This module never executes an asset, calls Blender, or guesses image regions.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_VIEWS = {"front", "back", "left", "right", "three_quarter", "face", "pose", "detail"}
_MAX_BYTES = 128_000


class PassportError(ValueError):
    pass


def validate_passport(data: dict) -> dict:
    if not isinstance(data, dict):
        raise PassportError("Passport must be an object")
    if set(data) - {"schema_version", "id", "name", "description", "references", "model_asset_id", "status"}:
        raise PassportError("Unknown passport fields")
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        raise PassportError("Unsupported schema")
    identifier = data.get("id")
    if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
        raise PassportError("Invalid character ID")
    for field in ("name", "description"):
        if not isinstance(data.get(field), str) or not data[field].strip() or len(data[field]) > 3000:
            raise PassportError(f"Invalid {field}")
    refs = data.get("references", [])
    if not isinstance(refs, list) or len(refs) > 40:
        raise PassportError("Invalid reference list")
    seen = set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) - {"id", "view", "file", "status", "box"}:
            raise PassportError("Invalid reference")
        rid = ref.get("id")
        if not isinstance(rid, str) or not _ID.fullmatch(rid) or rid in seen:
            raise PassportError("Duplicate or invalid reference ID")
        seen.add(rid)
        if ref.get("view") not in _VIEWS or ref.get("status") not in {"planned", "ready"}:
            raise PassportError("Invalid reference view/status")
        filename = ref.get("file")
        if filename is not None:
            p = Path(filename)
            if not isinstance(filename, str) or p.is_absolute() or "\\" in filename or any(x in {"..", "."} for x in p.parts) or not filename.startswith("assets/") or p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise PassportError("Reference must use a relative assets/ image path")
        if ref["status"] == "ready" and filename is None:
            raise PassportError("Ready reference needs an image file")
        box = ref.get("box")
        if box is not None and (not isinstance(box, list) or len(box) != 4 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 1 for x in box) or box[0] >= box[2] or box[1] >= box[3]):
            raise PassportError("Box must be normalized [left,top,right,bottom]")
    model = data.get("model_asset_id")
    if model is not None and (not isinstance(model, str) or not _ID.fullmatch(model)):
        raise PassportError("Invalid model asset ID")
    if data.get("status", "draft") not in {"draft", "reviewed", "approved"}:
        raise PassportError("Invalid passport status")
    if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > _MAX_BYTES:
        raise PassportError("Passport too large")
    return data


def select_reference(passport: dict, camera: str) -> dict | None:
    """Select a ready reference by camera wording; return None rather than inventing one."""
    validate_passport(passport)
    text = camera.casefold()
    if any(x in text for x in ("сзади", "спиной", "rear", "back")):
        view = "back"
    elif any(x in text for x in ("слева", "left")):
        view = "left"
    elif any(x in text for x in ("справа", "right")):
        view = "right"
    elif any(x in text for x in ("профиль", "сбоку", "side")):
        view = "left"
    elif any(x in text for x in ("три четверти", "three quarter", "3/4")):
        view = "three_quarter"
    elif any(x in text for x in ("крупный план лица", "close-up face")):
        view = "face"
    else:
        view = "front"
    return next((r for r in passport["references"] if r["view"] == view and r["status"] == "ready"), None)


def build_scene_reference_plan(scene: dict, passports: list[dict]) -> dict:
    """Resolve explicitly named characters; missing reference is reported, not hidden."""
    text = " ".join(str(scene.get(k, "")) for k in ("action", "camera", "visual_prompt"))
    matches = []
    for passport in passports:
        validate_passport(passport)
        name = passport["name"]
        if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, flags=re.I):
            chosen = select_reference(passport, str(scene.get("camera", "")))
            matches.append({"character_id": passport["id"], "reference_id": chosen["id"] if chosen else None, "reference_status": "ready" if chosen else "missing", "model_asset_id": passport.get("model_asset_id")})
    return {"scene_id": scene.get("scene_id"), "characters": matches}


def write_passport(project_dir: str | Path, data: dict) -> Path:
    """Write a new passport without overwriting existing character identity."""
    validate_passport(data)
    project = Path(project_dir).resolve()
    target_dir = project / "passports"
    if target_dir.is_symlink():
        raise PassportError("Unsafe passport directory")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (data["id"] + ".json")
    if target.is_symlink():
        raise PassportError("Unsafe passport target")
    with target.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target
