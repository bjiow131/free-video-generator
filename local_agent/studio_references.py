"""Serve the user's *approved* Mia turnaround to the local Studio.

Only the pinned, previously synced private image is eligible. This module
never fetches remote assets, creates a new character, or exposes arbitrary
project files via request parameters.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from local_agent.studio_state import StudioConflict, StudioError, StudioStore

# Approved private asset: bjiow131/local-agent-mailbox, previously synced to episode1.
APPROVED_RELATIVE = ("episode1", "assets", "references", "mia_turnaround_approved_20261012.jpeg")
APPROVED_SHA256 = "7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383"
APPROVED_SIZE = 111601
MEDIA_FILENAME = APPROVED_SHA256[:32] + ".jpg"
VIEWS = ("Анфас", "Профиль", "Со спины")


def _reject_link(path: Path) -> None:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise StudioError("Unsafe reference path")


def approved_bytes(workspace: Path) -> bytes | None:
    """Read fixed source and verify exact bytes BEFORE they enter the Studio."""
    root = Path(workspace).expanduser().resolve()
    current = root
    for part in APPROVED_RELATIVE:
        current = current / part
        _reject_link(current)
    if not current.is_file():
        return None
    if current.stat().st_size != APPROVED_SIZE:
        raise StudioError("Approved Mia reference does not match the pinned size")
    raw = current.read_bytes()
    if (len(raw) != APPROVED_SIZE or not raw.startswith(b"\xff\xd8\xff")
            or hashlib.sha256(raw).hexdigest() != APPROVED_SHA256):
        raise StudioError("Approved Mia reference failed SHA-256 verification")
    return raw


def approved_status(workspace: Path) -> dict:
    try:
        content = approved_bytes(workspace)
        status = "ready" if content is not None else "missing"
    except (StudioError, OSError):
        status = "invalid"
    return {
        "character_id": "mia",
        "status": status,
        "approved": status == "ready",
        "title": "Мия — утверждённый разворот",
        "source": "Утверждённый исходник, не сгенерированный черновик",
        "views": list(VIEWS),
        "url": "/api/approved-reference-image/mia" if status == "ready" else None,
        "model_status": "3D-модель и риг ещё не утверждены",
        "note": ("Один исходный JPEG с несколькими ракурсами. "
                 "Только после визуальной проверки допускается 2.5D; "
                 "для свободной 3D-камеры требуется отдельная проверенная модель."),
    }


def attach_approved_mia(store: StudioStore, revision: int) -> dict:
    """Explicit action in Passport. Preserve all existing character metadata."""
    if type(revision) is not int:
        raise StudioError("Revision must be an integer")
    raw = approved_bytes(store.workspace)
    if raw is None:
        raise StudioError("Утверждённый референс не найден в локальных материалах первой серии")
    folder = store.root / "studio_media"
    _reject_link(folder)
    folder.mkdir(exist_ok=True)
    target = folder / MEDIA_FILENAME
    _reject_link(target)
    # A stable, content-addressed name means repeat use does not duplicate media.
    if target.exists():
        if target.read_bytes() != raw:
            raise StudioError("Existing canonical media filename does not match approved image")
    else:
        try:
            with target.open("xb") as output:
                output.write(raw)
                output.flush()
        except FileExistsError:
            if target.read_bytes() != raw:
                raise StudioError("Existing canonical media filename does not match approved image")
    state = store.load()
    if state["revision"] != revision:
        raise StudioConflict("Project changed: refresh Passport before linking reference")
    mia = next((character for character in state["characters"] if character["id"] == "mia"), None)
    if mia is None:
        raise StudioError("Mia character card is missing")
    if mia["reference"] == MEDIA_FILENAME:
        return state
    mia["reference"] = MEDIA_FILENAME
    return store.save(state, revision)
