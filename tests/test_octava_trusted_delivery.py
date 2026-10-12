"""Offline release acceptance of the allowlisted OctavAPI memory implementation."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from local_agent.mailbox_policy import OctavaProjectMemory, MemoryErrorSafe
from local_agent.poller import _run_octava_advice
from local_agent.studio_server import _resume_octava_waiting_projects
from local_agent.octava_advisor import OctavaAdviceError
from local_agent.control_protocol import parse_task, ProtocolError


class TrustedMemoryDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.dict(os.environ, {"LOCAL_AGENT_WORKSPACE": self.tmp.name}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_key_exhaustion_and_rotated_key_recover_pending(self):
        seen = []
        def advise(question):
            seen.append(question)
            if len(seen) == 2:
                raise OctavaAdviceError("OctavAPI reported insufficient balance")
            return {"status": "completed", "advice": "Mia keeps approved face", "executed_anything": False}
        with patch("local_agent.octava_advisor.request_advice", side_effect=advise):
            first = _run_octava_advice({"project_id": "mia", "prompt": "Set Mia likeness"})
            self.assertEqual(first["checkpoint"]["history_turns"], 1)
            with self.assertRaisesRegex(OctavaAdviceError, "insufficient balance"):
                _run_octava_advice({"project_id": "mia", "prompt": "Make Mia blink"})
            m = OctavaProjectMemory(self.tmp.name, "mia")
            self.assertEqual(m.snapshot()["pending"], "Make Mia blink")
            self.assertEqual(m.snapshot()["status"], "waiting_for_key")
            final = _run_octava_advice({"project_id": "mia", "resume_pending": True})
        self.assertIn("Mia keeps approved face", seen[-1])
        self.assertIn("Make Mia blink", seen[-1])
        self.assertEqual(final["checkpoint"]["history_turns"], 2)
        self.assertIsNone(m.snapshot()["pending"])

    def test_legacy_requests_do_not_create_memory(self):
        with patch("local_agent.octava_advisor.request_advice",
                   return_value={"status": "completed", "advice": "ok"}) as service:
            result = _run_octava_advice({"prompt": "Only legacy"})
        service.assert_called_once_with("Only legacy")
        self.assertEqual(result["advice"], "ok")
        self.assertFalse((Path(self.tmp.name) / ".local_agent").exists())

    def test_rotated_key_triggers_only_locally_authorized_replay(self):
        m = OctavaProjectMemory(self.tmp.name, "mia")
        m.begin("Continue")
        m.fail("waiting_for_key")
        with patch("local_agent.studio_server.load_policy",
                   return_value={"enabled": False, "allow_octava": True}), \
             patch("local_agent.poller._run_octava_advice") as worker:
            _resume_octava_waiting_projects(Path(self.tmp.name))
            worker.assert_not_called()
        with patch("local_agent.studio_server.load_policy",
                   return_value={"enabled": True, "allow_octava": True}), \
             patch("local_agent.poller._run_octava_advice") as worker:
            _resume_octava_waiting_projects(Path(self.tmp.name))
            worker.assert_called_once_with(
                {"project_id": "mia", "resume_pending": True}, workspace=self.tmp.name)

    def test_older_answers_archived_when_context_rolls(self):
        memory = OctavaProjectMemory(self.tmp.name, "mia")
        for i in range(11):
            prompt = "Q " + str(i)
            memory.begin(prompt)
            memory.complete(prompt, "A " + str(i))
        self.assertEqual(len(memory.snapshot()["history"]), 8)
        journal = (memory.root / "mia.history.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(journal), 11)
        self.assertEqual(json.loads(journal[0])["answer"], "A 0")

    def test_no_new_question_overwrites_pending(self):
        m = OctavaProjectMemory(self.tmp.name, "mia")
        m.begin("First")
        with self.assertRaises(MemoryErrorSafe):
            m.begin("Second")
        self.assertEqual(m.snapshot()["pending"], "First")

    def test_unsupported_resume_rejected_by_protocol(self):
        base = {"protocol_version": 1, "task_id": "memory-validation",
                "operation": "octava_advice", "created_at": "2026-10-12T16:00:00Z",
                "expires_at": "2026-10-12T17:00:00Z",
                "requires_local_approval": True,
                "arguments": {"project_id": "mia", "resume_pending": True}}
        self.assertEqual(parse_task(json.dumps(base)).arguments["project_id"], "mia")
        for args in ({"project_id": "../secret", "resume_pending": True},
                     {"project_id": "mia", "resume_pending": False},
                     {"prompt": "hello", "project_id": "mia", "shell": "calc"}):
            base["arguments"] = args
            with self.assertRaises(ProtocolError):
                parse_task(json.dumps(base))


if __name__ == "__main__":
    unittest.main()
