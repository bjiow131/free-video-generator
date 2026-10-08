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
