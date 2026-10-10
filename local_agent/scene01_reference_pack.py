"""Download a small, license-tracked reference pack for Scene 01.

Assets are fetched only after an explicit user click. Files are stored in the local
character library, not committed as binary files to the source repository.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request
import zipfile

PACK_ID = "scene01_snail_path"
USER_AGENT = "BlenderWorkAgent/0.6 (open reference pack downloader)"
MAX_IMAGE_BYTES = 18 * 1024 * 1024
MAX_ARCHIVE_BYTES = 40 * 1024 * 1024

ASSETS = (
    {
        "id": "snail_moss",
        "filename": "snail_moss_cc0.jpg",
        "kind": "image",
        "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Albino_snail_walking_on_green_moss.jpg",
        "source_page": "https://commons.wikimedia.org/wiki/File:Albino_snail_walking_on_green_moss.jpg",
        "license": "CC0 1.0",
        "purpose": "Snail shell, body and ground contact reference; real snail, not a stylized model.",
        "max_bytes": MAX_IMAGE_BYTES,
    },
    {
        "id": "snail_wood",
        "filename": "garden_snail_wood_cc0.jpg",
        "kind": "image",
        "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Garden_snail_on_wooden_fence.jpg",
        "source_page": "https://commons.wikimedia.org/wiki/File:Garden_snail_on_wooden_fence.jpg",
        "license": "CC0 1.0",
        "purpose": "Additional side/three-quarter snail anatomy reference.",
        "max_bytes": MAX_IMAGE_BYTES,
    },
    {
        "id": "woodland_path",
        "filename": "woodland_path_cc0.jpg",
        "kind": "image",
        "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Forest_path_along_wall.jpg",
        "source_page": "https://commons.wikimedia.org/wiki/File:Forest_path_along_wall.jpg",
        "license": "CC0 1.0",
        "purpose": "Environment and path composition reference; crop/reframe for a vertical shot.",
        "max_bytes": MAX_IMAGE_BYTES,
    },
    {
        "id": "stylized_character_pack",
        "filename": "opengameart_3d_character_pack.zip",
        "kind": "archive",
        "url": "https://opengameart.org/sites/default/files/bravos_game_br_part_3.zip",
        "source_page": "https://opengameart.org/content/3d-character-pack",
        "license": "CC0",
        "purpose": "Optional generic stylized rigged-character candidates. Inspect contents and rig before considering them for Mia; not a guaranteed age/style match.",
        "max_bytes": MAX_ARCHIVE_BYTES,
    },
)


class ReferencePackError(ValueError):
    """Reference pack could not be safely retrieved."""


def _safe_archive_members(archive: zipfile.ZipFile) -> None:
    for member in archive.infolist():
        normalized_name = member.filename.replace(chr(92), "/")
        path = Path(normalized_name)
        if path.is_absolute() or ".." in path.parts or (len(normalized_name) > 1 and normalized_name[1] == ":"):
            raise ReferencePackError("Архив содержит небезопасный путь; распаковка запрещена.")
        if member.file_size > 512 * 1024 * 1024:
            raise ReferencePackError("В архиве найден слишком большой файл.")
        # Symlinks are not needed in this asset pack and are rejected.
        if (member.external_attr >> 16) & 0o170000 == 0o120000:
            raise ReferencePackError("Архив содержит символическую ссылку; распаковка запрещена.")


def _download_one(asset: dict, target_dir: Path) -> dict:
    destination = target_dir / asset["filename"]
    if destination.is_symlink():
        raise ReferencePackError(f"Путь назначения является символической ссылкой: {asset['filename']}.")
    if destination.exists() and destination.is_file() and destination.stat().st_size > 0:
        return {
            "id": asset["id"], "filename": asset["filename"], "status": "already_present",
            "bytes": destination.stat().st_size, "sha256": _sha256(destination),
            "source_page": asset["source_page"], "license": asset["license"],
        }

    request = urllib.request.Request(asset["url"], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > asset["max_bytes"]:
                raise ReferencePackError(f"Файл {asset['filename']} превышает допустимый размер.")
            with tempfile.NamedTemporaryFile("wb", dir=target_dir, prefix=".download-", delete=False) as stream:
                temporary = Path(stream.name)
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > asset["max_bytes"]:
                        raise ReferencePackError(f"Файл {asset['filename']} превышает допустимый размер.")
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        try:
            temporary.unlink()
        except (UnboundLocalError, FileNotFoundError):
            pass
        if isinstance(exc, ReferencePackError):
            raise
        raise ReferencePackError(f"Не удалось скачать {asset['filename']}: {exc}") from exc

    try:
        if total <= 0:
            raise ReferencePackError(f"Источник вернул пустой файл: {asset['filename']}.")
        if asset["kind"] == "image":
            header = temporary.read_bytes()[:16]
            valid = header.startswith(b"\xff\xd8\xff") or header.startswith(b"\x89PNG\r\n\x1a\n") or header.startswith(b"RIFF") or header.startswith((b"II*\x00", b"MM\x00*"))
            if not valid:
                raise ReferencePackError(f"Источник не вернул изображение для {asset['filename']}.")
        elif asset["kind"] == "archive":
            if not zipfile.is_zipfile(temporary):
                raise ReferencePackError("Архив персонажей не является корректным ZIP-файлом.")
            with zipfile.ZipFile(temporary) as archive:
                _safe_archive_members(archive)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

    return {
        "id": asset["id"], "filename": asset["filename"], "status": "downloaded",
        "bytes": destination.stat().st_size, "sha256": _sha256(destination),
        "source_page": asset["source_page"], "license": asset["license"],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_scene01_reference_pack(library_dir: str | Path, *, include_character_pack: bool = True) -> dict:
    """Download licensed references after explicit user action and record provenance."""
    root = Path(library_dir).expanduser()
    if root.is_symlink():
        raise ReferencePackError("Папка библиотеки не должна быть символической ссылкой.")
    root.mkdir(parents=True, exist_ok=True)
    pack_dir = root / "scene01_reference_pack"
    if pack_dir.is_symlink():
        raise ReferencePackError("Папка набора референсов не должна быть символической ссылкой.")
    pack_dir.mkdir(parents=True, exist_ok=True)

    selected = [asset for asset in ASSETS if include_character_pack or asset["kind"] != "archive"]
    results = []
    failures = []
    for asset in selected:
        try:
            results.append(_download_one(asset, pack_dir))
        except ReferencePackError as exc:
            failures.append({"id": asset["id"], "filename": asset["filename"], "error": str(exc),
                             "source_page": asset["source_page"], "license": asset["license"]})

    manifest = {
        "schema_version": 1,
        "pack_id": PACK_ID,
        "title": "Scene 01 — Snail on the Path",
        "note": "Reference material only. Photos are not 3D assets. The optional OpenGameArt archive is a generic character pack and must be reviewed before use.",
        "assets": results,
        "failures": failures,
    }
    manifest_path = pack_dir / "manifest.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=pack_dir, prefix=".manifest-", suffix=".tmp", delete=False) as stream:
        temporary_manifest = Path(stream.name)
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_manifest, manifest_path)
    manifest["manifest_path"] = str(manifest_path)
    manifest["pack_dir"] = str(pack_dir)
    return manifest
