"""Opt-in, pinned-commit, rollback-capable GitHub software updater.

Only code already committed to the fixed owner repository may be installed.
An incoming mailbox manifest is data; it never supplies shell commands,
script content, arbitrary URLs, destinations or test command lines.
"""
from __future__ import annotations

import ast
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPO = "bjiow131/free-video-generator"
MANIFEST_PATH = "queue/desired_update.json"
OPT_IN = ROOT / ".local_agent" / "trusted_updates_enabled.json"
STATE_DIR = ROOT / ".local_agent" / "trusted_updates"
RECOVERY = ROOT / ".local_agent" / "trusted_update_recovery.json"
MAX_FILE_BYTES = 500_000
MAX_FILES = 12
# Deliberately excludes credentials, secrets, scripts with arbitrary paths,
# updater itself, and the Windows Credential Manager.
ALLOWED_FILES = frozenset({
    "run_github_mailbox_agent.bat",
    "run_blender_studio.bat",
    "local_agent/poller.py",
    "local_agent/control_protocol.py",
    "local_agent/github_asset_sync.py",
    "docs/season1/asset_sync_manifest.json",
    "tests/test_github_asset_sync.py",
    "tests/test_github_asset_sync_resume.py",
    "tests/test_asset_sync_protocol.py",
    "tests/test_mailbox_policy.py",
    "local_agent/blender_bridge.py",
    "local_agent/blender_workflow.py",
    "local_agent/blender_rigging.py",
    "local_agent/blender_locator.py",
    "local_agent/mailbox_policy.py",
    "local_agent/dropbox_review.py",
    "local_agent/studio_jobs.py",
    "tests/test_dropbox_review.py",
    "local_agent/studio_server.py",
    "local_agent/studio_static/app.js",
    "local_agent/studio_static/style.css",
    "local_agent/studio_static/index.html",
    "tests/test_trusted_updates.py",
    "tests/test_poller.py",
})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,59}\Z")
_SHA1 = re.compile(r"[a-f0-9]{40}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")


class TrustedUpdateError(ValueError):
    """User-visible, credential-free update error."""


def _safe(path: Path) -> Path:
    root = ROOT.resolve()
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise TrustedUpdateError("Update path is a symlink or junction")
    if not path.resolve().is_relative_to(root):
        raise TrustedUpdateError("Update path leaves installation")
    return path


def _private_dir(path: Path) -> Path:
    _safe(path.parent)
    _safe(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_opt_in() -> dict[str, bool]:
    _safe(OPT_IN)
    try:
        raw = OPT_IN.read_bytes()
    except FileNotFoundError:
        return {"enabled": False}
    except OSError as exc:
        raise TrustedUpdateError("Cannot read local update permission") from exc
    if len(raw) > 120:
        raise TrustedUpdateError("Invalid local update permission size")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise TrustedUpdateError("Invalid local update permission") from exc
    if not isinstance(data, dict) or set(data) != {"enabled"} or type(data["enabled"]) is not bool:
        raise TrustedUpdateError("Invalid local update permission")
    return data


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    _private_dir(path.parent)
    _safe(path)
    raw = (json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode()
    if len(raw) > 8192:
        raise TrustedUpdateError("Update state is too large")
    with tempfile.NamedTemporaryFile(prefix=".trusted-update-", suffix=".tmp",
                                     dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        try:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def set_opt_in(value: dict[str, bool]) -> dict[str, bool]:
    if not isinstance(value, dict) or set(value) != {"enabled"} or type(value["enabled"]) is not bool:
        raise TrustedUpdateError("Expected one boolean enabled field")
    _write_json(OPT_IN, value)
    return value


def parse_manifest(raw: bytes, *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(raw, bytes) or len(raw) > 10000:
        raise TrustedUpdateError("Invalid update manifest size")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise TrustedUpdateError("Invalid update manifest JSON") from exc
    required = {"schema_version", "update_id", "created_at", "expires_at",
                "source_repo", "commit_sha", "files"}
    if not isinstance(data, dict) or set(data) != required:
        raise TrustedUpdateError("Update manifest fields not recognized")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise TrustedUpdateError("Unsupported update schema")
    if not isinstance(data["update_id"], str) or not _ID.fullmatch(data["update_id"]):
        raise TrustedUpdateError("Unsafe update ID")
    if data["source_repo"] != SOURCE_REPO:
        raise TrustedUpdateError("Untrusted code source")
    if not isinstance(data["commit_sha"], str) or not _SHA1.fullmatch(data["commit_sha"]):
        raise TrustedUpdateError("Update must use a pinned full commit SHA")
    try:
        created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise TrustedUpdateError("Invalid update timestamp") from exc
    current = now or datetime.now(timezone.utc)
    if (created.tzinfo is None or expires.tzinfo is None or
            created > current.replace(microsecond=0) + __import__("datetime").timedelta(minutes=5) or
            expires <= current or expires <= created or
            (expires - created).total_seconds() > 86400):
        raise TrustedUpdateError("Update expired or timestamps out of bounds")
    files = data["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise TrustedUpdateError("Invalid update file count")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise TrustedUpdateError("Invalid update file entry")
        path, digest = entry["path"], entry["sha256"]
        if not isinstance(path, str) or path not in ALLOWED_FILES or path in seen:
            raise TrustedUpdateError("Disallowed or duplicate update path")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise TrustedUpdateError("Invalid update file hash")
        seen.add(path)
    return data


def _fetch_manifest(client: Any) -> tuple[dict[str, Any], str] | None:
    from local_agent.github_queue import QueueTransportError
    client._require_private_repo()
    try:
        response = client._request("GET", "contents/" + MANIFEST_PATH,
                                   params={"ref": client.config.ref})
    except QueueTransportError as exc:
        if "Mailbox item not found" in str(exc):
            return None
        raise
    item = response.json()
    if not isinstance(item, dict) or item.get("encoding") != "base64":
        raise TrustedUpdateError("Malformed update manifest from GitHub")
    try:
        raw = base64.b64decode("".join(item["content"].split()), validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise TrustedUpdateError("Invalid update manifest encoding") from exc
    return parse_manifest(raw), str(item["sha"])


def _fetch_pinned(path: str, commit_sha: str, digest: str) -> bytes:
    # Public raw content avoids the unauthenticated GitHub REST API rate limit.
    # Integrity still comes only from the locally validated pinned commit and SHA-256.
    url = "https://raw.githubusercontent.com/" + SOURCE_REPO + "/" + commit_sha + "/" + quote(path, safe="/")
    try:
        response = requests.get(url, timeout=20, allow_redirects=False,
                                headers={"User-Agent": "blender-agent-pinned-updater"})
        if response.status_code != 200:
            raise TrustedUpdateError("Cannot fetch pinned update file from trusted GitHub repository")
        raw = response.content
        if len(raw) > MAX_FILE_BYTES:
            raise TrustedUpdateError("GitHub file response is too large")
    except requests.RequestException as exc:
        raise TrustedUpdateError("Pinned GitHub download failed") from exc
    if len(raw) > MAX_FILE_BYTES or hashlib.sha256(raw).hexdigest() != digest:
        raise TrustedUpdateError("Pinned update file digest mismatch")
    if path.endswith(".py"):
        try:
            ast.parse(raw.decode("utf-8"), filename=path)
        except (SyntaxError, UnicodeError) as exc:
            raise TrustedUpdateError("Python update failed syntax validation") from exc
    return raw


def recover_interrupted() -> bool:
    """Undo interrupted writes before processing another update; never auto-replay."""
    _safe(RECOVERY)
    if not RECOVERY.exists():
        return False
    try:
        data = json.loads(RECOVERY.read_text("utf-8"))
        files = data["files"]
        backup = _safe(ROOT / ".local_agent" / "trusted_updates" / data["update_id"] / "backup")
        if not isinstance(files, list) or not isinstance(data["update_id"], str) or not _ID.fullmatch(data["update_id"]):
            raise ValueError("invalid recovery")
        for item in files:
            if not isinstance(item, dict) or set(item) != {"path", "existed"} or item["path"] not in ALLOWED_FILES or type(item["existed"]) is not bool:
                raise ValueError("invalid recovery paths")
            dest = _safe(ROOT / item["path"])
            if item["existed"]:
                saved = _safe(backup / item["path"])
                if not saved.is_file():
                    raise TrustedUpdateError("Backup missing; manual recovery required")
                shutil.copy2(saved, dest)
            else:
                dest.unlink(missing_ok=True)
        RECOVERY.unlink()
        return True
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TrustedUpdateError("Interrupted update requires local recovery") from exc


def apply_update(data: dict[str, Any], *, fetch_file=_fetch_pinned, run_tests=True) -> dict[str, Any]:
    """Stage/verify everything first, atomically copy files, then validate and rollback."""
    uid = data["update_id"]
    folder = _private_dir(STATE_DIR / uid)
    _safe(RECOVERY)
    if RECOVERY.exists():
        raise TrustedUpdateError("Interrupted update must be recovered first")
    staged = _private_dir(folder / "staged")
    backup = _private_dir(folder / "backup")
    prepared = []
    for file in data["files"]:
        path = file["path"]
        dest = _safe(ROOT / path)
        for parent in [dest.parent, *list(dest.parents)[:-1]]:
            if parent == ROOT.parent:
                break
            _safe(parent)
        content = fetch_file(path, data["commit_sha"], file["sha256"])
        stage = _safe(staged / path)
        stage.parent.mkdir(parents=True, exist_ok=True)
        stage.write_bytes(content)
        existed = dest.is_file()
        if dest.exists() and not existed:
            raise TrustedUpdateError("Update destination is not a regular file")
        if existed:
            saved = _safe(backup / path)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, saved)
        prepared.append({"path": path, "existed": existed})
    _write_json(RECOVERY, {"update_id": uid, "files": prepared})
    try:
        for item in prepared:
            dest = _safe(ROOT / item["path"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = _safe(staged / item["path"])
            # Keep update temp on the same drive for Windows atomic rename.
            temp = dest.parent / (".trusted-" + uid + ".tmp")
            _safe(temp)
            shutil.copy2(src, temp)
            os.replace(temp, dest)
        if run_tests:
            command = [sys.executable, "-m", "pytest", "-q",
                       "tests/test_trusted_updates.py", "tests/test_unattended_poller.py"]
            try:
                result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                        text=True, timeout=240, check=False,
                                        stdin=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise TrustedUpdateError("Updated code validation could not finish") from exc
            if result.returncode != 0:
                raise TrustedUpdateError("Updated code regression tests failed")
        RECOVERY.unlink()
        return {"status": "completed", "update_id": uid, "files_updated": len(prepared),
                "source_commit": data["commit_sha"], "restart_needed": True,
                "backup_dir": str(backup)}
    except BaseException:
        # Recover from partial copies or failed tests using an independent backup.
        recover_interrupted()
        raise


def process_pending(client: Any, *, publish=None) -> dict[str, Any] | None:
    if not get_opt_in()["enabled"]:
        return None
    recover_interrupted()
    fetched = _fetch_manifest(client)
    if fetched is None:
        return None
    data, manifest_sha = fetched
    state_path = _safe(STATE_DIR / (data["update_id"] + ".json"))
    if state_path.exists():
        old = json.loads(state_path.read_text("utf-8"))
        if old.get("manifest_sha") != manifest_sha:
            raise TrustedUpdateError("Update ID reused with a changed manifest")
        return None
    # Durable claim happens before any file is changed. A restart never
    # applies the same update twice, even if result publication failed.
    _write_json(state_path, {"manifest_sha": manifest_sha, "status": "in_progress"})
    try:
        result = apply_update(data)
    except Exception as exc:
        result = {"status": "failed", "update_id": data["update_id"],
                  "reason": str(exc) if isinstance(exc, TrustedUpdateError) else type(exc).__name__}
    _write_json(state_path, {"manifest_sha": manifest_sha, "status": result["status"]})
    if publish is not None:
        publish("update-" + data["update_id"], {"task_id": "update-" + data["update_id"], **result})
    return result
