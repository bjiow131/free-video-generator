"""Safe import of versioned character passports into the desktop library.

Passport JSON is treated as data only: it is parsed and validated, never executed.
Original files are not modified.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_ALLOWED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_MAX_PASSPORT_BYTES = 2 * 1024 * 1024
_MAX_IMAGE_BYTES = 30 * 1024 * 1024
_MAX_BLEND_BYTES = 2 * 1024 * 1024 * 1024


class CharacterPassportImportError(ValueError):
    """Raised when an uploaded passport or its assets fail validation."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path_value: str | Path, *, suffixes: set[str], max_bytes: int) -> Path:
    path = Path(path_value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise CharacterPassportImportError("Файл отсутствует или является ссылкой.")
    if path.suffix.lower() not in suffixes:
        raise CharacterPassportImportError("Недопустимый тип файла.")
    if path.stat().st_size <= 0 or path.stat().st_size > max_bytes:
        raise CharacterPassportImportError("Недопустимый размер файла.")
    return path.resolve()


def _select_passport(payload: Any, character_id: str | None) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise CharacterPassportImportError("Паспорт должен быть JSON-объектом.")
    # Accept the registry produced by the local rig-audit workflow as well as a single passport.
    if isinstance(payload.get("characters"), dict):
        characters = payload["characters"]
        requested = character_id
        if not requested:
            if len(characters) != 1:
                raise CharacterPassportImportError("В реестре несколько персонажей: укажите ID персонажа.")
            requested = next(iter(characters))
        entry = characters.get(requested)
        if not isinstance(entry, dict) or not isinstance(entry.get("history"), list) or not entry["history"]:
            raise CharacterPassportImportError("В реестре нет истории паспорта для указанного персонажа.")
        passport = entry["history"][-1]
        if not isinstance(passport, dict):
            raise CharacterPassportImportError("Последняя версия паспорта повреждена.")
        character_id = str(passport.get("character_id") or requested)
    else:
        passport = payload
        character_id = str(passport.get("character_id") or character_id or "")
    if not _ID_RE.fullmatch(character_id or ""):
        raise CharacterPassportImportError("ID персонажа должен содержать латинские буквы, цифры, _ или -.")
    if passport.get("schema_version") not in (1, "1"):
        raise CharacterPassportImportError("Неподдерживаемая версия схемы паспорта.")
    return character_id, passport


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".passport-", suffix=".tmp", delete=False) as stream:
        temp = Path(stream.name)
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def import_character_passport(
    passport_path: str | Path,
    library_dir: str | Path,
    *,
    character_id: str | None = None,
    display_name: str | None = None,
    reference_paths: tuple[str | Path, ...] | list[str | Path] = (),
    blend_path: str | Path | None = None,
) -> dict[str, Any]:
    """Import a passport, preserving prior reference paths and version history."""
    source = _regular_file(passport_path, suffixes={".json"}, max_bytes=_MAX_PASSPORT_BYTES)
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CharacterPassportImportError("Не удалось прочитать корректный UTF-8 JSON.") from exc
    character_id, passport = _select_passport(payload, character_id)

    library = Path(library_dir).expanduser()
    library.mkdir(parents=True, exist_ok=True)
    library = library.resolve()
    if library.is_symlink():
        raise CharacterPassportImportError("Папка библиотеки не должна быть символической ссылкой.")
    card_dir = library / character_id
    if card_dir.is_symlink():
        raise CharacterPassportImportError("Папка персонажа не должна быть символической ссылкой.")
    card_dir.mkdir(parents=True, exist_ok=True)
    versions_dir = card_dir / "passport_versions"
    if versions_dir.is_symlink():
        raise CharacterPassportImportError("Папка версий не должна быть символической ссылкой.")
    versions_dir.mkdir(parents=True, exist_ok=True)

    versions = sorted(versions_dir.glob("v*.json"))
    next_version = len(versions) + 1
    version_path = versions_dir / f"v{next_version:04d}.json"
    if version_path.exists():
        raise CharacterPassportImportError("Файл следующей версии уже существует; импорт остановлен.")
    passport_copy = dict(passport)
    passport_copy.setdefault("character_id", character_id)
    _atomic_json(version_path, passport_copy)

    refs_added: list[str] = []
    refs_dir = card_dir / "references"
    for raw in reference_paths:
        image = _regular_file(raw, suffixes=_ALLOWED_IMAGES, max_bytes=_MAX_IMAGE_BYTES)
        destination = refs_dir / f"{len(refs_added) + 1:02d}_{image.name}"
        refs_dir.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination = refs_dir / f"{len(refs_added) + 1:02d}_{_sha256(image)[:10]}_{image.name}"
        shutil.copy2(image, destination)
        refs_added.append(str(destination))

    copied_blend = None
    if blend_path:
        blend = _regular_file(blend_path, suffixes={".blend"}, max_bytes=_MAX_BLEND_BYTES)
        model_dir = card_dir / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        destination = model_dir / blend.name
        if destination.exists():
            if _sha256(destination) != _sha256(blend):
                destination = model_dir / f"{blend.stem}_{_sha256(blend)[:10]}.blend"
        if not destination.exists():
            shutil.copy2(blend, destination)
        copied_blend = str(destination)

    database = library / "characters.json"
    lock = library / ".characters.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise CharacterPassportImportError("Библиотека занята другой операцией; повторите импорт позже.") from exc
    try:
        os.close(fd)
        if database.is_symlink():
            raise CharacterPassportImportError("Файл базы карточек не должен быть символической ссылкой.")
        if database.exists():
            if database.stat().st_size > _MAX_PASSPORT_BYTES * 4:
                raise CharacterPassportImportError("Файл библиотеки слишком велик.")
            try:
                cards = json.loads(database.read_text(encoding="utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise CharacterPassportImportError("Файл библиотеки повреждён; исходник не перезаписан.") from exc
            if not isinstance(cards, list):
                raise CharacterPassportImportError("Неизвестный формат файла библиотеки.")
        else:
            cards = []
        existing = next((item for item in cards if isinstance(item, dict) and item.get("id") == character_id), None)
        rig = passport.get("rig") if isinstance(passport.get("rig"), dict) else {}
        audit = passport.get("audit") if isinstance(passport.get("audit"), dict) else {}
        source_meta = passport.get("source") if isinstance(passport.get("source"), dict) else {}
        status = str(passport.get("status") or audit.get("status") or "passport_imported")
        card = dict(existing or {})
        card.update({
            "id": character_id,
            "name": (display_name or card.get("name") or passport.get("display_name") or passport.get("name") or character_id).strip(),
            "kind": card.get("kind", "Персонаж"),
            "profile_type": card.get("profile_type", "Человек"),
            "visual_style": card.get("visual_style", "По референсам / смешанный"),
            "description": card.get("description", ""),
            "references": list(card.get("references", [])) + refs_added,
            "passport_path": str(version_path),
            "passport_version": next_version,
            "passport_status": status,
            "passport_source_sha256": source_meta.get("sha256") or _sha256(source),
            "rig_summary": {
                "mesh_count": rig.get("mesh_count"),
                "armatures": rig.get("armatures", []),
                "shape_keys": rig.get("shape_keys", []),
                "facial_bones": rig.get("facial_bones", []),
                "mouth_related_drivers": rig.get("mouth_related_drivers", []),
                "audit_summary": audit.get("summary"),
            },
        })
        if copied_blend:
            card["blend_file"] = copied_blend
        if existing:
            cards[cards.index(existing)] = card
        else:
            cards.append(card)
        _atomic_json(database, cards)
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass

    return {
        "character_id": character_id,
        "name": card["name"],
        "passport_version": next_version,
        "passport_path": str(version_path),
        "status": status,
        "references_added": len(refs_added),
        "blend_file": copied_blend,
        "library_path": str(database),
    }
