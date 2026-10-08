import asyncio

from core.api.agnes_video import AgnesVideoAPI


def test_submit_closes_http_response(monkeypatch):
    class Response:
        status_code = 202
        headers = {}
        text = ""
        def __init__(self):
            self.closed = False
        def json(self):
            return {"video_id": "vid-1"}
        def close(self):
            self.closed = True

    response = Response()

    async def scenario():
        api = AgnesVideoAPI(api_key="test", model="agnes-video-2.5-flash")
        monkeypatch.setattr("core.api.agnes_video.requests.post", lambda *a, **k: response)
        monkeypatch.setattr("core.api.agnes_video.get_rate_limiter", lambda: type("L", (), {"acquire": lambda self: None})())
        return await api._submit_with_retry({"model": "x"}, "test")

    result = asyncio.run(scenario())
    assert result == "vid-1"
    assert response.closed is True


def test_submit_retries_connection_error(monkeypatch):
    class Response:
        status_code = 202
        headers = {}
        text = ""
        def json(self):
            return {"video_id": "vid-2"}
        def close(self):
            pass

    calls = {"count": 0}
    def post(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise __import__("requests").exceptions.ConnectionError("temporary")
        return Response()

    async def scenario():
        api = AgnesVideoAPI(api_key="test", model="agnes-video-2.5-flash")
        api.retry_base_delay = 0
        monkeypatch.setattr("core.api.agnes_video.requests.post", post)
        monkeypatch.setattr("core.api.agnes_video.get_rate_limiter", lambda: type("L", (), {"acquire": lambda self: None})())
        return await api._submit_with_retry({"model": "x"}, "test")

    assert asyncio.run(scenario()) == "vid-2"
    assert calls["count"] == 2


def test_poll_closes_http_response(monkeypatch):
    import asyncio

    class Response:
        def __init__(self):
            self.closed = False
        def raise_for_status(self):
            pass
        def json(self):
            return {"status": "completed", "progress": 100, "video_id": "vid-3"}
        def close(self):
            self.closed = True

    response = Response()
    async def scenario():
        api = AgnesVideoAPI(api_key="test", model="agnes-video-2.5-flash")
        monkeypatch.setattr("core.api.agnes_video.requests.get", lambda *a, **k: response)
        monkeypatch.setattr("core.api.agnes_video.get_rate_limiter", lambda: type("L", (), {"acquire": lambda self: None})())
        return await api._poll_task("vid-3", interval=0, max_poll_duration=5)

    result = asyncio.run(scenario())
    assert result["status"] == "completed"
    assert response.closed is True
