import asyncio
from pathlib import Path

import pytest

from local_agent.checkpoint import CheckpointStore
from local_agent.manifest import ProjectManifest
from local_agent.runner import LocalProjectRunner


class FakeBackend:
    def __init__(self, *, fail_first=False):
        self.calls = []
        self.fail_first = fail_first

    async def generate_i2v(self, *, prompt, input_image, duration_seconds, aspect_ratio, output_path):
        self.calls.append({"prompt": prompt, "input_image": input_image, "duration_seconds": duration_seconds})
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("temporary generation failure")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake-mp4")
        return output_path


class FakeMedia:
    def validate_video(self, path, expected_duration):
        assert Path(path).is_file() and Path(path).stat().st_size > 0

    def extract_last_frame(self, video_path, output_path):
        Path(output_path).write_bytes(b"fake-png")
        return output_path

    def validate_image(self, path):
        assert Path(path).is_file() and Path(path).stat().st_size > 0

    def concatenate(self, video_paths, output_path):
        assert len(video_paths) > 0
        Path(output_path).write_bytes(b"final-mp4")
        return output_path


def sample_manifest(start_image):
    return ProjectManifest.from_dict({
        "project_id": "test-project",
        "initial_image": str(start_image),
        "global_prompt": "Same character, same outfit.",
        "scenes": [
            {"scene_id": "s1", "prompt": "Mia starts riding."},
            {"scene_id": "s2", "prompt": "Mia continues riding."},
        ],
    })


def test_manifest_rejects_duplicate_scene_ids():
    with pytest.raises(ValueError, match="unique"):
        ProjectManifest.from_dict({
            "project_id": "x",
            "scenes": [
                {"scene_id": "same", "prompt": "one"},
                {"scene_id": "same", "prompt": "two"},
            ],
        })


def test_manifest_rejects_unsupported_ratio():
    with pytest.raises(ValueError, match="aspect_ratio"):
        ProjectManifest.from_dict({
            "project_id": "x",
            "scenes": [{"prompt": "one", "aspect_ratio": "4:3"}],
        })


@pytest.mark.asyncio
async def test_runner_passes_final_frame_to_next_scene(tmp_path):
    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    workspace = tmp_path / "workspace"
    manifest = sample_manifest(start)
    store = CheckpointStore(workspace, manifest.project_id)
    backend = FakeBackend()
    runner = LocalProjectRunner(workspace, store, backend, FakeMedia())

    state = await runner.run(manifest)

    assert state["status"] == "completed"
    assert len(backend.calls) == 2
    assert backend.calls[0]["input_image"] == str(start)
    assert backend.calls[1]["input_image"].endswith("s1/attempt_01_last.png")
    assert Path(state["final_video_path"]).read_bytes() == b"final-mp4"
    assert state["scenes"]["s1"]["video_sha256"]
    assert state["scenes"]["s1"]["frame_sha256"]


@pytest.mark.asyncio
async def test_runner_retries_scene_without_skipping_chain(tmp_path):
    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    workspace = tmp_path / "workspace"
    manifest = sample_manifest(start)
    store = CheckpointStore(workspace, manifest.project_id)
    backend = FakeBackend(fail_first=True)
    runner = LocalProjectRunner(workspace, store, backend, FakeMedia(), max_attempts=2)

    state = await runner.run(manifest)

    assert state["status"] == "completed"
    assert len(backend.calls) == 3
    assert backend.calls[1]["input_image"] == str(start)
    assert backend.calls[2]["input_image"].endswith("s1/attempt_02_last.png")


def test_checkpoint_survives_reload(tmp_path):
    store = CheckpointStore(tmp_path, "persist-test")
    manifest = {
        "project_id": "persist-test",
        "scenes": [{"scene_id": "s1", "prompt": "one", "duration_seconds": 5, "aspect_ratio": "9:16"}],
    }
    store.initialize(manifest)
    loaded = CheckpointStore(tmp_path, "persist-test").load()
    assert loaded["scenes"]["s1"]["status"] == "pending"

def test_manifest_rejects_path_like_output_name():
    with pytest.raises(ValueError, match="filename"):
        ProjectManifest.from_dict({
            "project_id": "x",
            "output_name": "..",
            "scenes": [{"prompt": "one"}],
        })



def test_checkpoint_refuses_manifest_changes(tmp_path):
    store = CheckpointStore(tmp_path, "persist-test")
    manifest = {
        "project_id": "persist-test",
        "scenes": [{"scene_id": "s1", "prompt": "one", "duration_seconds": 5, "aspect_ratio": "9:16"}],
    }
    store.initialize(manifest)
    changed = {
        "project_id": "persist-test",
        "scenes": [{"scene_id": "s1", "prompt": "different prompt", "duration_seconds": 5, "aspect_ratio": "9:16"}],
    }
    with pytest.raises(ValueError, match="differs from the checkpoint"):
        store.initialize(changed)


@pytest.mark.asyncio
async def test_runner_regenerates_completed_scene_when_revalidation_fails(tmp_path):
    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    workspace = tmp_path / "workspace"
    manifest = sample_manifest(start)
    store = CheckpointStore(workspace, manifest.project_id)
    state = store.initialize(manifest.to_dict())
    scene_dir = workspace / manifest.project_id / "s1"
    scene_dir.mkdir(parents=True)
    old_video = scene_dir / "old.mp4"
    old_frame = scene_dir / "old.png"
    old_video.write_bytes(b"old-video")
    old_frame.write_bytes(b"old-frame")
    import hashlib
    state["scenes"]["s1"].update({
        "status": "completed",
        "video_path": str(old_video),
        "final_frame_path": str(old_frame),
        "video_sha256": hashlib.sha256(old_video.read_bytes()).hexdigest(),
        "frame_sha256": hashlib.sha256(old_frame.read_bytes()).hexdigest(),
    })
    store.save(state)

    class FlakyValidationMedia(FakeMedia):
        def __init__(self):
            self.fail_once = True

        def validate_video(self, path, expected_duration):
            if self.fail_once and path == str(old_video):
                self.fail_once = False
                raise RuntimeError("saved video is corrupt")
            super().validate_video(path, expected_duration)

    backend = FakeBackend()
    runner = LocalProjectRunner(workspace, store, backend, FlakyValidationMedia())
    result = await runner.run(manifest)
    assert result["status"] == "completed"
    assert len(backend.calls) == 2
    assert result["scenes"]["s1"]["video_path"] != str(old_video)


@pytest.mark.asyncio
async def test_duplicate_project_run_is_rejected_and_registry_released(tmp_path):
    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    manifest = sample_manifest(start)
    workspace = tmp_path / "workspace"
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingBackend(FakeBackend):
        async def generate_i2v(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().generate_i2v(**kwargs)

    store = CheckpointStore(workspace, manifest.project_id)
    runner = LocalProjectRunner(workspace, store, BlockingBackend(), FakeMedia())
    first = asyncio.create_task(runner.run(manifest))
    await asyncio.wait_for(entered.wait(), timeout=2)
    with pytest.raises(RuntimeError, match="already running"):
        await runner.run(manifest)
    release.set()
    result = await first
    assert result["status"] == "completed"
    # Ownership is released after completion, so a subsequent resume is permitted.
    again = await runner.run(manifest)
    assert again["status"] == "completed"


def test_corrupt_checkpoint_is_preserved_and_reports_recovery_hint(tmp_path):
    store = CheckpointStore(tmp_path, "corrupt-test")
    store.path.write_text('{"truncated":', encoding="utf-8")
    with pytest.raises(ValueError, match="original file was preserved"):
        store.load()
    assert store.path.read_text(encoding="utf-8") == '{"truncated":'


def test_checkpoint_rejects_project_directory_symlink_escape(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace / "symlink-test"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks are not available in this environment")
    with pytest.raises(ValueError, match="outside the configured workspace"):
        CheckpointStore(workspace, "symlink-test")


@pytest.mark.asyncio
async def test_permanent_media_validation_error_is_not_retried(tmp_path):
    from local_agent.ffmpeg_media import MediaError

    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    manifest = sample_manifest(start)
    workspace = tmp_path / "workspace"

    class PermanentlyInvalidMedia(FakeMedia):
        def validate_video(self, path, expected_duration):
            raise MediaError("invalid video stream")

    backend = FakeBackend()
    runner = LocalProjectRunner(
        workspace, CheckpointStore(workspace, manifest.project_id),
        backend, PermanentlyInvalidMedia(), max_attempts=4,
    )
    result = await runner.run(manifest)
    assert result["status"] == "failed"
    assert result["scenes"]["s1"]["status"] == "failed"
    assert len(backend.calls) == 1
    assert "invalid video stream" in result["error"]


@pytest.mark.asyncio
async def test_unexpected_setup_error_does_not_leave_running_checkpoint(tmp_path):
    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    manifest = sample_manifest(start)
    workspace = tmp_path / "workspace"

    class BrokenMedia(FakeMedia):
        def validate_image(self, path):
            raise RuntimeError("reference image decoder failed")

    store = CheckpointStore(workspace, manifest.project_id)
    runner = LocalProjectRunner(workspace, store, FakeBackend(), BrokenMedia())
    with pytest.raises(RuntimeError, match="reference image decoder failed"):
        await runner.run(manifest)
    state = store.load()
    assert state["status"] == "failed"
    assert "reference image decoder failed" in state["error"]


@pytest.mark.asyncio
async def test_task_cancellation_persists_cancelled_state(tmp_path):
    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    manifest = sample_manifest(start)
    workspace = tmp_path / "workspace"
    entered = asyncio.Event()

    class BlockingBackend(FakeBackend):
        async def generate_i2v(self, **kwargs):
            entered.set()
            await asyncio.Event().wait()

    store = CheckpointStore(workspace, manifest.project_id)
    runner = LocalProjectRunner(workspace, store, BlockingBackend(), FakeMedia())
    task = asyncio.create_task(runner.run(manifest))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    state = store.load()
    assert state["status"] == "cancelled"
    assert state["scenes"]["s1"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_total_attempt_budget_is_not_reset_by_resume(tmp_path):
    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    manifest = sample_manifest(start)
    workspace = tmp_path / "workspace"

    class AlwaysFailBackend(FakeBackend):
        async def generate_i2v(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError("backend unavailable")

    backend = AlwaysFailBackend()
    store = CheckpointStore(workspace, manifest.project_id)
    runner = LocalProjectRunner(workspace, store, backend, FakeMedia(), max_attempts=2)
    first = await runner.run(manifest)
    assert first["status"] == "failed"
    assert first["scenes"]["s1"]["attempts"] == 2
    second = await runner.run(manifest)
    assert second["status"] == "failed"
    assert len(backend.calls) == 2


@pytest.mark.asyncio
async def test_cancel_request_during_generation_prevents_scene_completion(tmp_path):
    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    manifest = sample_manifest(start)
    workspace = tmp_path / "workspace"
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowBackend(FakeBackend):
        async def generate_i2v(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().generate_i2v(**kwargs)

    store = CheckpointStore(workspace, manifest.project_id)
    runner = LocalProjectRunner(workspace, store, SlowBackend(), FakeMedia())
    task = asyncio.create_task(runner.run(manifest))
    await asyncio.wait_for(entered.wait(), timeout=2)
    runner.cancel()
    release.set()
    result = await task
    assert result["status"] == "cancelled"
    assert result["scenes"]["s1"]["status"] == "cancelled"
    assert result["scenes"]["s1"]["video_path"] is None


@pytest.mark.asyncio
async def test_pause_during_generation_waits_before_validation(tmp_path):
    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    manifest = sample_manifest(start)
    workspace = tmp_path / "workspace"
    entered = asyncio.Event()
    release = asyncio.Event()
    validated = asyncio.Event()

    class SlowBackend(FakeBackend):
        async def generate_i2v(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().generate_i2v(**kwargs)

    class ObserveMedia(FakeMedia):
        def validate_video(self, path, expected_duration):
            validated.set()
            super().validate_video(path, expected_duration)

    store = CheckpointStore(workspace, manifest.project_id)
    runner = LocalProjectRunner(workspace, store, SlowBackend(), ObserveMedia())
    task = asyncio.create_task(runner.run(manifest))
    await asyncio.wait_for(entered.wait(), timeout=2)
    runner.pause()
    release.set()
    await asyncio.sleep(0.05)
    assert not validated.is_set()
    runner.resume()
    result = await task
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_regenerating_upstream_scene_invalidates_downstream_frame_chain(tmp_path):
    import hashlib

    start = tmp_path / "start.png"
    start.write_bytes(b"start-image")
    manifest = sample_manifest(start)
    workspace = tmp_path / "workspace"
    store = CheckpointStore(workspace, manifest.project_id)

    class ChangingFramesMedia(FakeMedia):
        def __init__(self):
            self.frame_number = 0

        def extract_last_frame(self, video_path, output_path):
            self.frame_number += 1
            Path(output_path).write_bytes(f"frame-{self.frame_number}".encode())
            return output_path

    media = ChangingFramesMedia()
    backend = FakeBackend()
    runner = LocalProjectRunner(workspace, store, backend, media)
    first = await runner.run(manifest)
    assert first["status"] == "completed"
    assert first["scenes"]["s1"]["input_frame_sha256"] == hashlib.sha256(start.read_bytes()).hexdigest()
    assert first["scenes"]["s2"]["input_frame_sha256"] == first["scenes"]["s1"]["frame_sha256"]

    # Simulate a checkpoint whose first scene output fails integrity validation
    # after restart. Rebuilding scene 1 changes its final frame, so scene 2 must
    # be rebuilt too instead of reusing a clip generated from the old frame.
    first["scenes"]["s1"]["video_sha256"] = "not-the-real-checksum"
    store.save(first)
    resumed = await runner.run(manifest)

    assert resumed["status"] == "completed"
    assert len(backend.calls) == 4
    assert backend.calls[2]["input_image"].endswith("s1/attempt_02_last.png")
    assert backend.calls[3]["input_image"].endswith("s2/attempt_02_last.png")
    assert resumed["scenes"]["s2"]["input_frame_sha256"] == resumed["scenes"]["s1"]["frame_sha256"]


def test_os_project_lock_rejects_second_owner_and_releases(tmp_path):
    lock_path = tmp_path / ".runner.lock"
    first = LocalProjectRunner._acquire_process_lock(lock_path)
    try:
        with pytest.raises(RuntimeError, match="locked by another process"):
            LocalProjectRunner._acquire_process_lock(lock_path)
    finally:
        LocalProjectRunner._release_process_lock(first)

    second = LocalProjectRunner._acquire_process_lock(lock_path)
    LocalProjectRunner._release_process_lock(second)
