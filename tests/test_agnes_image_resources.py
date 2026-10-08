import asyncio

from core.api.agnes_image import AgnesImageAPI


def test_image_generation_closes_session_and_response(monkeypatch):
    class Response:
        status_code = 200
        text = ""
        def __init__(self):
            self.closed = False
        def json(self):
            return {"data": [{"url": "https://example.com/image.png"}]}
        def raise_for_status(self):
            pass
        def close(self):
            self.closed = True

    class Session:
        def __init__(self):
            self.closed = False
        def post(self, *args, **kwargs):
            return response
        def close(self):
            self.closed = True

    response = Response()
    session = Session()

    async def scenario():
        api = AgnesImageAPI(api_key="test")
        monkeypatch.setattr("core.api.agnes_image._make_session", lambda: session)
        monkeypatch.setattr("core.api.agnes_image.get_rate_limiter", lambda: type("L", (), {"acquire": lambda self: None})())
        return await api.generate_single_image("test")

    result = asyncio.run(scenario())
    assert result.data.endswith("image.png")
    assert response.closed is True
    assert session.closed is True


def test_image_generation_closes_retry_response(monkeypatch):
    class Response:
        headers = {}
        def __init__(self, status, url=""):
            self.status_code = status
            self.text = "busy"
            self.closed = False
            self.url = url
        def json(self):
            return {"data": [{"url": "https://example.com/image.png"}]}
        def raise_for_status(self):
            pass
        def close(self):
            self.closed = True

    first = Response(500)
    second = Response(200)
    responses = iter([first, second])

    class Session:
        def post(self, *args, **kwargs):
            return next(responses)
        def close(self):
            pass

    async def scenario():
        api = AgnesImageAPI(api_key="test")
        monkeypatch.setattr("core.api.agnes_image._make_session", Session)
        monkeypatch.setattr("core.api.agnes_image.get_rate_limiter", lambda: type("L", (), {"acquire": lambda self: None})())
        return await api.generate_single_image("test", retry_base_delay=0)

    result = asyncio.run(scenario())
    assert result.data.endswith("image.png")
    assert first.closed is True
