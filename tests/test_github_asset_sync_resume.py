import hashlib
import json

from local_agent.github_asset_sync import sync_approved_assets


COMMIT = "7ced2288169e91db2758965999ad3e8d71d5be37"
DATA = b"passport"


class Response:
    def __init__(self, status, payload=None, content=b"", headers=None):
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
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_resumes_existing_partial_download(tmp_path):
    manifest = {
        "schema_version": 1,
        "repository": "bjiow131/free-video-generator",
        "commit_sha": COMMIT,
        "assets": [{
            "category": "character_passport",
            "path": "docs/season1/character_passports/mia.json",
            "destination": "assets/characters/passports/mia.json",
            "commit_sha": COMMIT,
            "sha256": hashlib.sha256(DATA).hexdigest(),
        }],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    project = tmp_path / "workspace/episode1"
    partial = project / "assets/characters/passports/mia.json.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(DATA[:3])
    raw_url = f"https://raw.githubusercontent.com/bjiow131/free-video-generator/{COMMIT}/docs/season1/character_passports/mia.json"
    metadata = {
        "type": "file",
        "path": "docs/season1/character_passports/mia.json",
        "size": len(DATA),
        "download_url": raw_url,
    }
    session = Session([
        Response(200, payload=metadata),
        Response(206, content=DATA[3:], headers={"Content-Range": f"bytes 3-{len(DATA)-1}/{len(DATA)}"}),
    ])
    result = sync_approved_assets(tmp_path / "workspace", "episode1", manifest_path, session=session)
    assert result["counts"] == {"downloaded": 1}
    assert (project / "assets/characters/passports/mia.json").read_bytes() == DATA
    assert session.calls[1][1]["headers"] == {"Range": "bytes=3-"}
