import io
import json
import urllib.error
from unittest.mock import Mock

import pytest

from scripts.inspect_wan2gp_api import (
    MAX_RESPONSE_BYTES, get_json, summarize_config, validate_local_url,
)


class Response:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body[:size]


def test_get_json_success(monkeypatch):
    monkeypatch.setattr("scripts.inspect_wan2gp_api.urllib.request.urlopen",
                        Mock(return_value=Response(b'{"version":"1"}')))
    status, result = get_json("http://127.0.0.1:7860", "/config", 1)
    assert status == 200 and result == {"version": "1"}


def test_http_error_is_reported_without_crashing(monkeypatch):
    error = urllib.error.HTTPError("http://127.0.0.1/config", 404, "Not Found", {}, None)
    monkeypatch.setattr("scripts.inspect_wan2gp_api.urllib.request.urlopen", Mock(side_effect=error))
    status, result = get_json("http://127.0.0.1", "/config", 1)
    assert status == 404 and result["_http_error"] == "Not Found"


def test_malformed_json_is_reported(monkeypatch):
    monkeypatch.setattr("scripts.inspect_wan2gp_api.urllib.request.urlopen",
                        Mock(return_value=Response(b"{not-json")))
    status, result = get_json("http://127.0.0.1", "/config", 1)
    assert status == 200 and result["_non_json_response"] is True


def test_connection_error_is_reported_without_url(monkeypatch):
    monkeypatch.setattr("scripts.inspect_wan2gp_api.urllib.request.urlopen",
                        Mock(side_effect=urllib.error.URLError("connection refused")))
    status, result = get_json("http://127.0.0.1", "/config", 1)
    assert status == 0 and "connection refused" in result["_connection_error"]


def test_oversized_response_is_rejected(monkeypatch):
    monkeypatch.setattr("scripts.inspect_wan2gp_api.urllib.request.urlopen",
                        Mock(return_value=Response(b"x" * (MAX_RESPONSE_BYTES + 1))))
    status, result = get_json("http://127.0.0.1", "/config", 1)
    assert status == 200 and result["_response_too_large"] is True


@pytest.mark.parametrize("url", [
    "https://example.com", "http://192.168.1.2:7860", "file:///tmp/config",
    "http://user:pass@127.0.0.1:7860", "http://127.0.0.1:7860/?token=secret",
])
def test_rejects_non_loopback_or_credential_urls(url):
    with pytest.raises(ValueError):
        validate_local_url(url)


def test_component_summary_omits_defaults():
    report = summarize_config({
        "components": [{"id": 1, "type": "Textbox", "props": {"label": "Prompt", "value": "private default"}}],
        "dependencies": [{"api_name": "generate", "inputs": [1], "outputs": [999]}],
    })
    rendered = json.dumps(report)
    assert "private default" not in rendered
    assert report["endpoints"][0]["api_name"] == "generate"
