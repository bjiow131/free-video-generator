"""Offline tests: rotate via UI without exposing key or affecting GitHub."""
from __future__ import annotations
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from local_agent import octava_credentials as keys


class Reply:
    def __init__(self, content=None):
        self.stream = io.BytesIO(json.dumps(content if content is not None else
              {"choices": [{"message": {"content": "OK"}}]}).encode())
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.stream.close()
    def read(self, size=-1):
        return self.stream.read(size)


class TestRotation(unittest.TestCase):
    def test_candidate_validated_before_write_and_result_redacted(self):
        writes = []
        def fake_probe(req, timeout):
            self.assertEqual(timeout, 18)
            self.assertIn("new-secret-test-123456", req.get_header("Authorization"))
            return Reply()
        def fake_write(key):
            writes.append(key)
        with patch.object(keys.os, "name", "nt"), patch.object(keys, "store_key", side_effect=fake_write):
            result = keys.replace_key("  new-secret-test-123456  ", transport=fake_probe)
        self.assertEqual(writes, ["new-secret-test-123456"])
        self.assertTrue(result["validated"])
        self.assertNotIn("secret", repr(result))
        self.assertTrue(result["github_connection_independent"])

    def test_failed_key_never_replaces_previous(self):
        with patch.object(keys.os, "name", "nt"), patch.object(keys, "store_key") as writer:
            def unauthorized(req, timeout):
                raise HTTPError(req.full_url, 401, "no", {}, None)
            with self.assertRaisesRegex(keys.OctavaKeyError, "401"):
                keys.replace_key("new-secret-test-123456", transport=unauthorized)
            writer.assert_not_called()

    def test_no_persistence_on_nonwindows(self):
        with patch.object(keys.os, "name", "posix"), patch.object(keys, "store_key") as writer:
            with self.assertRaisesRegex(keys.OctavaKeyError, "Windows"):
                keys.replace_key("new-secret-test-123456", transport=lambda *_a, **_k: Reply())
            writer.assert_not_called()

    def test_invalid_key_rejected_without_network(self):
        with patch.object(keys, "probe_key") as p:
            for value in ("", "short", "a b 123456789000", "x\ny12345678900", None):
                with self.assertRaises(keys.OctavaKeyError):
                    keys.replace_key(value)
            p.assert_not_called()

    def test_status_has_no_key(self):
        with patch.object(keys, "read_key", return_value=("protected-secr3t-abcd", "windows_vault")):
            result = keys.key_status()
        self.assertTrue(result["stored_locally"])
        self.assertNotIn("protected-secr3t", json.dumps(result))

    def test_read_after_rotation_on_every_request(self):
        with patch.object(keys.os, "name", "posix"), patch.dict(keys.os.environ, {"OCTAVA_API_KEY": "first-test-key-123"}):
            self.assertEqual(keys.read_key()[0], "first-test-key-123")
            keys.os.environ["OCTAVA_API_KEY"] = "second-test-key-456"
            self.assertEqual(keys.read_key()[0], "second-test-key-456")


if __name__ == "__main__":
    unittest.main()