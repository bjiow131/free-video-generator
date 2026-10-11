"""Opt-in real Blender/FFmpeg acceptance on the user's own Windows computer.

Run with STUDIO_LIVE_BLENDER=1, never treat CI skip as a render success.
Creates ONLY a labelled procedural test character in a temporary workspace.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from local_agent.blender_locator import find_blender_executable
from local_agent.studio_jobs import StudioJobs
from local_agent.studio_state import StudioStore, default_state


@unittest.skipUnless(
    os.environ.get("STUDIO_LIVE_BLENDER") == "1",
    "Set STUDIO_LIVE_BLENDER=1 explicitly on a machine with Blender and FFmpeg",
)
class BlenderStudioLiveAcceptance(unittest.TestCase):
    def test_free_text_to_animated_mp4(self):
        executable = find_blender_executable()
        self.assertTrue(executable, "Blender executable not found; configure BLENDER_EXECUTABLE")
        self.assertTrue(shutil.which("ffmpeg"), "FFmpeg not found in PATH")
        self.assertTrue(shutil.which("ffprobe"), "FFprobe not found in PATH")

        with tempfile.TemporaryDirectory(prefix="blender-studio-acceptance-") as tmp:
            store = StudioStore(tmp, "smoke")
            state = default_state("smoke")
            state["settings"].update(duration=3, fps=6, resolution="360x640", aspect="9:16")
            state["scenes"] = [{
                "id": "scene_smoke", "title": "Fixture acceptance",
                "prompt": "Тестовый персонаж идёт, затем поворачивается и говорит. Камера следует.",
                "location": "", "camera": "", "style": "", "animation": "",
                "status": "черновик", "preview": "", "duration": 3,
                "characters": [], "props": [],
            }]
            queue = StudioJobs(store)
            job = queue.start(state, "scene_smoke")
            deadline = time.monotonic() + 240
            status = job
            while time.monotonic() < deadline:
                status = queue.status(job["job_id"])
                if status["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                    break
                time.sleep(0.5)
            else:
                queue.cancel(job["job_id"])
                self.fail("Blender acceptance exceeded the four-minute limit")

            self.assertEqual(status["state"], "completed", status.get("message"))
            directory = queue._path(job["job_id"])
            self.assertTrue((directory / "scene.blend").is_file())
            frames = sorted((directory / "frames").glob("frame_*.png"))
            self.assertEqual(len(frames), 18)
            fingerprints = {hashlib.sha256(path.read_bytes()).hexdigest() for path in frames}
            self.assertGreater(len(fingerprints), 1, "Rendered frames must visibly change")

            mp4 = queue.video(job["job_id"])
            result = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-count_frames", "-show_entries",
                "stream=width,height,nb_read_frames", "-of", "json", str(mp4)
            ], text=True, timeout=30)
            streams = json.loads(result)["streams"]
            self.assertEqual(len(streams), 1)
            self.assertEqual((streams[0]["width"], streams[0]["height"]), (360, 640))
            self.assertGreaterEqual(int(streams[0]["nb_read_frames"]), 18)


if __name__ == "__main__":
    unittest.main()
