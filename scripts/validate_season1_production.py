"""Audit Season 1 library completeness without modifying project assets.

Run from repository root:
    python scripts/validate_season1_production.py
Use --strict to return exit code 2 when production blockers remain.
The validator reports missing data; it never claims that remote references are
downloaded, licenses are verified, or models are Blender-ready merely because
a source URL exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "season1"
PASSPORT_DIR = DOCS / "character_passports"
CATALOG_PATH = DOCS / "asset_catalog.json"
INVENTORY_PATH = DOCS / "scene_inventory.json"

REQUIRED_PASSPORT_FIELDS = (
    "character_id", "display_name", "category", "role", "visual_identity",
    "personality", "animation_requirements", "voice_and_mouth_sync",
    "rig", "continuity_rules", "reference_sources",
)
REQUIRED_PRODUCTION_PROFILE = (
    "canonical_silhouette", "palette_hex", "height_m", "turnaround_status",
    "expression_sheet_status", "rig_status", "animation_test_status",
)
VALID_STATES = {"not_started", "in_progress", "verified", "blocked", "not_applicable"}


def load_json(path: Path, issues: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        issues.append(f"MISSING FILE: {path.relative_to(ROOT)}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        issues.append(f"INVALID JSON: {path.relative_to(ROOT)}: {exc}")
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_passports(issues: list[str], warnings: list[str]) -> dict:
    inventory = load_json(INVENTORY_PATH, issues) or {}
    expected_ids = set(inventory.get("character_ids", []))
    paths = sorted(PASSPORT_DIR.glob("*.json"))
    found_ids: set[str] = set()
    profiles_complete = 0
    sources = 0
    invalid_sources = 0

    if not paths:
        issues.append("NO CHARACTER PASSPORTS FOUND")
    for path in paths:
        passport = load_json(path, issues)
        if not isinstance(passport, dict):
            continue
        cid = str(passport.get("character_id", ""))
        if not cid:
            issues.append(f"{path.name}: missing character_id")
        elif cid in found_ids:
            issues.append(f"{path.name}: duplicate character_id {cid}")
        found_ids.add(cid)

        for field in REQUIRED_PASSPORT_FIELDS:
            value = passport.get(field)
            if value is None or value == "" or value == []:
                issues.append(f"{path.name}: missing required field {field}")

        profile = passport.get("production_profile")
        if not isinstance(profile, dict):
            warnings.append(f"{path.name}: production_profile not yet completed")
        else:
            missing = [key for key in REQUIRED_PRODUCTION_PROFILE if profile.get(key) in (None, "", [])]
            if missing:
                warnings.append(f"{path.name}: production_profile incomplete: {', '.join(missing)}")
            else:
                profiles_complete += 1
            for state_key in ("turnaround_status", "expression_sheet_status", "rig_status", "animation_test_status"):
                state = profile.get(state_key)
                if state and state not in VALID_STATES:
                    issues.append(f"{path.name}: invalid state {state_key}={state!r}")
            height = profile.get("height_m")
            if height is not None and (not isinstance(height, (int, float)) or height <= 0):
                issues.append(f"{path.name}: height_m must be a positive number")

        refs = passport.get("reference_sources", [])
        if not isinstance(refs, list) or not refs:
            warnings.append(f"{path.name}: no reference sources listed")
            continue
        for ref in refs:
            sources += 1
            if not isinstance(ref, dict):
                invalid_sources += 1
                issues.append(f"{path.name}: reference source must be an object")
                continue
            url = str(ref.get("url", ""))
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                invalid_sources += 1
                issues.append(f"{path.name}: reference URL is not valid HTTPS: {url!r}")
            if not ref.get("license"):
                warnings.append(f"{path.name}: source has no license field: {url}")
            if not ref.get("usage"):
                warnings.append(f"{path.name}: source has no usage restriction: {url}")

        rig = passport.get("rig", {})
        if isinstance(rig, dict) and rig.get("status") not in ("verified", "built", "ready"):
            warnings.append(f"{path.name}: rig not verified (reported status: {rig.get('status', 'missing')})")

    if expected_ids and found_ids != expected_ids:
        missing = sorted(expected_ids - found_ids)
        extra = sorted(found_ids - expected_ids)
        if missing:
            issues.append("Missing passport IDs: " + ", ".join(missing))
        if extra:
            warnings.append("Passport IDs not in inventory: " + ", ".join(extra))

    catalog = load_json(CATALOG_PATH, issues) or {}
    catalog_sources = catalog.get("source_packs", [])
    if not catalog_sources:
        warnings.append("Asset catalog has no source_packs")
    for item in catalog_sources:
        if not item.get("url") or not item.get("license"):
            warnings.append(f"Catalog item {item.get('id', '<unknown>')} needs URL/license review")
        if item.get("license") and ("verify" in str(item["license"]).lower() or "check" in str(item["license"]).lower()):
            warnings.append(f"Catalog license is not yet verified for exact downloadable asset: {item.get('id', '<unknown>')}")

    return {
        "passport_count": len(found_ids),
        "expected_character_count": len(expected_ids),
        "production_profiles_complete": profiles_complete,
        "reference_entries": sources,
        "invalid_reference_urls": invalid_sources,
        "catalog_entries": len(catalog_sources),
    }


def audit_local_manifest(warnings: list[str]) -> dict:
    """Check a user's local manifest if present; never download anything."""
    home = Path.home() / "BlenderAgentLibrary"
    manifest_path = home / "season1_manifest.json"
    if not manifest_path.is_file():
        warnings.append("Local asset manifest not found; run the GUI import/download action before checking local files.")
        return {"manifest_found": False, "assets_checked": 0, "missing_files": 0}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        warnings.append(f"Local manifest cannot be parsed: {exc}")
        return {"manifest_found": True, "assets_checked": 0, "missing_files": 0}

    checked = 0
    missing = 0
    for item in manifest.get("assets", []):
        file_value = item.get("path") or item.get("local_path")
        if not file_value:
            continue
        checked += 1
        path = Path(file_value).expanduser()
        if not path.is_file():
            missing += 1
            warnings.append(f"Local asset missing: {path}")
            continue
        expected_hash = item.get("sha256")
        if expected_hash and sha256(path).lower() != str(expected_hash).lower():
            warnings.append(f"Local asset hash mismatch: {path}")
    return {"manifest_found": True, "assets_checked": checked, "missing_files": missing}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit 2 when blocking issues or production warnings remain")
    args = parser.parse_args()

    issues: list[str] = []
    warnings: list[str] = []
    summary = audit_passports(issues, warnings)
    local = audit_local_manifest(warnings)
    report = {
        "schema_version": 1,
        "status": "blocked" if issues or warnings else "ready_for_blender_validation",
        "summary": summary,
        "local_manifest": local,
        "blocking_issues": issues,
        "warnings": warnings,
        "limitations": [
            "A source URL is not proof of an exact asset license or a downloaded file.",
            "This script does not launch Blender and cannot verify mesh, textures, scale, rig, or animation clips.",
            "Production readiness requires the Blender checklist and a rendered test scene to be completed by the local agent.",
        ],
    }
    output = DOCS / "production_readiness_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nReport written to {output.relative_to(ROOT)}")
    return 2 if args.strict and (issues or warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
