"""Offline tests for local, opt-in OctavAPI advice and mailbox validation."""
import io
import json
import os
import unittest
from unittest.mock import patch

from local_agent.octava_advisor import OctavaAdviceError, request_advice, validate_prompt
from local_agent.control_protocol import ProtocolError, parse_task


class Response:
    def __init__(self, data):
        self.stream = io.BytesIO(json.dumps(data).encode("utf-8"))
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.stream.close()
    def read(self, size=-1):
        return self.stream.read(size)


class OctavaAdviceTests(unittest.TestCase):
    def test_opt_in_required(self):
        with patch.dict(os.environ, {"OCTAVA_API_KEY": "mock-test-key"}, clear=True):
            with self.assertRaisesRegex(OctavaAdviceError, "disabled"):
                request_advice("Как организовать движение камеры?")

    def test_key_is_required_and_not_revealed(self):
        with patch.dict(os.environ, {"LOCAL_AGENT_ALLOW_OCTAVA": "1"}, clear=True):
            with self.assertRaisesRegex(OctavaAdviceError, "missing"):
                request_advice("Как организовать движение камеры?")

    def test_rejects_credentials_and_long_input(self):
        for value in ["token=ABCDEFpassword1234", "sk-" + "a" * 20, "x" * 1601]:
            with self.assertRaises(OctavaAdviceError):
                validate_prompt(value)

    def test_bounded_message_one_call(self):
        seen = []
        def transport(req, timeout):
            seen.append((req, timeout))
            return Response({"choices": [{"message": {"content": "Нужно начать с простого движения."}}],
                             "usage": {"total_tokens": 15, "extra": "private"}})
        with patch.dict(os.environ, {"LOCAL_AGENT_ALLOW_OCTAVA": "1", "OCTAVA_API_KEY": "test-never-real"}, clear=True):
            result = request_advice("Мия идёт по дорожке", transport=transport)
        self.assertEqual(len(seen), 1)
        req, timeout = seen[0]
        self.assertEqual(req.full_url, "https://octavapi.shop/v1/chat/completions")
        self.assertEqual(timeout, 25)
        self.assertEqual(json.loads(req.data)["max_tokens"], 320)
        self.assertEqual(result["usage"], {"total_tokens": 15})
        self.assertFalse(result["executed_anything"])
        self.assertNotIn("test-never-real", repr(result))

    def test_malformed_model_and_response(self):
        with patch.dict(os.environ, {"LOCAL_AGENT_ALLOW_OCTAVA": "1", "OCTAVA_API_KEY": "test-never-real", "OCTAVA_MODEL": "../../bad"}, clear=True):
            with self.assertRaisesRegex(OctavaAdviceError, "model"):
                request_advice("Сцена")
        with patch.dict(os.environ, {"LOCAL_AGENT_ALLOW_OCTAVA": "1", "OCTAVA_API_KEY": "test-never-real"}, clear=True):
            with self.assertRaisesRegex(OctavaAdviceError, "Unexpected"):
                request_advice("Сцена", transport=lambda *_args, **_kwargs: Response({"oops": True}))

    def test_mailbox_allows_only_specific_prompt_field(self):
        base = {"protocol_version": 1, "task_id": "octava-connectivity-01",
                "operation": "octava_advice", "created_at": "2026-10-11T16:00:00Z",
                "expires_at": "2026-10-11T17:00:00Z",
                "requires_local_approval": True,
                "arguments": {"prompt": "Как поставить камеру для сцены?"}}
        parsed = parse_task(json.dumps(base, ensure_ascii=False))
        self.assertEqual(parsed.operation, "octava_advice")
        for args in ({"prompt": "a", "command": "whoami"}, {"prompt": ""}, {"prompt": "x" * 1601}):
            bad = dict(base, arguments=args)
            with self.assertRaises(ProtocolError):
                parse_task(json.dumps(bad))


if __name__ == "__main__":
    unittest.main()