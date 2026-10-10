"""Safely apply a local, hash-verified, file-by-file agent update."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import time
from typing import Any


class UpdateError(ValueError):
    """A local update package failed validation or installation."""


_ALLOWED_SUFFIXES = {".py", ".md", ".json", ".bat", ".ps1", ".yml"}
_ALLOWED_ROOTS = ("local_agent/", "tests/", ".github/workflows/", "BLENDER_AGENT_QUICKSTART_RU.md",
                  "run_blender_agent.bat", "setup_blender_agent.bat",
                  "install_blender_agent_autostart.ps1", "uninstall_blender_agent_autostart.bat")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_FILE_BYTES = 2_000_000
_MAX_FILES = 100


def _safe_relative_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise UpdateError("Update contains an invalid relative path.")
    posix = PurePosixPath(value)
    if any(part in ("", ".", "..") for part in posix.parts):
        raise UpdateError("Update path traversal is not allowed.")
    normalized = posix.as_posix()
    if not any(normalized == root or normalized.startswith(root) for root in _ALLOWED_ROOTS):
        raise UpdateError(f"Update is not allowed to change this path: {normalized}")
    if Path(normalized).suffix.lower() not in _ALLOWED_SUFFIXES:
        raise UpdateError(f"Unsupported update file type: {normalized}")
    return Path(*posix.parts)


def apply_update_folder(update_dir: Path, install_root: Path) -> dict[str, Any]:
    """Install files from payload/ after validating every path and SHA-256 hash.

    A complete backup of each overwritten file is created before replacement.
    Project/workspace folders are never traversed or changed.
    """
    update_dir = update_dir.expanduser().resolve()
    install_root = install_root.expanduser().resolve()
    manifest_path = update_dir / "update_manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise UpdateError("update_manifest.json is missing or is a symlink.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError("Update manifest is not valid JSON.") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise UpdateError("Unsupported update manifest schema.")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > _MAX_FILES:
        raise UpdateError(f"Update must contain between 1 and {_MAX_FILES} files.")
    payload = update_dir / "payload"
    if not payload.is_dir() or payload.is_symlink():
        raise UpdateError("Update payload/ directory is missing or is a symlink.")

    staged: list[tuple[Path, Path, str]] = []
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise UpdateError("Malformed file entry in update manifest.")
        relative = _safe_relative_path(entry.get("path"))
        normalized = relative.as_posix()
        if normalized in seen:
            raise UpdateError(f"Duplicate path in update manifest: {normalized}")
        seen.add(normalized)
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
            raise UpdateError(f"Missing or invalid SHA-256 for {normalized}")
        source = payload.joinpath(*PurePosixPath(normalized).parts)
        cursor = payload
        for part in PurePosixPath(normalized).parts:
            cursor = cursor / part
            if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
                raise UpdateError(f"Update payload contains a symlink or junction: {normalized}")
        if source.is_symlink() or not source.is_file():
            raise UpdateError(f"Update file is missing or is a symlink: {normalized}")
        if source.stat().st_size > _MAX_FILE_BYTES:
            raise UpdateError(f"Update file exceeds the size limit: {normalized}")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != expected_hash:
            raise UpdateError(f"SHA-256 mismatch for {normalized}")
        destination = install_root.joinpath(*relative.parts)
        if not destination.resolve().is_relative_to(install_root):
            raise UpdateError(f"Destination escapes the installation root: {normalized}")
        if destination.is_symlink() or getattr(destination, "is_junction", lambda: False)():
            raise UpdateError(f"Destination is a symlink or junction: {normalized}")
        staged.append((source, destination, normalized))

    backup_root = install_root / "update_backups" / time.strftime("%Y%m%d_%H%M%S")
    # Back up every existing target before replacing any file.
    for _source, destination, normalized in staged:
        if destination.exists():
            if not destination.is_file():
                raise UpdateError(f"Destination is not a regular file: {normalized}")
            backup = backup_root.joinpath(*PurePosixPath(normalized).parts)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)

    installed: list[Path] = []
    try:
        for source, destination, _normalized in staged:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".update-tmp")
            if temporary.exists() or temporary.is_symlink():
                raise UpdateError(f"Temporary update path already exists: {temporary.name}")
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
            installed.append(destination)
    except OSError as exc:
        # Best-effort rollback from backups, and remove newly-created files.
        for destination in reversed(installed):
            backup = backup_root.joinpath(*destination.relative_to(install_root).parts)
            try:
                if backup.is_file():
                    shutil.copy2(backup, destination)
                else:
                    destination.unlink(missing_ok=True)
            except OSError:
                pass
        raise UpdateError(f"Update failed and rollback was attempted ({type(exc).__name__}).") from exc
    return {"status": "completed", "updated_count": len(installed),
            "files": [path.relative_to(install_root).as_posix() for path in installed],
            "backup_dir": str(backup_root) if backup_root.exists() else "No existing files needed backup"}
