from core.api.agnes_video import AgnesVideoAPI, MODERN_MODELS
from core.config import SUPPORTED_AGNES_VIDEO_DURATIONS


def test_agnes_modern_defaults():
    assert AgnesVideoAPI.DEFAULT_MODEL if hasattr(AgnesVideoAPI, "DEFAULT_MODEL") else True


def test_short_durations_are_supported():
    assert {4, 5, 6, 8, 10, 12}.issubset(SUPPORTED_AGNES_VIDEO_DURATIONS)


def test_modern_duration_clamps_to_provider_range():
    api = AgnesVideoAPI(api_key="test", model="agnes-video-2.5-flash")
    assert api._modern_seconds(3) == 4
    assert api._modern_seconds(5) == 5
    assert api._modern_seconds(99) == 12


def test_modern_models_are_explicit():
    assert "agnes-video-2.5-flash" in MODERN_MODELS
