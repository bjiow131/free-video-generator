import asyncio
from io import BytesIO

import pytest
import time
from starlette.datastructures import UploadFile as StarletteUploadFile

import server


class DummyTaskManager:
    def __init__(self):
        self.statuses = []

    def update_state(self, **kwargs):
        self.statuses.append(kwargs.get("status"))


class DummyPipeline:
    def __init__(self, task_id="task-1"):
        self.task_id = task_id
        self._stop_event = asyncio.Event()
        self.runs = 0

    async def run(self, state):
        self.runs += 1


class DummyState:
    task_type = server.TaskType.SIMPLE


@pytest.mark.asyncio
async def test_semaphore_cancellation_does_not_release_unacquired_slot(monkeypatch):
    semaphore = server.WeightedSemaphore(1)
    await semaphore.acquire(1)
    monkeypatch.setattr(server, "_pipeline_semaphore", semaphore)

    pipeline = DummyPipeline()
    tm = DummyTaskManager()
    task = asyncio.create_task(server._run_pipeline_with_concurrency(pipeline, DummyState(), tm))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert semaphore.current == 1
    assert "task-1" not in server._queued_tasks
    await semaphore.release(1)


@pytest.mark.asyncio
async def test_stopped_queued_task_is_not_left_queued(monkeypatch):
    semaphore = server.WeightedSemaphore(1)
    await semaphore.acquire(1)
    monkeypatch.setattr(server, "_pipeline_semaphore", semaphore)

    pipeline = DummyPipeline("task-stop")
    tm = DummyTaskManager()
    server.active_pipelines[pipeline.task_id] = pipeline

    task = asyncio.create_task(server._run_pipeline_with_concurrency(pipeline, DummyState(), tm))
    await asyncio.sleep(0)
    pipeline._stop_event.set()
    await semaphore.release(1)
    await task

    assert tm.statuses[-1] == server.StepStatus.PENDING
    assert pipeline.runs == 0
    assert pipeline.task_id not in server.active_pipelines
    assert pipeline.task_id not in server._queued_tasks


def test_task_id_validation():
    assert server._validate_task_id("abc123") == "abc123"
    for value in ("", "../x", "a/b", r"a\\b", "..", "x" * 129):
        with pytest.raises(Exception):
            server._validate_task_id(value)


def test_origin_and_host_validation():
    assert server._origin_matches_host("http://localhost:8765", "localhost:8765")
    assert not server._origin_matches_host("https://evil.example", "localhost:8765")
    assert not server._request_host_allowed("evil.example:8765")


@pytest.mark.asyncio
async def test_upload_magic_and_content_type_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "get_upload_dir", lambda: str(tmp_path))
    png = b"\x89PNG\r\n\x1a\n" + b"payload"
    good = StarletteUploadFile(
        file=BytesIO(png),
        filename="evil.exe",
        headers={"content-type": "image/png"},
    )
    path = await server._save_image_upload(good, "ref")
    assert path.endswith(".png")

    bad_type = StarletteUploadFile(
        file=BytesIO(png),
        filename="x.png",
        headers={"content-type": "image/jpeg"},
    )
    with pytest.raises(server.HTTPException) as exc:
        await server._save_image_upload(bad_type, "bad")
    assert exc.value.status_code == 422


def test_bg_color_parsing():
    assert server._parse_bg_color("black@0.5") == (0, 0, 0, 128)
    assert server._parse_bg_color("black@50") == (0, 0, 0, 128)
    assert server._parse_bg_color("(1, 2, 3, 4)") == (1, 2, 3, 4)
    assert server._parse_bg_color([1, 2, 3]) == (1, 2, 3)
    assert server._parse_bg_color("transparent") is None
    with pytest.raises(ValueError):
        server._parse_bg_color("black@101")
    with pytest.raises(ValueError):
        server._parse_bg_color("not-a-color")
    with pytest.raises(ValueError):
        server._parse_bg_color((256, 0, 0))


@pytest.mark.parametrize(
    "text, expected",
    [
        ("每个场景5秒", 5),
        ("各 10 秒", 10),
        ("each scene 5 seconds", 5),
        ("각 5 초", 5),
        ("по 10 секунд", 10),
        ("5 detik setiap", 5),
        ("setiap satu 10 saat", 10),
    ],
)
def test_duration_parsing_seven_languages(text, expected):
    assert server._parse_duration(text) == expected


def test_duration_parser_ignores_unrelated_numbers():
    assert server._parse_duration("camera 123, take 7") == 5


@pytest.mark.asyncio
async def test_upload_size_limit_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "get_upload_dir", lambda: str(tmp_path))
    monkeypatch.setattr(server, "MAX_UPLOAD_SIZE", 4)
    oversized = StarletteUploadFile(
        file=BytesIO(b"\x89PNG\r\n\x1a\n" + b"12345"),
        filename="x.png",
        headers={"content-type": "image/png"},
    )
    with pytest.raises(server.HTTPException) as exc:
        await server._save_image_upload(oversized, "oversized")
    assert exc.value.status_code == 413

    ref = tmp_path / "ref.png"
    ref.write_bytes(b"data")
    state = type("State", (), {"reference_image": str(ref), "end_frame_image": "", "end_frame_images": []})()
    server._cleanup_uploaded_references(state)
    assert not ref.exists()


def test_workspace_path_is_normalized_and_protected(tmp_path):
    assert server._validate_workspace_path(str(tmp_path)) == str(tmp_path.resolve())
    with pytest.raises(server.HTTPException):
        server._validate_workspace_path(str(tmp_path / ".." / "etc"))
    with pytest.raises(server.HTTPException):
        server._validate_workspace_path(str(tmp_path / "missing-parent" / "workspace"))
    with pytest.raises(server.HTTPException):
        server._validate_workspace_path(server._PROJECT_ROOT)


def test_save_config_rejects_empty_key():
    import asyncio

    async def scenario():
        with pytest.raises(server.HTTPException) as exc:
            await server.save_config("   ", request=None)
        assert exc.value.status_code == 422

    asyncio.run(scenario())


def test_state_change_origin_policy_accepts_same_origin_and_rejects_cross_origin():
    assert server._request_host_allowed("localhost:8765")
    assert server._origin_matches_host("http://localhost:8765", "localhost:8765")
    assert not server._origin_matches_host("http://127.0.0.1:8765", "localhost:8765")
    assert not server._origin_matches_host("http://evil.example", "localhost:8765")


def test_duration_parser_never_returns_unsupported_key(monkeypatch):
    monkeypatch.setattr(server, "DURATION_FRAME_MAP", {4: 1, 6: 1})
    assert server._parse_duration("5 seconds") == 4
    assert server._parse_duration("6 seconds") == 6


def test_config_get_does_not_expose_api_key(monkeypatch):
    monkeypatch.setattr(server, "get_api_key", lambda: "secret-key")
    monkeypatch.setattr(server, "get_api_key_source", lambda: "config")
    result = asyncio.run(server.get_config(None))
    assert result["configured"] is True
    assert "api_key" not in result
    assert "key" not in result


def test_image_download_validates_each_redirect(monkeypatch, tmp_path):
    from utils import image as image_utils

    calls = []
    class Response:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/private"}
        is_redirect = True
        def close(self):
            pass

    monkeypatch.setattr(image_utils.requests, "get", lambda *args, **kwargs: (calls.append(args[0]) or Response()))
    def validate(url):
        calls.append("validated:" + url)
        if "127.0.0.1" in url:
            raise ValueError("blocked")
    monkeypatch.setattr(image_utils, "_validate_download_url", validate)

    with pytest.raises(ValueError, match="blocked"):
        image_utils.download_image("https://public.example/image.png", str(tmp_path / "x.png"))
    assert "validated:https://public.example/image.png" in calls
    assert "validated:http://127.0.0.1/private" in calls


def test_video_download_validates_each_redirect(monkeypatch, tmp_path):
    from utils import video as video_utils

    calls = []
    class Response:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/private"}
        is_redirect = True
        def close(self):
            pass

    monkeypatch.setattr(video_utils.requests, "get", lambda *args, **kwargs: (calls.append(args[0]) or Response()))
    def validate(url):
        calls.append("validated:" + url)
        if "127.0.0.1" in url:
            raise ValueError("blocked")
    monkeypatch.setattr(video_utils, "_validate_download_url", validate)

    with pytest.raises(ValueError, match="blocked"):
        video_utils.download_video("https://public.example/video.mp4", str(tmp_path / "x.mp4"))
    assert "validated:https://public.example/video.mp4" in calls
    assert "validated:http://127.0.0.1/private" in calls


def test_subtitle_overlay_closes_video_when_composition_fails(monkeypatch, tmp_path):
    from core.audio import subtitle as subtitle_module

    class DummyClip:
        w = 640
        h = 360
        def __init__(self):
            self.closed = False
        def close(self):
            self.closed = True
        def with_position(self, position):
            return self

    video = DummyClip()
    subs = DummyClip()
    monkeypatch.setattr(subtitle_module, "VideoFileClip", lambda path: video)
    monkeypatch.setattr(subtitle_module, "SubtitlesClip", lambda *args, **kwargs: subs)
    monkeypatch.setattr(subtitle_module, "CompositeVideoClip", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("compose failed")))
    monkeypatch.setattr("core.config.resolve_font_path", lambda font: font)
    style = server.SubtitleStyle()

    with pytest.raises(RuntimeError, match="compose failed"):
        subtitle_module.SubtitleGenerator.overlay_subtitles_to_video(
            str(tmp_path / "video.mp4"),
            str(tmp_path / "captions.srt"),
            style,
            str(tmp_path / "out.mp4"),
        )
    assert video.closed is True
    assert subs.closed is True


def test_watermark_render_closes_moviepy_clips_on_failure(monkeypatch, tmp_path):
    from core.compositor import watermark

    class DummyClip:
        size = (100, 40)
        def __init__(self):
            self.closed = False
        def with_duration(self, duration):
            return self
        def with_position(self, position):
            return self
        def close(self):
            self.closed = True

    clips = []
    def make_clip(*args, **kwargs):
        clip = DummyClip()
        clips.append(clip)
        return clip
    class DummyComposite(DummyClip):
        def save_frame(self, path, t=0):
            raise RuntimeError("render failed")

    monkeypatch.setattr(watermark, "resolve_font_path", lambda value: str(tmp_path / "font"))
    (tmp_path / "font").write_bytes(b"font")
    import moviepy
    monkeypatch.setattr(moviepy, "TextClip", make_clip)
    monkeypatch.setattr(moviepy, "ColorClip", make_clip)
    monkeypatch.setattr(moviepy, "CompositeVideoClip", lambda *args, **kwargs: DummyComposite())

    assert watermark._render_watermark_png(str(tmp_path / "wm.png"), 640, 360) is False
    assert all(c.closed for c in clips)


def test_history_ui_does_not_embed_task_id_in_inline_javascript():
    from pathlib import Path

    html = Path(__file__).resolve().parents[1] / "static" / "ai-studio.html"
    source = html.read_text(encoding="utf-8")
    assert "onclick="openResult" not in source
    assert "escapeHtml(x.status)" in source


def test_concat_audio_overlay_closes_source_clips(monkeypatch, tmp_path):
    from core.compositor import concatenator

    class DummyClip:
        duration = 1.0
        w = 640
        h = 360
        def __init__(self):
            self.closed = False
        def subclipped(self, start, end):
            return DummyClip()
        def with_audio(self, audio):
            return self
        def write_videofile(self, *args, **kwargs):
            pass
        def close(self):
            self.closed = True

    video_source = DummyClip()
    audio_source = DummyClip()
    monkeypatch.setattr(concatenator, "VideoFileClip", lambda path: video_source)
    monkeypatch.setattr(concatenator, "AudioFileClip", lambda path: audio_source)
    monkeypatch.setattr(concatenator.VideoConcatenator, "_get_duration", lambda path: 1.0)
    monkeypatch.setattr(concatenator.VideoConcatenator, "concat_videos", lambda paths, out: None)

    concatenator.VideoConcatenator.concat_videos_with_audio_overlay(
        [str(tmp_path / "v.mp4")],
        str(tmp_path / "a.mp3"),
        None,
        str(tmp_path / "out.mp4"),
    )
    assert video_source.closed is True
    assert audio_source.closed is True
