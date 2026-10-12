"""Safe OctavAPI Luna/Sol routing on top of the *installed* memory bridge."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_agent import octava_credentials as keys
from local_agent.octava_advisor import request_advice, OctavaAdviceError
from local_agent.mailbox_policy import OctavaProjectMemory
from local_agent.poller import _run_octava_advice


class Reply:
    def __init__(self):
        self.file = io.BytesIO(b'{"choices":[{"message":{"content":"OK"}}]}')
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.file.close()
    def read(self, n=-1):
        return self.file.read(n)


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.settings = Path(self.td.name) / "studio" / "octava_default_model.json"
        patcher = patch.object(keys, "MODEL_SETTINGS", self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_and_explicit_tiers(self):
        with patch.dict(keys.os.environ, {}, clear=True):
            self.assertEqual(keys.model_for_tier(), "gpt-6-luna")
            self.assertEqual(keys.model_for_tier("simple"), "gpt-6-luna")
            self.assertEqual(keys.model_for_tier("complex"), "gpt-6.1-sol")
            with self.assertRaises(keys.OctavaKeyError):
                keys.model_for_tier("arbitrary")

    def test_model_switch_is_atomic_and_key_independent(self):
        with patch.object(keys, "read_key", return_value=("private-key-example", "windows_vault")), \
             patch.object(keys, "probe_key") as probe:
            status = keys.set_default_model({"model": "gpt-6.1-sol"})
            probe.assert_called_once_with("private-key-example", transport=None,
                                          model="gpt-6.1-sol")
            self.assertEqual(status["model"], "gpt-6.1-sol")
            self.assertEqual(keys.model_for_tier("default"), "gpt-6.1-sol")
            self.assertEqual(keys.model_for_tier("simple"), "gpt-6-luna")
            data = self.settings.read_text("utf-8")
            self.assertNotIn("private-key", data)
            self.assertEqual(set(json.loads(data)), {"model"})

    def test_failed_probe_never_commits(self):
        with patch.object(keys, "read_key", return_value=("private-key", "windows_vault")), \
             patch.object(keys, "probe_key", side_effect=keys.OctavaKeyError("offline")):
            with self.assertRaisesRegex(keys.OctavaKeyError, "offline"):
                keys.set_default_model({"model": "gpt-6.1-sol"})
        self.assertFalse(self.settings.exists())
        self.assertEqual(keys.configured_model(), "gpt-6-luna")

    def test_no_credential_in_model_state(self):
        with patch.object(keys, "read_key", return_value=("secret-in-vault", "windows_vault")):
            status = keys.key_status()
        self.assertNotIn("secret-in-vault", json.dumps(status))

    def test_routing_uses_vault_without_tampering(self):
        seen = []
        def fake_send(req, timeout):
            self.assertEqual(timeout, 25)
            seen.append((json.loads(req.data)["model"], req.get_header("Authorization")))
            return Reply()
        with patch.object(keys, "read_key", return_value=("vault-value-123", "windows_vault")):
            self.assertEqual(request_advice("short", tier="simple", transport=fake_send)["model_requested"], "gpt-6-luna")
            self.assertEqual(request_advice("hard", tier="complex", transport=fake_send)["model_requested"], "gpt-6.1-sol")
            with self.assertRaises(OctavaAdviceError):
                request_advice("unsafe", tier="unknown", transport=fake_send)
        self.assertEqual(seen, [("gpt-6-luna", "Bearer vault-value-123"),
                                ("gpt-6.1-sol", "Bearer vault-value-123")])

    def test_existing_memory_wrap_remains_compatible(self):
        with patch("local_agent.octava_advisor.request_advice",
                   side_effect=lambda prompt, *, tier="default":
                   {"status": "completed", "advice": "2.5D Mia", "model_requested": keys.model_for_tier(tier)}) as called:
            a = _run_octava_advice({"project_id": "mia", "prompt": "Save reference", "tier": "simple"},
                                   workspace=self.td.name)
            b = _run_octava_advice({"project_id": "mia", "prompt": "Recall reference", "tier": "complex"},
                                   workspace=self.td.name)
        self.assertEqual(a["checkpoint"]["history_turns"], 1)
        self.assertEqual(b["checkpoint"]["history_turns"], 2)
        self.assertEqual(b["checkpoint"]["status"], "idle")
        self.assertEqual(b["model_requested"], "gpt-6.1-sol")
        self.assertIn("2.5D Mia", called.call_args_list[-1].args[0])
        mem = OctavaProjectMemory(self.td.name, "mia")
        self.assertEqual(len(mem.snapshot()["history"]), 2)


if __name__ == "__main__":
    unittest.main()
