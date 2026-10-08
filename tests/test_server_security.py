import asyncio
from io import BytesIO

import pytest
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
    assert server._parse_bg_color("transparent") is None
    with pytest.raises(ValueError):
        server._parse_bg_color("black@101")
    with pytest.raises(ValueError):
        server._parse_bg_color("not-a-color")


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
