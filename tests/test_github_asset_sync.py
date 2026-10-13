import hashlib
import base64
import json
from pathlib import Path

import pytest
import requests

from local_agent import github_asset_sync as asset_sync
from local_agent.github_asset_sync import AssetSyncError, sync_approved_assets


COMMIT = "7ced2288169e91db2758965999ad3e8d71d5be37"
DATA = b"passport"
DIGEST = hashlib.sha256(DATA).hexdigest()


class Response:
    def __init__(self, status, *, payload=None, content=DATA, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self._content = content
        self.headers = headers or {}

    def json(self):
        return self._payload

    def iter_content(self, chunk_size):
        yield self._content


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}

    def get(self, *args, **kwargs):
        return self.responses.pop(0)


def make_manifest(tmp_path, **changes):
    item = {
        "category": "character_passport",
        "asset_id": "mia",
        "path": "docs/season1/character_passports/mia.json",
        "destination": "assets/characters/passports/mia.json",
        "commit_sha": COMMIT,
        "sha256": DIGEST,
    }
    item.update(changes)
    manifest = {
        "schema_version": 1,
        "repository": "bjiow131/free-video-generator",
        "commit_sha": COMMIT,
        "assets": [item],
    }
    path = tmp_path / "asset_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def session_for(data=DATA):
    metadata = {
        "type": "file",
        "path": "docs/season1/character_passports/mia.json",
        "size": len(data),
        "download_url": f"https://raw.githubusercontent.com/bjiow131/free-video-generator/{COMMIT}/docs/season1/character_passports/mia.json",
    }
    return Session([Response(200, payload=metadata), Response(200, content=data)])


def test_downloads_pinned_file_and_is_idempotent(tmp_path):
    manifest = make_manifest(tmp_path)
    workspace = tmp_path / "workspace"
    result = sync_approved_assets(workspace, "episode1", manifest, session=session_for())
    target = workspace / "episode1/assets/characters/passports/mia.json"
    assert result["counts"] == {"downloaded": 1}
    assert target.read_bytes() == DATA
    again = sync_approved_assets(workspace, "episode1", manifest, session=Session([]))
    assert again["counts"] == {"duplicate": 1}


def test_existing_different_file_is_preserved(tmp_path):
    manifest = make_manifest(tmp_path)
    workspace = tmp_path / "workspace"
    target = workspace / "episode1/assets/characters/passports/mia.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user file")
    result = sync_approved_assets(workspace, "episode1", manifest, session=Session([]))
    assert result["counts"] == {"preserved_conflict": 1}
    assert target.read_bytes() == b"user file"


@pytest.mark.parametrize("changes", [
    {"path": "../secret"},
    {"destination": "outside/file.json"},
    {"commit_sha": "0" * 40},
    {"category": "unknown"},
])
def test_rejects_untrusted_manifest_fields(tmp_path, changes):
    manifest = make_manifest(tmp_path, **changes)
    with pytest.raises(AssetSyncError):
        sync_approved_assets(tmp_path / "workspace", "episode1", manifest, session=Session([]))


def test_project_name_is_fixed_before_creating_workspace_path(tmp_path):
    workspace = tmp_path / "workspace"
    with pytest.raises(AssetSyncError, match="project_not_allowlisted"):
        sync_approved_assets(workspace, "other-project", make_manifest(tmp_path), session=Session([]))
    assert not workspace.exists()


def test_concurrent_destination_file_is_preserved(tmp_path, monkeypatch):
    manifest = make_manifest(tmp_path)
    workspace = tmp_path / "workspace"
    user_bytes = b"created by another local process"
    real_link = asset_sync.os.link

    def create_conflict_then_link(source, destination):
        Path(destination).write_bytes(user_bytes)
        return real_link(source, destination)

    monkeypatch.setattr(asset_sync.os, "link", create_conflict_then_link)
    result = sync_approved_assets(workspace, "episode1", manifest, session=session_for())
    target = workspace / "episode1/assets/characters/passports/mia.json"
    assert result["counts"] == {"preserved_conflict": 1}
    assert target.read_bytes() == user_bytes


def test_rejects_redirects_and_bad_digest_without_creating_target(tmp_path):
    manifest = make_manifest(tmp_path)
    redirect = Session([Response(302)])
    result = sync_approved_assets(tmp_path / "workspace", "episode1", manifest, session=redirect)
    assert result["counts"] == {"github_metadata_unavailable": 1}

    bad = make_manifest(tmp_path, sha256="0" * 64)
    result = sync_approved_assets(tmp_path / "workspace", "episode1", bad, session=session_for())
    assert result["counts"] == {"sha256_mismatch": 1}
    assert not (tmp_path / "workspace/episode1/assets/characters/passports/mia.json").exists()


def test_downloads_pinned_private_mia_reference_with_auth_only_on_api_request(tmp_path, monkeypatch):
    private_commit = "a" * 40
    private_path = "private_assets/mia/mia_turnaround_approved_20261012.jpeg"
    destination = "assets/references/mia_turnaround_approved_20261012.jpeg"
    image_bytes = b"approved-mia-reference"
    digest = hashlib.sha256(image_bytes).hexdigest()
    manifest = make_manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["assets"] = [{
        "category": "character_reference",
        "asset_id": "mia-turnaround-20261012",
        "source_repository": "bjiow131/local-agent-mailbox",
        "path": private_path,
        "destination": destination,
        "commit_sha": private_commit,
        "size_bytes": len(image_bytes),
        "sha256": digest,
    }]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    response = Response(200, payload={
        "type": "file", "path": private_path, "size": len(image_bytes),
        "encoding": "base64", "content": base64.b64encode(image_bytes).decode("ascii"),
    })

    class RecordingSession(Session):
        def __init__(self):
            super().__init__([response])
            self.calls = []

        def get(self, url, *args, **kwargs):
            self.calls.append((url, kwargs))
            return super().get(url, *args, **kwargs)

    session = RecordingSession()
    monkeypatch.setattr("local_agent.windows_credentials.read_credential", lambda: "test-private-token")
    workspace = tmp_path / "workspace"
    result = sync_approved_assets(workspace, "episode1", manifest, session=session)

    assert result["counts"] == {"downloaded": 1}
    assert result["downloaded_private_data"] is True
    assert (workspace / "episode1" / destination).read_bytes() == image_bytes
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url.startswith("https://api.github.com/repos/bjiow131/season1-private-bible/")
    assert kwargs["headers"] == {"Authorization": "Bearer test-private-token"}


def test_syncs_private_environment_draft_only_into_draft_reference_folder(tmp_path, monkeypatch):
    private_commit = "c" * 40
    private_path = "private_assets/season1/generated/forest_gate_draft.jpg"
    destination = "assets/references/drafts/set.forest_gate.jpg"
    image_bytes = b"draft-jpeg-reference"
    digest = hashlib.sha256(image_bytes).hexdigest()
    manifest = make_manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["assets"] = [{
        "category": "environment",
        "asset_id": "set.forest_gate",
        "source_repository": "bjiow131/local-agent-mailbox",
        "path": private_path,
        "destination": destination,
        "commit_sha": private_commit,
        "size_bytes": len(image_bytes),
        "sha256": digest,
        "review_status": "draft",
    }]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    response = Response(200, payload={
        "type": "file", "path": private_path, "size": len(image_bytes),
        "encoding": "base64", "content": base64.b64encode(image_bytes).decode("ascii"),
    })

    class RecordingSession(Session):
        def __init__(self):
            super().__init__([response])
            self.calls = []
        def get(self, url, *args, **kwargs):
            self.calls.append((url, kwargs))
            return super().get(url, *args, **kwargs)

    session = RecordingSession()
    monkeypatch.setattr("local_agent.windows_credentials.read_credential", lambda: "test-private-token")
    workspace = tmp_path / "workspace"
    result = sync_approved_assets(workspace, "episode1", manifest, session=session)
    assert result["counts"] == {"downloaded": 1}
    assert result["downloaded_private_data"] is True
    assert (workspace / "episode1" / destination).read_bytes() == image_bytes
    assert session.calls[0][0].startswith(
        "https://api.github.com/repos/bjiow131/local-agent-mailbox/contents/"
    )
    assert session.calls[0][1]["headers"] == {"Authorization": "Bearer test-private-token"}


def test_private_draft_manifest_rejects_non_draft_destination(tmp_path):
    manifest = make_manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    item = data["assets"][0]
    item.update({
        "category": "environment",
        "source_repository": "bjiow131/local-agent-mailbox",
        "path": "private_assets/season1/generated/forest_gate_draft.jpg",
        "destination": "assets/environments/set.forest_gate.jpg",
        "commit_sha": "c" * 40,
        "review_status": "draft",
    })
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AssetSyncError, match="draft_reference_destination_not_allowlisted"):
        asset_sync._load_manifest(manifest)

def test_studio_project_is_explicitly_allowlisted_for_pinned_sync(tmp_path):
    manifest = make_manifest(tmp_path)
    workspace = tmp_path / "workspace"
    result = sync_approved_assets(workspace, "mia_story", manifest, session=session_for())
    target = workspace / "mia_story/assets/characters/passports/mia.json"
    assert result["counts"] == {"downloaded": 1}
    assert target.read_bytes() == DATA
