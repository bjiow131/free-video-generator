from __future__ import annotations

from pathlib import Path

import pytest

from local_agent.attachments import (
    AttachmentExchangeError,
    GitHubAttachmentExchange,
    _remote_path,
    _safe_child,
)


def test_safe_child_rejects_path_traversal(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.png"
    with pytest.raises(AttachmentExchangeError):
        _safe_child(tmp_path, outside)


@pytest.mark.parametrize("path", [
    "../secret.png",
    "inbox/attachments/../../secret.png",
    "inbox\\attachments\\image.png",
    "/inbox/attachments/image.png",
    "inbox/attachments/program.exe",
    "results/image.png",
])
def test_remote_path_rejects_untrusted_paths(path: str) -> None:
    with pytest.raises(AttachmentExchangeError):
        _remote_path(path)


def test_remote_path_accepts_only_attachment_folder() -> None:
    assert _remote_path("inbox/attachments/mia.png") == "inbox/attachments/mia.png"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload
        self.headers = {}

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.headers = {}
        self.response = response

    def request(self, method: str, url: str, **kwargs):
        return self.response


def test_public_repository_is_refused_before_transfer() -> None:
    session = FakeSession(FakeResponse(200, {"private": False}))
    client = GitHubAttachmentExchange(
        "owner/mailbox", "not-a-real-token", session=session
    )
    with pytest.raises(AttachmentExchangeError, match="not confirmed private"):
        client._require_private_repo()


def test_private_repository_is_accepted() -> None:
    session = FakeSession(FakeResponse(200, {"private": True}))
    client = GitHubAttachmentExchange(
        "owner/mailbox", "not-a-real-token", session=session
    )
    client._require_private_repo()
    assert client._private_verified is True
