from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import pytest

from local_agent.scene01_reference_pack import (
    ASSETS,
    ReferencePackError,
    _safe_archive_members,
    download_scene01_reference_pack,
)


def test_reference_manifest_tracks_source_and_license(tmp_path: Path, monkeypatch):
    import local_agent.scene01_reference_pack as pack

    def fake_download(asset, target_dir):
        path = target_dir / asset["filename"]
        path.write_bytes(b"\xff\xd8\xff" + b"test-image")
        return {
            "id": asset["id"],
            "filename": asset["filename"],
            "status": "downloaded",
            "bytes": path.stat().st_size,
            "sha256": "test-hash",
            "source_page": asset["source_page"],
            "license": asset["license"],
        }

    monkeypatch.setattr(pack, "_download_one", fake_download)
    result = download_scene01_reference_pack(tmp_path / "library", include_character_pack=False)

    assert len(result["assets"]) == 3
    assert not result["failures"]
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert all(item["source_page"].startswith("https://") for item in manifest["assets"])
    assert all(item["license"] for item in manifest["assets"])
    assert "stylized_character_pack" not in {item["id"] for item in manifest["assets"]}


def test_reference_pack_rejects_symlinked_pack_folder(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (library / "scene01_reference_pack").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReferencePackError, match="символической ссылкой"):
        download_scene01_reference_pack(library, include_character_pack=False)


def test_archive_rejects_parent_traversal():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.txt", "not allowed")
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as archive:
        with pytest.raises(ReferencePackError, match="небезопасный путь"):
            _safe_archive_members(archive)


def test_archive_accepts_regular_member():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("characters/readme.txt", "ok")
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as archive:
        _safe_archive_members(archive)
