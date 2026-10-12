"""Offline model-routing and key-independent project-memory regressions.

Never contacts OctavAPI and never uses real keys. Model availability at the
third-party provider must still be checked on the user's Windows installation.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from local_agent import octava_credentials as credentials
from local_agent.octava_advisor import request_advice, OctavaAdviceError
from local_agent.octava_project_memory import ProjectMemory
from local_agent.control_protocol import parse_task, ProtocolError


class Response:
    def __init__(self, result):
        self.buffer = io.BytesIO(json.dumps({
            "choices": [{"message": {"content": result}}],
            "usage": {"total_tokens": 11}
        }).encode("utf-8"))
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.buffer.close()
    def read(self, count=-1):
        return self.buffer.read(count)


class ModelRoutingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = tmp.name
        env = patch.dict(os.environ, {
            "LOCAL_AGENT_WORKSPACE": self.workspace,
            "OCTAVA_MODEL": "gpt-6-luna",
            "LOCAL_AGENT_ALLOW_OCTAVA": "1",
            "OCTAVA_API_KEY": "local-fake-key-123"
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_legacy_luna_default_and_explicit_complex_sol(self):
        sent = []
        def transport(req, timeout):
            self.assertEqual(req.full_url, credentials.API_URL)
            payload = json.loads(req.data)
            sent.append(payload["model"])
            return Response("Valid text advice.")
        a = request_advice("Explain a small studio status", transport=transport)
        b = request_advice("Plan the Blender scene", tier="complex", transport=transport)
        c = request_advice("Short check", tier="simple", transport=transport)
        self.assertEqual(sent, ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-luna"])
        self.assertEqual(a["model_tier"], "default")
        self.assertEqual(b["model_requested"], "gpt-6.1-sol")
        self.assertFalse(b["executed_anything"])

    def test_no_implicit_fallback_or_extra_paid_call(self):
        calls = []
        def transport(req, timeout):
            calls.append(json.loads(req.data)["model"])
            raise HTTPError(req.full_url, 404, "unsupported", {}, io.BytesIO(b"private"))
        with self.assertRaisesRegex(OctavaAdviceError, "rejected the model"):
            request_advice("Make a scene plan", tier="complex", project_id="mia", transport=transport)
        self.assertEqual(calls, ["gpt-6.1-sol"])
        saved = ProjectMemory(self.workspace, "mia").snapshot()
        self.assertEqual(saved["status"], "retry_later")
        self.assertEqual(saved["pending"], "Make a scene plan")

    def test_new_key_and_model_resumes_same_project_history(self):
        seen = []
        keys = iter([("first-local-secret-123", "windows_vault"),
                     ("first-local-secret-123", "windows_vault"),
                     ("second-local-secret-456", "windows_vault")])
        def send(request, timeout):
            payload = json.loads(request.data)
            seen.append((request.get_header("Authorization"), payload))
            if len(seen) == 2:
                raise HTTPError(request.full_url, 402, "balance", {}, io.BytesIO(b"private"))
            return Response("Mia keeps the same colors." if len(seen) == 1
                            else "Continue Mia animation; same outfit.")
        with patch.object(credentials, "read_key", side_effect=lambda: next(keys)):
            request_advice("Save Mia appearance", project_id="mia", transport=send)
            with self.assertRaisesRegex(OctavaAdviceError, "insufficient balance"):
                request_advice("Plan Mia animation", tier="complex", project_id="mia", transport=send)
            result = request_advice(project_id="mia", resume_pending=True,
                                    tier="complex", transport=send)
        self.assertEqual([v[1]["model"] for v in seen],
                         ["gpt-6-luna", "gpt-6.1-sol", "gpt-6.1-sol"])
        self.assertEqual(seen[2][0], "Bearer second-local-secret-456")
        self.assertIn("Mia keeps the same colors.", json.dumps(seen[2][1]["messages"]))
        self.assertEqual(result["checkpoint"]["history_turns"], 2)
        full = (ProjectMemory(self.workspace, "mia").root / "mia.history.jsonl").read_text("utf-8")
        self.assertNotIn("first-local-secret-123", full)
        self.assertNotIn("second-local-secret-456", full)
        self.assertEqual(len(full.splitlines()), 2)

    def test_malformed_tier_cannot_create_pending_work(self):
        with self.assertRaisesRegex(OctavaAdviceError, "model tier"):
            request_advice("Please start", tier="expensive-unapproved", project_id="mia")
        self.assertFalse(ProjectMemory(self.workspace, "mia").path.exists())

    def test_structured_mailbox_accepts_only_fixed_tiers(self):
        task = {
            "protocol_version": 1, "task_id": "test-model-choice",
            "operation": "octava_advice",
            "created_at": "2026-10-12T10:00:00Z",
            "expires_at": "2026-10-12T11:00:00Z",
            "requires_local_approval": True,
            "arguments": {"prompt": "Plan simple steps", "project_id": "mia", "tier": "complex"}
        }
        self.assertEqual(parse_task(json.dumps(task)).arguments["tier"], "complex")
        task["arguments"] = {"project_id": "mia", "resume_pending": True, "tier": "complex"}
        self.assertEqual(parse_task(json.dumps(task)).arguments["tier"], "complex")
        for value in (True, "opus-5", None, "../bad"):
            task["arguments"]["tier"] = value
            with self.assertRaises(ProtocolError):
                parse_task(json.dumps(task))
        task["arguments"] = {"prompt": "Safe", "tier": "simple", "shell": "evil"}
        with self.assertRaises(ProtocolError):
            parse_task(json.dumps(task))


if __name__ == "__main__":
    unittest.main()
