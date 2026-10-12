"""Approved Mia turnaround is visible and attachable without any new synthesis."""
from __future__ import annotations

import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from local_agent import studio_references as refs
from local_agent.studio_state import StudioConflict, StudioError, StudioStore
from local_agent.studio_server import StudioHandler


class ApprovedReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.store = StudioStore(self.workspace)
        self.source = self.workspace.joinpath(*refs.APPROVED_RELATIVE)
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.image = b"\xff\xd8\xff" + b"approved-example-test-bytes"
        self.digest = hashlib.sha256(self.image).hexdigest()
        self.sha_patch = patch.object(refs, "APPROVED_SHA256", self.digest)
        self.size_patch = patch.object(refs, "APPROVED_SIZE", len(self.image))
        self.sha_patch.start()
        self.size_patch.start()
        self.addCleanup(self.sha_patch.stop)
        self.addCleanup(self.size_patch.stop)
        self.source.write_bytes(self.image)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), StudioHandler)
        self.server.store = self.store
        self.server.octava_lock = threading.Lock()
        self.server.mailbox_policy_lock = threading.Lock()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def http(self, method, path, body=None, origin=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        headers = {}
        if method == "POST":
            headers["Content-Type"] = "application/json"
            if origin:
                headers["Origin"] = f"http://127.0.0.1:{self.server.server_port}"
            body = json.dumps(body or {}).encode("utf-8")
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            status = response.status
            content_type = response.getheader("Content-Type")
            content = response.read()
            if content_type and content_type.startswith("application/json"):
                return status, json.loads(content)
            return status, content
        finally:
            conn.close()

    def test_approved_turnaround_is_visible_and_not_misrepresented_as_3d(self):
        code, data = self.http("GET", "/api/approved-references")
        self.assertEqual(code, 200)
        entry = data["references"][0]
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(entry["views"], ["Анфас", "Профиль", "Со спины"])
        self.assertIn("ещё не утверждены", entry["model_status"])
        code, body = self.http("GET", entry["url"])
        self.assertEqual(code, 200)
        self.assertEqual(body, self.image)

    def test_missing_and_invalid_assets_cannot_be_displayed_or_attached(self):
        self.source.write_bytes(b"tampered")
        code, data = self.http("GET", "/api/approved-references")
        self.assertEqual(code, 200)
        self.assertEqual(data["references"][0]["status"], "invalid")
        self.assertEqual(self.http("GET", "/api/approved-reference-image/mia")[0], 404)
        self.assertEqual(self.http("POST", "/api/link-mia-reference", {"revision": 0})[0], 400)
        self.source.unlink()
        code, data = self.http("GET", "/api/approved-references")
        self.assertEqual(data["references"][0]["status"], "missing")

    def test_attach_updates_only_mia_media_field(self):
        initial = self.store.load()
        initial["characters"][0]["appearance"] = "User-edited approved appearance"
        initial["characters"][0]["outfit"] = "Do not replace existing wardrobe"
        saved = self.store.save(initial, 0)
        before_revision = saved["revision"]
        code, result = self.http("POST", "/api/link-mia-reference", {"revision": before_revision})
        self.assertEqual(code, 200)
        self.assertEqual(result["revision"], before_revision+1)
        mia = result["characters"][0]
        self.assertEqual(mia["appearance"], "User-edited approved appearance")
        self.assertEqual(mia["outfit"], "Do not replace existing wardrobe")
        self.assertEqual(mia["reference"], refs.MEDIA_FILENAME)
        self.assertEqual((self.store.root/"studio_media"/refs.MEDIA_FILENAME).read_bytes(),self.image)
        self.assertEqual(self.http("GET", "/media/"+refs.MEDIA_FILENAME), (200, self.image))
        self.assertEqual(self.store.load()["characters"][0]["reference"], refs.MEDIA_FILENAME)
        # Repeating the action is idempotent, no gratuitous revision.
        code, repeated = self.http("POST", "/api/link-mia-reference", {"revision": before_revision+1})
        self.assertEqual(code, 200)
        self.assertEqual(repeated["revision"], before_revision+1)

    def test_link_rejects_stale_revision_unexpected_fields_and_bad_origin(self):
        self.assertEqual(self.http("POST", "/api/link-mia-reference", {"revision": 12})[0], 409)
        self.assertEqual(self.http("POST", "/api/link-mia-reference", {"revision": 0, "path": "x"})[0], 400)
        self.assertEqual(self.http("POST", "/api/link-mia-reference", {"revision": 0}, origin=False)[0], 403)
        self.assertEqual(self.store.load()["revision"], 0)
        self.assertEqual(self.store.load()["characters"][0]["reference"], "")

    def test_symlink_source_cannot_be_read(self):
        self.source.unlink()
        try:
            self.source.symlink_to(self.workspace/"some-other.jpeg")
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unsupported")
        self.assertEqual(self.http("GET", "/api/approved-references")[1]["references"][0]["status"], "invalid")
        self.assertEqual(self.http("GET", "/api/approved-reference-image/mia")[0],404)


if __name__ == "__main__":
    unittest.main()
