"""Loopback API regression tests: keys never appear in GET responses or files."""
from __future__ import annotations
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from local_agent.octava_credentials import OctavaKeyError
from local_agent.studio_server import StudioHandler


class LocalKeyHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), StudioHandler)
        cls.server.octava_lock = threading.Lock()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def fetch(self, method, path, body=None, *, include_origin=True, headers=None):
        con = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        hdr = dict(headers or {})
        if method == "POST":
            hdr["Content-Type"] = "application/json"
            if include_origin:
                hdr["Origin"] = f"http://127.0.0.1:{self.server.server_port}"
            body = json.dumps(body).encode("utf-8") if body is not None else b"{}"
        try:
            con.request(method, path, body=body, headers=hdr)
            response = con.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            con.close()

    def test_status_does_not_reflect_key(self):
        with patch("local_agent.studio_server.key_status", return_value={"configured": True, "stored_locally": True}):
            status, body = self.fetch("GET", "/api/octava-key")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"configured": True, "stored_locally": True})

    def test_successful_rotation_returns_only_status(self):
        secret = "never-publish-or-log-987654321"
        with patch("local_agent.studio_server.replace_key", return_value={"configured": True, "validated": True}) as save:
            status, body = self.fetch("POST", "/api/octava-key", {"api_key": secret})
        self.assertEqual(status, 200)
        save.assert_called_once_with(secret)
        self.assertNotIn(secret, json.dumps(body))

    def test_rejected_rotation_does_not_expose_key(self):
        secret = "secret-incorrect-987654321"
        with patch("local_agent.studio_server.replace_key", side_effect=OctavaKeyError("Ключ OctavAPI отклонён (401/403)")):
            status, body = self.fetch("POST", "/api/octava-key", {"api_key": secret})
        self.assertEqual(status, 400)
        self.assertNotIn(secret, json.dumps(body))
        self.assertIn("отклонён", body["error"])

    def test_origin_required_for_key_rotation(self):
        with patch("local_agent.studio_server.replace_key") as save:
            status, _ = self.fetch("POST", "/api/octava-key", {"api_key": "secret-123456789"}, include_origin=False)
        self.assertEqual(status, 403)
        save.assert_not_called()

    def test_extra_fields_forbidden(self):
        with patch("local_agent.studio_server.replace_key") as save:
            status, _ = self.fetch("POST", "/api/octava-key", {"api_key": "secret-123456789", "command": "rm -rf"})
        self.assertEqual(status, 400)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()