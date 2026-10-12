"""Tests for credential-free fixed-target OctavAPI connectivity diagnostics."""
import io
import socket
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from local_agent.poller import octava_network_diagnostics
from local_agent.control_protocol import parse_task, ProtocolError
from local_agent.mailbox_policy import is_auto_authorized
import json


class FakeResponse:
    status = 200
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class ConnectivityTests(unittest.TestCase):
    def test_no_auth_header_and_get_only(self):
        def responder(req, timeout):
            self.assertEqual(req.get_method(), "GET")
            self.assertEqual(req.full_url, "https://octavapi.shop/v1")
            self.assertIsNone(req.get_header("Authorization"))
            self.assertEqual(timeout, 8)
            return FakeResponse()
        with patch("socket.getaddrinfo", return_value=[("fixed",)]), \
             patch("urllib.request.urlopen", side_effect=responder), \
             patch("urllib.request.getproxies", return_value={}):
            result = octava_network_diagnostics()
        self.assertEqual(result["https"], "reachable")
        self.assertEqual(result["dns"], "ok")
        self.assertFalse(result["api_key_sent"])

    def test_http_error_is_reachable(self):
        with patch("socket.getaddrinfo", return_value=[]), \
             patch("urllib.request.urlopen", side_effect=HTTPError("fixed", 401, "unauthorized", {}, io.BytesIO())), \
             patch("urllib.request.getproxies", return_value={"https": "hidden"}):
            result = octava_network_diagnostics()
        self.assertEqual(result["https_status"], 401)
        self.assertTrue(result["https_proxy_configured"])
        self.assertNotIn("hidden", str(result))

    def test_dns_failure_classified_without_leak(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror()), \
             patch("urllib.request.urlopen", side_effect=URLError(socket.gaierror())), \
             patch("urllib.request.getproxies", return_value={}):
            result = octava_network_diagnostics()
        self.assertEqual(result["dns"], "failed")
        self.assertEqual(result["https"], "dns_error")

    def test_operation_requires_empty_arguments(self):
        obj = {"protocol_version": 1, "task_id": "octava-network-audit",
               "operation": "octava_connectivity",
               "created_at": "2026-10-12T18:00:00Z",
               "expires_at": "2026-10-12T18:30:00Z",
               "requires_local_approval": True, "arguments": {}}
        self.assertEqual(parse_task(json.dumps(obj)).operation, "octava_connectivity")
        obj["arguments"] = {"url": "https://another-site.example"}
        with self.assertRaises(ProtocolError):
            parse_task(json.dumps(obj))

    def test_unattended_readonly_operation(self):
        p = {"enabled": True, "allow_octava": False,
             "allow_blender": False, "allow_tests": False,
             "allow_asset_sync": False}
        self.assertTrue(is_auto_authorized("octava_connectivity", p))


if __name__ == "__main__":
    unittest.main()
