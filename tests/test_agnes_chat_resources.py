import pytest
import requests

from core.api.agnes_chat import AgnesChatAPI


def test_chat_closes_response_on_success(monkeypatch):
    class Response:
        status_code = 200
        headers = {}
        text = ""
        def __init__(self):
            self.closed = False
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": []}
        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(requests, "post", lambda *a, **k: response)
    monkeypatch.setattr("core.api.agnes_chat.get_rate_limiter", lambda: type("L", (), {"acquire": lambda self: None})())

    AgnesChatAPI("test")._request_with_retry({})
    assert response.closed is True


def test_chat_closes_response_on_nonretryable_http_error(monkeypatch):
    class Response:
        status_code = 400
        headers = {}
        text = "bad"
        def __init__(self):
            self.closed = False
        def raise_for_status(self):
            raise requests.HTTPError("bad")
        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(requests, "post", lambda *a, **k: response)
    monkeypatch.setattr("core.api.agnes_chat.get_rate_limiter", lambda: type("L", (), {"acquire": lambda self: None})())

    with pytest.raises(requests.HTTPError):
        AgnesChatAPI("test")._request_with_retry({})
    assert response.closed is True
