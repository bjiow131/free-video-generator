"""GitHub mailbox transport for the local Windows agent.

This module only reads a desired-task manifest and publishes sanitized result
JSON. It does not execute tasks and does not store credentials on disk.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from typing import Any
from urllib.parse import quote

import requests

from local_agent.control_protocol import ProtocolError, TaskEnvelope, parse_task
from local_agent.reporting import _redact_value

API_ROOT = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 10
MAX_MANIFEST_BYTES = 16_384
MAX_RESULT_BYTES = 64_000


class QueueConfigurationError(RuntimeError):
    """Raised when required mailbox configuration is absent or malformed."""


class QueueTransportError(RuntimeError):
    """Raised for GitHub API/network failures without leaking response bodies."""


@dataclass(frozen=True)
class QueueConfig:
    repository: str
    token: str
    ref: str = "main"
    manifest_path: str = "queue/desired_task.json"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_environment(cls) -> "QueueConfig":
        repository = os.environ.get("LOCAL_AGENT_GITHUB_REPO", "").strip()
        token = os.environ.get("LOCAL_AGENT_GITHUB_TOKEN", "").strip()
        ref = os.environ.get("LOCAL_AGENT_GITHUB_REF", "main").strip() or "main"
        path = os.environ.get("LOCAL_AGENT_GITHUB_MANIFEST", "queue/desired_task.json").strip()
        if not repository or "/" not in repository or repository.startswith("/") or repository.endswith("/"):
            raise QueueConfigurationError("Set LOCAL_AGENT_GITHUB_REPO to owner/private-repo.")
        if not token:
            raise QueueConfigurationError("GitHub token is not configured.")
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise QueueConfigurationError("Invalid manifest path.")
        return cls(repository=repository, token=token, ref=ref, manifest_path=path)


class GitHubQueueClient:
    """Small REST client. Use only with a dedicated private mailbox repository."""

    def __init__(self, config: QueueConfig, *, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {config.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "local-first-windows-agent",
        })

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{API_ROOT}/repos/{self.config.repository}/{path.lstrip('/')}"
        try:
            response = self.session.request(method, url, timeout=self.config.timeout_seconds, **kwargs)
        except requests.RequestException as exc:
            raise QueueTransportError(f"GitHub request failed: {type(exc).__name__}") from exc
        if response.status_code == 404:
            raise QueueTransportError("Mailbox item not found; check repository, ref, and path.")
        if response.status_code in (401, 403):
            if response.headers.get("X-RateLimit-Remaining") == "0":
                raise QueueTransportError("GitHub API rate limit reached; back off before retrying.")
            raise QueueTransportError("GitHub access denied; check token scope and private-repo access.")
        if response.status_code == 429:
            raise QueueTransportError("GitHub API rate limit reached; back off before retrying.")
        if not response.ok:
            raise QueueTransportError(f"GitHub API returned HTTP {response.status_code}.")
        return response

    def fetch_desired_task(self) -> tuple[TaskEnvelope, str] | None:
        """Fetch and validate the single latest desired task; return its file SHA."""
        path = quote(self.config.manifest_path, safe="/")
        response = self._request("GET", f"contents/{path}", params={"ref": self.config.ref})
        try:
            item = response.json()
            if item.get("type") != "file" or item.get("encoding") != "base64":
                raise QueueTransportError("Task manifest must be a regular base64-encoded file.")
            raw_bytes = base64.b64decode(item["content"], validate=False)
            if len(raw_bytes) > MAX_MANIFEST_BYTES:
                raise QueueTransportError("Task manifest exceeds the size limit.")
            raw = raw_bytes.decode("utf-8")
            task = parse_task(raw)
            return task, str(item["sha"])
        except (ValueError, KeyError, TypeError, UnicodeError, ProtocolError) as exc:
            raise QueueTransportError(f"Task manifest rejected: {type(exc).__name__}") from exc

    def publish_result(self, task_id: str, result: dict[str, Any]) -> str:
        """Publish bounded, redacted JSON into queue/results/<id>.json."""
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        if not task_id or any(c not in allowed for c in task_id):
            raise QueueConfigurationError("Invalid task ID for result path.")
        safe_result = _redact_value(result)
        payload = json.dumps(safe_result, ensure_ascii=False, indent=2)
        encoded_bytes = payload.encode("utf-8")
        if len(encoded_bytes) > MAX_RESULT_BYTES:
            raise QueueConfigurationError("Result exceeds the size limit.")
        path = f"queue/results/{task_id}.json"
        api_path = f"contents/{quote(path, safe='/')}"
        body: dict[str, Any] = {
            "message": f"agent: result for {task_id}",
            "content": base64.b64encode(encoded_bytes).decode("ascii"),
            "branch": self.config.ref,
        }
        try:
            existing = self.session.get(
                f"{API_ROOT}/repos/{self.config.repository}/{api_path}",
                headers=self.session.headers,
                params={"ref": self.config.ref},
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise QueueTransportError(f"GitHub request failed: {type(exc).__name__}") from exc
        if existing.status_code == 200:
            try:
                body["sha"] = existing.json()["sha"]
            except (ValueError, KeyError, TypeError) as exc:
                raise QueueTransportError("Could not read existing result metadata.") from exc
        elif existing.status_code != 404:
            raise QueueTransportError(f"GitHub API returned HTTP {existing.status_code}.")
        response = self._request("PUT", api_path, json=body)
        try:
            return str(response.json()["commit"]["sha"])
        except (ValueError, KeyError, TypeError) as exc:
            raise QueueTransportError("GitHub accepted result but returned an unexpected response.") from exc
