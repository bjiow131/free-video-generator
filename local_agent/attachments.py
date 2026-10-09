"""Bounded binary/text attachment exchange for a private GitHub mailbox.

This module deliberately refuses public repositories. It transfers only a small
allowlist of image and text formats, under caller-selected local roots. It is
not a general file browser or a way to execute downloaded content.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
from urllib.parse import quote

import requests

API_ROOT = "https://api.github.com"
ALLOWED_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".txt", ".md", ".json", ".yaml", ".yml",
})
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class AttachmentExchangeError(RuntimeError):
    """Safe, bounded attachment-transfer failure."""


def _safe_child(root: str | Path, candidate: str | Path) -> Path:
    """Resolve a path and require it to stay inside the explicitly allowed root."""
    allowed_root = Path(root).expanduser().resolve()
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = allowed_root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise AttachmentExchangeError("Path is outside the configured attachment folder.") from exc
    return resolved


def _remote_path(value: str) -> str:
    """Accept only a relative POSIX path inside inbox/attachments/."""
    if not isinstance(value, str) or "\\" in value or value.startswith("/"):
        raise AttachmentExchangeError("Invalid remote attachment path.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AttachmentExchangeError("Invalid remote attachment path.")
    if len(path.parts) < 3 or path.parts[:2] != ("inbox", "attachments"):
        raise AttachmentExchangeError("Remote path must be inside inbox/attachments/.")
    if Path(path.name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise AttachmentExchangeError("File type is not allowed for exchange.")
    return path.as_posix()


class GitHubAttachmentExchange:
    """Transfer approved attachments through a dedicated *private* GitHub repo.

    Reuse the mailbox token only on the local computer. Never place credentials
    or private reference images in a public project repository.
    """

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: int = 15,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
            raise AttachmentExchangeError("Repository must use owner/name format.")
        if not token or "\n" in token or "\r" in token:
            raise AttachmentExchangeError("GitHub token is missing or malformed.")
        self.repository = repository
        self.timeout_seconds = max(3, min(int(timeout_seconds), 60))
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "local-first-attachment-exchange",
        })
        self._private_verified = False

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        try:
            response = self.session.request(
                method, url, timeout=self.timeout_seconds, **kwargs
            )
        except requests.RequestException as exc:
            raise AttachmentExchangeError(
                f"GitHub network request failed ({type(exc).__name__})."
            ) from exc
        if response.status_code in (401, 403):
            raise AttachmentExchangeError("GitHub access denied; verify the token and repository permissions.")
        if response.status_code == 404:
            raise AttachmentExchangeError("Mailbox repository or attachment was not found.")
        if response.status_code == 429:
            raise AttachmentExchangeError("GitHub rate limit reached; retry later.")
        if not response.ok:
            raise AttachmentExchangeError(f"GitHub returned HTTP {response.status_code}.")
        return response

    def _require_private_repo(self) -> None:
        if self._private_verified:
            return
        response = self._request("GET", f"{API_ROOT}/repos/{self.repository}")
        try:
            info = response.json()
        except ValueError as exc:
            raise AttachmentExchangeError("Could not verify mailbox repository visibility.") from exc
        if info.get("private") is not True:
            raise AttachmentExchangeError(
                "Refusing file transfer: the mailbox repository is not confirmed private."
            )
        self._private_verified = True

    def upload(
        self,
        source: str | Path,
        *,
        allowed_root: str | Path,
        branch: str = "main",
        overwrite: bool = False,
    ) -> dict[str, str]:
        """Upload one allowlisted file located under allowed_root."""
        self._require_private_repo()
        path = _safe_child(allowed_root, source)
        if not path.is_file():
            raise AttachmentExchangeError("Source must be a regular file.")
        suffix = path.suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise AttachmentExchangeError("File type is not allowed for exchange.")
        if path.stat().st_size > MAX_ATTACHMENT_BYTES:
            raise AttachmentExchangeError("Attachment exceeds the 8 MiB limit.")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise AttachmentExchangeError(f"Could not read attachment ({type(exc).__name__}).") from exc
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise AttachmentExchangeError("Attachment exceeds the 8 MiB limit.")
        digest = hashlib.sha256(raw).hexdigest()
        safe_name = _SAFE_NAME.sub("_", path.name).strip("._")[:100] or ("attachment" + suffix)
        remote = f"inbox/attachments/{digest[:16]}-{safe_name}"
        api_url = f"{API_ROOT}/repos/{self.repository}/contents/{quote(remote, safe='/')}"
        body: dict[str, Any] = {
            "message": f"attachment: add {digest[:12]}",
            "content": base64.b64encode(raw).decode("ascii"),
            "branch": branch,
        }
        if not overwrite:
            try:
                self.session.get(api_url, params={"ref": branch}, timeout=self.timeout_seconds)
                existing = self.session.get(api_url, params={"ref": branch}, timeout=self.timeout_seconds)
            except requests.RequestException as exc:
                raise AttachmentExchangeError(f"GitHub network request failed ({type(exc).__name__}).") from exc
            if existing.status_code == 200:
                raise AttachmentExchangeError("Attachment already exists; use overwrite=True only intentionally.")
            if existing.status_code != 404:
                raise AttachmentExchangeError(f"GitHub returned HTTP {existing.status_code} while checking the destination.")
        response = self._request("PUT", api_url, json=body)
        try:
            commit = str(response.json()["commit"]["sha"])
        except (ValueError, KeyError, TypeError) as exc:
            raise AttachmentExchangeError("GitHub response did not include a commit SHA.") from exc
        return {"path": remote, "sha256": digest, "commit": commit}

    def download(
        self,
        remote_path: str,
        *,
        destination_root: str | Path,
        branch: str = "main",
        overwrite: bool = False,
    ) -> dict[str, str]:
        """Download one allowlisted file into destination_root; never execute it."""
        self._require_private_repo()
        remote = _remote_path(remote_path)
        url = f"{API_ROOT}/repos/{self.repository}/contents/{quote(remote, safe='/')}"
        response = self._request("GET", url, params={"ref": branch})
        try:
            item = response.json()
            if item.get("type") != "file" or item.get("encoding") != "base64":
                raise AttachmentExchangeError("Remote attachment must be a regular base64 file.")
            encoded = item["content"]
            if len(encoded) > ((MAX_ATTACHMENT_BYTES + 2) // 3) * 4 + 16_384:
                raise AttachmentExchangeError("Remote attachment exceeds the transfer limit.")
            raw = base64.b64decode(encoded, validate=False)
        except (ValueError, KeyError, TypeError) as exc:
            raise AttachmentExchangeError("Remote attachment content is invalid.") from exc
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise AttachmentExchangeError("Remote attachment exceeds the 8 MiB limit.")
        root = Path(destination_root).expanduser().resolve()
        target = _safe_child(root, root / PurePosixPath(remote).name)
        if target.exists() and not overwrite:
            raise AttachmentExchangeError("Destination already exists; refusing to overwrite.")
        root.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically in the destination directory, then replace only when permitted.
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".incoming-", suffix=".tmp", dir=root, delete=False
            ) as handle:
                temp_name = handle.name
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            temp = Path(temp_name)
            if target.exists() and not overwrite:
                raise AttachmentExchangeError("Destination appeared during download; refusing to overwrite.")
            temp.replace(target)
        except OSError as exc:
            raise AttachmentExchangeError(f"Could not save attachment ({type(exc).__name__}).") from exc
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
        return {"path": str(target), "sha256": hashlib.sha256(raw).hexdigest()}
