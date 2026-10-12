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
        cls.server.mailbox_policy_lock = threading.Lock()
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

    def test_mailbox_policy_get_does_not_expose_tokens(self):
        settings = {"enabled": True, "allow_octava": True,
                    "allow_blender": False, "allow_tests": False}
        with patch("local_agent.studio_server.load_policy", return_value=settings):
            status, data = self.fetch("GET", "/api/mailbox-policy")
        self.assertEqual(status, 200)
        self.assertEqual(data, settings)
        self.assertNotIn("api_key", json.dumps(data))

    def test_mailbox_policy_requires_browser_origin(self):
        settings = {"enabled": True, "allow_octava": False,
                    "allow_blender": False, "allow_tests": False}
        with patch("local_agent.studio_server.save_policy") as save:
            status, _ = self.fetch("POST", "/api/mailbox-policy",
                                   settings, include_origin=False)
        self.assertEqual(status, 403)
        save.assert_not_called()

    def test_mailbox_policy_updated_from_studio(self):
        settings = {"enabled": True, "allow_octava": False,
                    "allow_blender": True, "allow_tests": False}
        with patch("local_agent.studio_server.save_policy", return_value=settings) as save:
            status, result = self.fetch("POST", "/api/mailbox-policy", settings)
        self.assertEqual(status, 200)
        self.assertEqual(result, settings)
        save.assert_called_once_with(settings)

    def test_trusted_updates_disabled_by_default(self):
        with patch("local_agent.studio_server.get_opt_in", return_value={"enabled": False}):
            status, data = self.fetch("GET", "/api/trusted-updates")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"enabled": False})

    def test_trusted_updates_requires_same_origin(self):
        with patch("local_agent.studio_server.set_opt_in") as save:
            status, _ = self.fetch("POST", "/api/trusted-updates", {"enabled": True},
                                   include_origin=False)
        self.assertEqual(status, 403)
        save.assert_not_called()

    def test_trusted_updates_can_be_locally_enabled_or_disabled(self):
        for enabled in (True, False):
            with patch("local_agent.studio_server.set_opt_in",
                       return_value={"enabled": enabled}) as save:
                status, data = self.fetch("POST", "/api/trusted-updates", {"enabled": enabled})
            self.assertEqual(status, 200)
            self.assertEqual(data, {"enabled": enabled})
            save.assert_called_once_with({"enabled": enabled})

    def test_telegram_notifications_status_and_toggle(self):
        with patch("local_agent.studio_server.load_telegram_notifications", return_value={"enabled": False}):
            status, data = self.fetch("GET", "/api/telegram-notifications")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"notifications_enabled": False})
        with patch("local_agent.studio_server.telegram_set_notifications",
                   return_value={"notifications_enabled": True}) as setter:
            status, data = self.fetch("POST", "/api/telegram-notifications", {"enabled": True})
        self.assertEqual(status, 200)
        self.assertEqual(data, {"notifications_enabled": True})
        setter.assert_called_once_with({"enabled": True})

    def test_telegram_notification_toggle_requires_same_origin(self):
        with patch("local_agent.studio_server.telegram_set_notifications") as setter:
            status, _ = self.fetch("POST", "/api/telegram-notifications",
                                   {"enabled": False}, include_origin=False)
        self.assertEqual(status, 403)
        setter.assert_not_called()

    def test_telegram_notification_toggle_rejects_extra_fields(self):
        status, data = self.fetch("POST", "/api/telegram-notifications",
                                  {"enabled": False, "bot_token": "should-not-store"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_agent_restart_local_origin_only(self):
        with patch("local_agent.studio_server.request_runtime_restart",
                   return_value={"restart_pending": True}) as request:
            status, _ = self.fetch("POST", "/api/agent-restart", {}, include_origin=False)
            self.assertEqual(status, 403)
            request.assert_not_called()
            status, data = self.fetch("POST", "/api/agent-restart", {})
            self.assertEqual(status, 202)
            self.assertEqual(data, {"restart_pending": True})
            request.assert_called_once_with({})

    def test_agent_pause_local_origin_only(self):
        with patch("local_agent.studio_server.set_runtime_pause",
                   return_value={"paused": True}) as pause:
            status, _ = self.fetch("POST", "/api/agent-pause", {"paused": True},
                                   include_origin=False)
            self.assertEqual(status, 403)
            pause.assert_not_called()
            status, data = self.fetch("POST", "/api/agent-pause", {"paused": True})
            self.assertEqual(status, 200)
            self.assertEqual(data, {"paused": True})

    def test_agent_control_rejects_extra_fields(self):
        with patch("local_agent.studio_server.set_runtime_pause") as pause:
            status, _ = self.fetch("POST", "/api/agent-pause",
                                   {"paused": True, "command": "powershell.exe"})
            self.assertEqual(status, 400)
            pause.assert_not_called()

    def test_extra_fields_forbidden(self):
        with patch("local_agent.studio_server.replace_key") as save:
            status, _ = self.fetch("POST", "/api/octava-key", {"api_key": "secret-123456789", "command": "rm -rf"})
        self.assertEqual(status, 400)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()