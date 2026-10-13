"""Download only explicitly pinned public GitHub assets into a local project."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

import requests

_PUBLIC_REPOSITORY = "bjiow131/free-video-generator"
_PRIVATE_REFERENCE_REPOSITORY = "bjiow131/local-agent-mailbox"
_ALLOWED_REPOSITORIES = {_PUBLIC_REPOSITORY, _PRIVATE_REFERENCE_REPOSITORY}
_ALLOWED_CATEGORIES = {
    "character_reference", "character_passport", "animal_reference",
    "animal_passport", "prop", "environment",
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_MODEL_EXTENSIONS = {".blend", ".obj", ".fbx", ".glb", ".gltf", ".stl", ".abc", ".usd", ".usdz"}
_CATEGORY_EXTENSIONS = {
    "character_reference": _IMAGE_EXTENSIONS,
    "animal_reference": _IMAGE_EXTENSIONS,
    "character_passport": {".json"},
    "animal_passport": {".json"},
    "prop": _IMAGE_EXTENSIONS | _MODEL_EXTENSIONS,
    "environment": _IMAGE_EXTENSIONS | _MODEL_EXTENSIONS,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_FILE_BYTES = 100 * 1024 * 1024


class AssetSyncError(ValueError):
    """An asset manifest or destination is not safe to process."""


def _safe_relative(value: Any, *, asset_only: bool = False) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise AssetSyncError("invalid_relative_path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise AssetSyncError("unsafe_relative_path")
    if asset_only and (not path.parts or path.parts[0] != "assets"):
        raise AssetSyncError("destination_must_be_under_assets")
    return path


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AssetSyncError("manifest_missing_or_unsafe")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AssetSyncError("manifest_invalid") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise AssetSyncError("unsupported_manifest")
    if data.get("repository") not in _ALLOWED_REPOSITORIES:
        raise AssetSyncError("repository_not_allowlisted")
    commit = data.get("commit_sha")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AssetSyncError("commit_not_pinned")
    assets = data.get("assets")
    if not isinstance(assets, list) or len(assets) > 500:
        raise AssetSyncError("invalid_asset_list")
    seen: set[str] = set()
    for item in assets:
        if not isinstance(item, dict):
            raise AssetSyncError("invalid_asset_entry")
        if item.get("category") not in _ALLOWED_CATEGORIES:
            raise AssetSyncError("category_not_allowlisted")
        source = _safe_relative(item.get("path"))
        destination = _safe_relative(item.get("destination"), asset_only=True)
        allowed_extensions = _CATEGORY_EXTENSIONS[item["category"]]
        if source.suffix.lower() not in allowed_extensions or destination.suffix.lower() not in allowed_extensions:
            raise AssetSyncError("file_extension_not_allowed_for_category")
        digest = item.get("sha256")
        if not _SHA256.fullmatch(digest or ""):
            raise AssetSyncError("invalid_sha256")
        source_repository = item.get("source_repository", data["repository"])
        if source_repository not in _ALLOWED_REPOSITORIES:
            raise AssetSyncError("repository_not_allowlisted")
        source_commit = item.get("commit_sha", commit)
        if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
            raise AssetSyncError("asset_commit_mismatch")
        if source_repository == data["repository"] and source_commit != commit:
            raise AssetSyncError("asset_commit_mismatch")
        if source_repository == _PRIVATE_REFERENCE_REPOSITORY:
            if (item["category"] not in {"character_reference", "animal_reference", "prop", "environment"}
                    or source.suffix.lower() not in _IMAGE_EXTENSIONS):
                raise AssetSyncError("private_repository_category_not_allowed")
            review_status = item.get("review_status", "approved")
            if review_status not in {"approved", "draft"}:
                raise AssetSyncError("invalid_reference_review_status")
            if review_status == "draft" and destination.parts[:3] != ("assets", "references", "drafts"):
                raise AssetSyncError("draft_reference_destination_not_allowlisted")
        item["source_repository"] = source_repository
        item["commit_sha"] = source_commit
        key = destination.as_posix().casefold()
        if key in seen:
            raise AssetSyncError("duplicate_destination")
        seen.add(key)
    return data


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_path(root: Path, relative: PurePosixPath, *, create: bool = False) -> Path:
    root = root.resolve()
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise AssetSyncError("symlink_in_destination")
        if create:
            current.mkdir(exist_ok=True)
    target = current / relative.parts[-1]
    if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
        raise AssetSyncError("symlink_in_destination")
    if not target.resolve().is_relative_to(root):
        raise AssetSyncError("destination_escapes_project")
    return target


def _download_one(
    session: requests.Session,
    repository: str,
    commit: str,
    project: Path,
    asset: dict[str, Any],
    *,
    private_token: str | None = None,
) -> dict[str, str]:
    relative = _safe_relative(asset["destination"], asset_only=True)
    target = _check_path(project, relative, create=True)
    expected = asset["sha256"]
    if target.exists():
        return {
            "path": relative.as_posix(),
            "status": "duplicate" if _digest(target) == expected else "preserved_conflict",
        }

    repository = asset.get("source_repository", repository)
    commit = asset.get("commit_sha", commit)
    is_private = repository == _PRIVATE_REFERENCE_REPOSITORY
    if is_private and not private_token:
        raise AssetSyncError("private_repository_credential_unavailable")
    source = _safe_relative(asset["path"])
    api_url = (
        f"https://api.github.com/repos/{repository}/contents/"
        f"{quote(source.as_posix(), safe='/')}?ref={commit}"
    )
    try:
        api_headers = {"Authorization": f"Bearer {private_token}"} if is_private else None
        metadata_response = session.get(api_url, headers=api_headers, timeout=20, allow_redirects=False)
        if metadata_response.status_code != 200:
            raise AssetSyncError("github_metadata_unavailable")
        metadata = metadata_response.json()
        remote_size = metadata.get("size")
        pinned_size = asset.get("size_bytes")
        if (metadata.get("type") != "file" or metadata.get("path") != source.as_posix()
                or isinstance(remote_size, bool) or not isinstance(remote_size, int)
                or remote_size < 0 or remote_size > _MAX_FILE_BYTES
                or (pinned_size is not None and pinned_size != remote_size)):
            raise AssetSyncError("github_file_metadata_rejected")
        if is_private:
            if remote_size > 900_000 or metadata.get("encoding") != "base64":
                raise AssetSyncError("private_reference_size_or_encoding_rejected")
            try:
                encoded = "".join(metadata.get("content", "").split())
                raw = base64.b64decode(encoded, validate=True)
            except (AttributeError, TypeError, ValueError) as exc:
                raise AssetSyncError("private_reference_content_invalid") from exc
            if len(raw) != remote_size or hashlib.sha256(raw).hexdigest() != expected:
                raise AssetSyncError("sha256_mismatch")
            part = target.with_name(target.name + ".part")
            if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                raise AssetSyncError("unsafe_partial_file")
            with part.open("wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(part, target)
            except FileExistsError:
                return {
                    "path": relative.as_posix(),
                    "status": "duplicate" if _digest(target) == expected else "preserved_conflict",
                }
            except OSError as exc:
                raise AssetSyncError("atomic_install_unavailable") from exc
            part.unlink()
            return {"path": relative.as_posix(), "status": "downloaded"}
        raw_url = metadata.get("download_url")
        parsed = urlparse(raw_url or "")
        if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
            raise AssetSyncError("download_host_not_allowlisted")
        expected_url_path = f"/{repository}/{commit}/{source.as_posix()}"
        if parsed.path != expected_url_path:
            raise AssetSyncError("download_url_not_pinned")
        part = target.with_name(target.name + ".part")
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise AssetSyncError("unsafe_partial_file")
        offset = part.stat().st_size if part.exists() else 0
        if offset > _MAX_FILE_BYTES:
            part.unlink()
            offset = 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        response = session.get(
            raw_url, headers=headers, stream=True, timeout=60, allow_redirects=False
        )
        if response.status_code not in ({206} if offset else {200}):
            if offset and response.status_code == 200:
                offset = 0
            else:
                raise AssetSyncError("github_download_unavailable")
        if offset:
            content_range = response.headers.get("Content-Range", "")
            if not content_range.startswith(f"bytes {offset}-"):
                raise AssetSyncError("invalid_resume_range")
        mode = "ab" if offset else "wb"
        downloaded_bytes = offset
        too_large = False
        with part.open(mode) as stream:
            for chunk in response.iter_content(64 * 1024):
                if chunk:
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > _MAX_FILE_BYTES:
                        too_large = True
                        break
                    stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if too_large or part.stat().st_size > _MAX_FILE_BYTES:
            response.close()
            part.unlink(missing_ok=True)
            raise AssetSyncError("asset_too_large")
        if _digest(part) != expected:
            part.unlink(missing_ok=True)
            raise AssetSyncError("sha256_mismatch")
        try:
            # Hard-link creation is atomic and fails if another file appeared at
            # the destination after the initial existence check. Unlike
            # os.replace(), it cannot overwrite a concurrent local file.
            os.link(part, target)
        except FileExistsError:
            return {
                "path": relative.as_posix(),
                "status": "duplicate" if _digest(target) == expected else "preserved_conflict",
            }
        except OSError as exc:
            raise AssetSyncError("atomic_install_unavailable") from exc
        part.unlink()
        return {"path": relative.as_posix(), "status": "downloaded"}
    except requests.RequestException as exc:
        # Keep a partial file so a locally approved retry can resume it.
        return {"path": relative.as_posix(), "status": f"retryable_{type(exc).__name__}"}


def sync_approved_assets(
    workspace: str | Path,
    project_name: str,
    manifest_path: str | Path,
    *,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Sync pinned assets without replacing existing local files.

    The caller must enforce local approval before invoking this function.
    """
    if not isinstance(project_name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,47}", project_name):
        raise AssetSyncError("invalid_project_name")
    # Keep downloads confined to the existing pilot project or Octava Studio's configured season project.
    if project_name not in {"episode1", "mia_story"}:
        raise AssetSyncError("project_not_allowlisted")
    raw_root = Path(workspace).expanduser()
    if raw_root.is_symlink() or getattr(raw_root, "is_junction", lambda: False)():
        raise AssetSyncError("workspace_must_not_be_linked")
    root = raw_root.resolve()
    project = root / project_name
    if project.is_symlink() or getattr(project, "is_junction", lambda: False)():
        raise AssetSyncError("project_must_not_be_linked")
    project.mkdir(parents=True, exist_ok=True)
    if not project.resolve().is_relative_to(root):
        raise AssetSyncError("project_escapes_workspace")

    manifest = _load_manifest(Path(manifest_path))
    client = session or requests.Session()
    client.headers.update({
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "blender-agent-approved-asset-sync",
    })
    private_token = None
    if any(item.get("source_repository", manifest["repository"]) == _PRIVATE_REFERENCE_REPOSITORY
           for item in manifest["assets"]):
        try:
            from local_agent.windows_credentials import read_credential
            private_token = (read_credential() or "").strip()
        except (ImportError, OSError, RuntimeError) as exc:
            raise AssetSyncError("private_repository_credential_unavailable") from exc
        if not private_token:
            raise AssetSyncError("private_repository_credential_unavailable")
    results = []
    for item in manifest["assets"]:
        try:
            results.append(_download_one(
                client, manifest["repository"], manifest["commit_sha"], project, item,
                private_token=private_token,
            ))
        except AssetSyncError as exc:
            results.append({
                "path": str(item.get("destination", "")),
                "status": str(exc),
            })
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "status": "completed" if all(k in {"downloaded", "duplicate"} for k in counts) else "partial",
        "asset_count": len(results),
        "counts": counts,
        "assets": results,
        "downloaded_private_data": any(
            item.get("source_repository") == _PRIVATE_REFERENCE_REPOSITORY
            and result.get("status") == "downloaded"
            for item, result in zip(manifest["assets"], results, strict=True)
        ),
    }
