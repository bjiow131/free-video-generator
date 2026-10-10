"""Versioned local character passports built from Blender facial-rig audits.

The registry is local to each project. Original .blend files are never modified.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from typing import Any

_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
_CHARACTER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_MAX_REGISTRY_BYTES = 2 * 1024 * 1024
_MAX_HISTORY = 20


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_file(project: Path, requested: str | None) -> Path | None:
    if requested is not None:
        if Path(requested).name != requested or not requested.lower().endswith(".blend"):
            raise ValueError("blend_file must be a filename ending in .blend.")
        candidate = project / requested
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size == 0:
            return None
        return candidate
    preferred = ("mia_blockout.blend", "project.blend", "scene.blend", "mouth_motion.blend")
    candidates = [project / name for name in preferred if (project / name).is_file() and not (project / name).is_symlink()]
    if not candidates:
        candidates = [p for p in project.glob("*.blend") if p.is_file() and not p.is_symlink()]
    return candidates[0] if len(candidates) == 1 else None


def _safe_registry_path(project: Path) -> Path:
    registry = project / "character_passports.json"
    if registry.is_symlink() or getattr(registry, "is_junction", lambda: False)():
        raise ValueError("Character passport registry must not be a symlink or junction.")
    return registry


def _write_registry(registry: Path, data: dict[str, Any]) -> None:
    lock = registry.with_suffix(registry.suffix + ".lock")
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("passport_registry_locked_retry_later") from exc
    try:
        os.close(fd)
        if registry.exists():
            if registry.is_symlink() or registry.stat().st_size > _MAX_REGISTRY_BYTES:
                raise ValueError("Existing passport registry is unsafe or too large.")
            current = json.loads(registry.read_text(encoding="utf-8"))
            if not isinstance(current, dict) or current.get("schema_version") != 1 or not isinstance(current.get("characters"), dict):
                raise ValueError("Existing passport registry has an unsupported format.")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=registry.parent,
                                         prefix=".character-passports-", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, registry)
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _append_passport(registry: Path, character_id: str, passport: dict[str, Any]) -> int:
    """Lock, reload, append and atomically replace so concurrent refreshes do not clobber history."""
    lock = registry.with_suffix(registry.suffix + ".lock")
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("passport_registry_locked_retry_later") from exc
    try:
        os.close(fd)
        if registry.exists():
            if registry.is_symlink() or registry.stat().st_size > _MAX_REGISTRY_BYTES:
                raise ValueError("Existing passport registry is unsafe or too large.")
            data = json.loads(registry.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("characters"), dict):
                raise ValueError("Existing passport registry has an unsupported format.")
        else:
            data = {"schema_version": 1, "characters": {}}
        entry = data["characters"].setdefault(character_id, {"history": []})
        if not isinstance(entry, dict) or not isinstance(entry.get("history"), list):
            raise ValueError("Character entry in passport registry is invalid.")
        entry["history"].append(passport)
        entry["history"] = entry["history"][-_MAX_HISTORY:]
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=registry.parent,
                                         prefix=".character-passports-", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, registry)
        return len(entry["history"])
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def create_or_update_passport(project_name: str, character_id: str, blend_file: str | None = None) -> dict[str, Any]:
    """Audit one local Blender project and append a safe versioned character passport."""
    if not isinstance(project_name, str) or not _PROJECT_RE.fullmatch(project_name):
        raise ValueError("Invalid project_name.")
    if not isinstance(character_id, str) or not _CHARACTER_RE.fullmatch(character_id):
        raise ValueError("Invalid character_id.")
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not workspace_value:
        return {"status": "blocked", "reason": "set_LOCAL_AGENT_WORKSPACE_locally"}
    workspace = Path(workspace_value).expanduser().resolve()
    requested_project = workspace / project_name
    if requested_project.is_symlink() or getattr(requested_project, "is_junction", lambda: False)():
        raise ValueError("Project directory must not be a symlink or junction.")
    project = requested_project.resolve()
    if not project.is_relative_to(workspace) or project == workspace or not project.is_dir():
        return {"status": "blocked", "reason": "project_directory_missing_or_outside_workspace"}
    registry = _safe_registry_path(project)
    source = _source_file(project, blend_file)
    if source is None:
        return {"status": "blocked", "reason": "source_blend_missing_or_ambiguous"}
    from local_agent.blender_face_rig_check import check_face_rig
    report_name = "face_rig_passport_audit_" + uuid.uuid4().hex + ".json"
    audit = check_face_rig(project_name, source.name, report_name=report_name)
    stat = source.stat()
    passport = {
        "character_id": character_id,
        "schema_version": 1,
        "created_or_updated_at": datetime.now(timezone.utc).isoformat(),
        "status": audit.get("status", "unknown"),
        "source": {
            "filename": source.name,
            "size_bytes": stat.st_size,
            "sha256": _sha256(source),
        },
        "blender_version": audit.get("blender_version"),
        "rig": {
            "mesh_count": audit.get("mesh_count"),
            "armatures": audit.get("armatures", []),
            "shape_keys": audit.get("shape_keys", []),
            "facial_bones": audit.get("facial_bones", []),
            "facial_custom_properties": audit.get("facial_custom_properties", []),
            "mouth_related_drivers": audit.get("mouth_related_drivers", []),
        },
        "audit": {
            "summary": audit.get("summary"),
            "reason": audit.get("reason"),
            "report_filename": report_name,
            "checks": audit.get("checks", {}),
            "fixes": audit.get("fixes", []),
        },
        "limitations": [
            "Controller names are heuristic and do not prove correct facial deformation.",
            "Visual review in Blender is required before production use.",
            "This passport does not copy or modify the source .blend file.",
        ],
    }
    history_entries = _append_passport(registry, character_id, passport)
    return {
        "status": passport["status"],
        "character_id": character_id,
        "registry_path": str(registry),
        "history_entries": history_entries,
        "audit": audit,
        "source_sha256": passport["source"]["sha256"],
    }
