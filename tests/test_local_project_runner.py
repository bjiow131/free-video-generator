"""Regression tests for scene-bound checkpoint media paths."""
import asyncio
import hashlib
from pathlib import Path

from local_agent.checkpoint import CheckpointStore
from local_agent.manifest import ProjectManifest
from local_agent.runner import LocalProjectRunner


class FakeBackend:
    def __init__(self):
        self.outputs = []

    async def generate_i2v(self, *, prompt, input_image, duration_seconds, aspect_ratio, output_path):
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(("generated:" + target.parent.name).encode("utf-8"))
        self.outputs.append(str(target))
        return str(target)


class FakeMedia:
    def validate_video(self, path, expected_duration):
        assert Path(path).is_file()

    def extract_last_frame(self, video_path, output_path):
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(("frame:" + target.parent.name).encode("utf-8"))
        return str(target)

    def validate_image(self, path):
        assert Path(path).is_file()

    def concatenate(self, video_paths, output_path):
        target = Path(output_path)
        target.write_bytes(b"assembled-video")
        return str(target)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_checkpoint_video_from_another_scene_is_not_reused(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    initial_image = tmp_path / "initial.png"
    initial_image.write_bytes(b"initial-frame")
    manifest = ProjectManifest.from_dict({
        "project_id": "scene-boundary",
        "initial_image": str(initial_image),
        "scenes": [
            {"scene_id": "scene_a", "prompt": "Scene A", "duration_seconds": 5},
            {"scene_id": "scene_b", "prompt": "Scene B", "duration_seconds": 5},
        ],
    })
    store = CheckpointStore(workspace, manifest.project_id)
    state = store.initialize(manifest.to_dict())

    foreign_dir = workspace / manifest.project_id / "scene_b"
    foreign_dir.mkdir(parents=True)
    foreign_video = foreign_dir / "attempt_01.mp4"
    foreign_frame = foreign_dir / "attempt_01_last.png"
    foreign_video.write_bytes(b"video belonging to scene B")
    foreign_frame.write_bytes(b"frame belonging to scene B")
    state["scenes"]["scene_a"].update({
        "status": "completed",
        "attempts": 1,
        "video_path": str(foreign_video),
        "final_frame_path": str(foreign_frame),
        "video_sha256": _sha(foreign_video),
        "frame_sha256": _sha(foreign_frame),
        "input_frame_sha256": _sha(initial_image),
    })
    store.save(state)

    backend = FakeBackend()
    runner = LocalProjectRunner(workspace, store, backend, FakeMedia())
    result = asyncio.run(runner.run(manifest))

    assert result["status"] == "completed"
    assert len(backend.outputs) == 2
    assert all(Path(path).parent.name in {"scene_a", "scene_b"} for path in backend.outputs)
    assert any(Path(path).parent.name == "scene_a" for path in backend.outputs)
