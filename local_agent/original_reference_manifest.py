"""Validate original-only reference manifests before library ingestion.

This module never downloads, creates, or claims ownership of an image.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

_ALLOWED_VIEWS = {"front", "back", "left", "right", "three_quarter", "face", "detail"}
_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}
_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 30 * 1024 * 1024


class OriginalReferenceError(ValueError):
    pass


def verify_original_reference(manifest_path: str | Path, asset_root: str | Path) -> dict:
    """Verify a local original reference and return its trusted metadata.

    The provenance is an explicit declaration, not proof of who generated the file.
    """
    manifest_path = Path(manifest_path)
    root = Path(asset_root)
    if manifest_path.is_symlink() or root.is_symlink():
        raise OriginalReferenceError("Symbolic links are not allowed")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OriginalReferenceError("Invalid manifest") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise OriginalReferenceError("Unsupported manifest")
    if payload.get("origin") != "project_generated":
        raise OriginalReferenceError("Only project-generated references are permitted")
    if payload.get("source_url") not in (None, ""):
        raise OriginalReferenceError("External source URL is not permitted")
    if not isinstance(payload.get("asset_id"), str) or not _ID.fullmatch(payload["asset_id"]):
        raise OriginalReferenceError("Invalid asset ID")
    if payload.get("view") not in _ALLOWED_VIEWS:
        raise OriginalReferenceError("Invalid view")
    relative = payload.get("file")
    if not isinstance(relative, str) or not relative or "\\\\" in relative or "\\x00" in relative:
        raise OriginalReferenceError("Invalid filename")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix.lower() not in _ALLOWED_EXT:
        raise OriginalReferenceError("Unsafe file path")
    if not root.is_dir() or not (root / candidate).is_file():
        raise OriginalReferenceError("Image missing")
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise OriginalReferenceError("Symlink in image path")
    resolved_root = root.resolve()
    image = (root / candidate).resolve()
    if not image.is_relative_to(resolved_root):
        raise OriginalReferenceError("Image escapes library")
    size = image.stat().st_size
    if not 0 < size <= _MAX_BYTES:
        raise OriginalReferenceError("Image size out of bounds")
    expected = payload.get("sha256")
    if not isinstance(expected, str) or not _SHA.fullmatch(expected):
        raise OriginalReferenceError("Invalid SHA-256")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    if digest != expected:
        raise OriginalReferenceError("Image hash mismatch")
    return {"asset_id": payload["asset_id"], "view": payload["view"],
            "file": str(image), "sha256": digest, "origin": "project_generated",
            "verified": True, "provenance_claim_verified": False}
