"""Regression tests for cancellation before subprocess spawn.

These test the real StudioJobs worker methods with a mocked subprocess; they
do not require Blender or claim that frames were rendered.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from local_agent.studio_jobs import StudioJobs


class StudioCancellationRaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        store = type("Store", (), {"root": Path(self.tmp.name)})()
        self.jobs = StudioJobs(store)

    def new_job(self, job_id="a" * 32, total_frames=2):
        directory = self.jobs._path(job_id)
        directory.mkdir()
        info = {
            "job_id": job_id, "scene_id": "scene_001", "kind": "scene",
            "state": "queued", "message": "Queued", "progress_percent": 0,
            "rendered_frames": 0, "total_frames": total_frames,
            "video_url": "",
        }
        (directory / "manifest.json").write_text(json.dumps({"fps": 4}), encoding="utf-8")
        self.jobs._write(directory, info)
        self.jobs.active = job_id
        return directory, info

    def cancel_during_status_write(self, matching_message):
        original = self.jobs._write
        was_cancelled = [False]
        def intercepted(directory, info):
            original(directory, info)
            if not was_cancelled[0] and info.get("message") == matching_message:
                was_cancelled[0] = True
                self.jobs.cancel(info["job_id"])
        self.jobs._write = intercepted
        return was_cancelled

    def test_cancel_between_running_status_and_blender_spawn(self):
        job_id = "a" * 32
        directory, _ = self.new_job(job_id)
        cancelled = self.cancel_during_status_write("Blender создаёт анимацию")
        with patch("local_agent.studio_jobs.subprocess.Popen") as spawn:
            self.jobs._run(job_id, directory, "blender", "ffmpeg")
        self.assertTrue(cancelled[0])
        spawn.assert_not_called()
        self.assertEqual(self.jobs.status(job_id)["state"], "cancelled")
        self.assertIsNone(self.jobs.active)

    def test_cancel_between_render_and_ffmpeg_spawn(self):
        job_id = "b" * 32
        directory, _ = self.new_job(job_id)
        frames = directory / "frames"
        frames.mkdir()
        for number in (1, 2):
            (frames / f"frame_{number:04d}.png").write_bytes(b"sample")
        (directory / "scene.blend").write_bytes(b"sample")
        completed_blender = Mock()
        completed_blender.wait.return_value = 0
        completed_blender.poll.return_value = 0
        cancelled = self.cancel_during_status_write("FFmpeg собирает MP4")
        with patch("local_agent.studio_jobs.subprocess.Popen", return_value=completed_blender) as spawn:
            self.jobs._run(job_id, directory, "blender", "ffmpeg")
        self.assertTrue(cancelled[0])
        self.assertEqual(spawn.call_count, 1, "FFmpeg must not launch after cancellation")
        self.assertEqual(self.jobs.status(job_id)["state"], "cancelled")

    def test_cancel_between_assembly_status_and_ffmpeg_spawn(self):
        job_id = "c" * 32
        directory, info = self.new_job(job_id)
        info["kind"] = "assembly"
        self.jobs._write(directory, info)
        cancelled = self.cancel_during_status_write("FFmpeg собирает сцены по порядку")
        videos = [directory / "a.mp4", directory / "b.mp4"]
        with patch("local_agent.studio_jobs.subprocess.Popen") as spawn:
            self.jobs._assemble(info, videos, "ffmpeg")
        self.assertTrue(cancelled[0])
        spawn.assert_not_called()
        self.assertEqual(self.jobs.status(job_id)["state"], "cancelled")


if __name__ == "__main__":
    unittest.main()


def test_fixed_blender_script_is_used_without_duplicate_world_patch(tmp_path):
    from local_agent.studio_jobs import _prepare_studio_blender_script
    source = Path(__file__).resolve().parents[1] / "local_agent/studio_blender_scene.py"
    assert _prepare_studio_blender_script(source, tmp_path) == source
    assert list(tmp_path.iterdir()) == []
