from core.api.agnes_video import AgnesVideoAPI, MODERN_MODELS
from core.config import SUPPORTED_AGNES_VIDEO_DURATIONS


def test_short_durations_are_supported():
    assert {4, 5, 6, 8, 10, 12}.issubset(SUPPORTED_AGNES_VIDEO_DURATIONS)


def test_modern_duration_clamps_to_provider_range():
    api = AgnesVideoAPI(api_key="test", model="agnes-video-2.5-flash")
    assert api._modern_seconds(3) == 4
    assert api._modern_seconds(5) == 5
    assert api._modern_seconds(99) == 12


def test_modern_models_are_explicit():
    assert "agnes-video-2.5-flash" in MODERN_MODELS


def test_transient_statuses_are_explicit():
    source = __import__("inspect").getsource(AgnesVideoAPI._submit_with_retry)
    assert "{500, 502, 503, 504, 520, 522, 524}" in source


def test_queue_full_error_is_user_actionable():
    source = __import__("inspect").getsource(AgnesVideoAPI._submit_with_retry)
    assert "video queue is full" in source
    assert "please retry later" in source


@pytest.mark.asyncio
async def test_video_reference_file_read_is_async(tmp_path):
    from core.api.agnes_video import AgnesVideoAPI

    path = tmp_path / "ref.png"
    path.write_bytes(b"png-data")
    api = AgnesVideoAPI(api_key="test")
    result = await api._path_to_b64(str(path))
    assert result.startswith("data:image/png;base64,")
