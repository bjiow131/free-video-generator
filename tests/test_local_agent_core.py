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
