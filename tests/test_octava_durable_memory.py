"""Offline regressions for memory across exhausted and replaced OctavAPI keys."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from local_agent import octava_credentials
from local_agent.octava_advisor import request_advice, OctavaAdviceError
from local_agent.octava_project_memory import ProjectMemory, MemoryErrorSafe
from local_agent.control_protocol import parse_task, ProtocolError


class Reply:
    def __init__(self, answer):
        self.data = io.BytesIO(json.dumps({
            "choices": [{"message": {"content": answer}}],
            "usage": {"total_tokens": 10},
        }).encode())
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.data.close()
    def read(self, size=-1):
        return self.data.read(size)


class DurableMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"LOCAL_AGENT_WORKSPACE": self.tmp.name}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_rotate_key_and_resume_pending_with_full_history(self):
        seen = []
        keys = iter([("key-1-secret-local", "windows_vault"),
                     ("key-1-secret-local", "windows_vault"),
                     ("key-2-secret-local", "windows_vault")])
        def send(request, timeout):
            body = json.loads(request.data)
            seen.append((request.get_header("Authorization"), body["messages"]))
            if len(seen) == 2:
                raise HTTPError(request.full_url, 402, "no balance", {}, io.BytesIO(b"secret"))
            return Reply("Mia continues with approved clothes." if len(seen) == 3 else
                         "Preserve face and proportions.")
        with patch.object(octava_credentials, "read_key", side_effect=lambda: next(keys)):
            first = request_advice("Plan Mia appearance", project_id="mia", transport=send)
            self.assertEqual(first["checkpoint"]["history_turns"], 1)
            with self.assertRaisesRegex(OctavaAdviceError, "insufficient balance"):
                request_advice("Continue Mia animation", project_id="mia", transport=send)
            previous = ProjectMemory(self.tmp.name, "mia").snapshot()
            self.assertEqual(previous["status"], "waiting_for_key")
            self.assertEqual(previous["pending"], "Continue Mia animation")
            self.assertEqual(len(previous["history"]), 1)
            continued = request_advice(project_id="mia", resume_pending=True, transport=send)
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen[-1][0], "Bearer key-2-secret-local")
        self.assertIn("Preserve face and proportions.", json.dumps(seen[-1][1]))
        self.assertEqual(continued["checkpoint"]["history_turns"], 2)
        saved = ProjectMemory(self.tmp.name, "mia").snapshot()
        self.assertEqual(saved["status"], "idle")
        self.assertIsNone(saved["pending"])
        self.assertNotIn("key-1-secret-local", json.dumps(saved))
        self.assertNotIn("key-2-secret-local", json.dumps(saved))

    def test_crash_before_response_is_recoverable(self):
        memory = ProjectMemory(self.tmp.name, "mia")
        memory.begin("Original question")
        restarted = ProjectMemory(self.tmp.name, "mia")
        prompt, history = restarted.begin(resume=True)
        self.assertEqual(prompt, "Original question")
        self.assertEqual(history, [])
        restarted.complete(prompt, "Result")
        self.assertEqual(restarted.snapshot()["history"][0]["answer"], "Result")

    def test_different_projects_remain_isolated(self):
        a = ProjectMemory(self.tmp.name, "mia")
        b = ProjectMemory(self.tmp.name, "episode_02")
        a.begin("Mia action")
        a.complete("Mia action", "Walk")
        self.assertEqual(b.snapshot()["history"], [])
        self.assertEqual(b.snapshot()["status"], "idle")

    def test_new_request_never_displaces_pending(self):
        m = ProjectMemory(self.tmp.name, "mia")
        m.begin("First")
        m.fail("waiting_for_key")
        with self.assertRaisesRegex(MemoryErrorSafe, "Resume pending"):
            m.begin("Different")
        self.assertEqual(m.snapshot()["pending"], "First")

    def test_checkpoint_milestones_keep_last_verified_outcome(self):
        m = ProjectMemory(self.tmp.name, "mia")
        m.checkpoint_step("render-1", "blocked", "Blender unavailable")
        m.checkpoint_step("render-1", "completed", "MP4 was verified")
        self.assertEqual(m.snapshot()["steps"], [
            {"id": "render-1", "state": "completed", "note": "MP4 was verified"}])

    def test_reject_secret_and_bad_project_id(self):
        with self.assertRaises(MemoryErrorSafe):
            ProjectMemory(self.tmp.name, "../outside")
        m = ProjectMemory(self.tmp.name, "mia")
        with self.assertRaises(MemoryErrorSafe):
            m.begin("token=secret_value_123")
        with self.assertRaises(MemoryErrorSafe):
            m.checkpoint_step("test", "completed", "Bearer secret-value")
        self.assertFalse(m.path.exists())

    def test_preserve_corrupted_memory_instead_of_resetting(self):
        m = ProjectMemory(self.tmp.name, "mia")
        m.begin("Keep data")
        m.path.write_text('{"invalid":true}', encoding="utf-8")
        with self.assertRaises(MemoryErrorSafe):
            m.snapshot()
        self.assertEqual(m.path.read_text(encoding="utf-8"), '{"invalid":true}')

    def test_mailbox_accepts_project_and_resume_without_commands(self):
        base = {"protocol_version": 1, "task_id": "mia-memory-check",
                "operation": "octava_advice", "created_at": "2026-10-12T17:00:00Z",
                "expires_at": "2026-10-12T18:00:00Z",
                "requires_local_approval": True, "arguments": {"prompt": "Mia test", "project_id": "mia"}}
        self.assertEqual(parse_task(json.dumps(base)).arguments["project_id"], "mia")
        base["arguments"] = {"project_id": "mia", "resume_pending": True}
        self.assertEqual(parse_task(json.dumps(base)).arguments["resume_pending"], True)
        for bad in ({"project_id": "mia", "resume_pending": False},
                    {"project_id": "../other", "resume_pending": True},
                    {"prompt": "foo", "project_id": "mia", "shell": "dir"}):
            base["arguments"] = bad
            with self.assertRaises(ProtocolError):
                parse_task(json.dumps(base))


if __name__ == "__main__":
    unittest.main()
