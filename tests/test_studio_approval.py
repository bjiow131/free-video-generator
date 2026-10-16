from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from local_agent.studio_approval import StudioApprovalError, StudioApprovalStore


def task(task_id="mia-inspect-001", operation="blender_inspect_mia_project", arguments=None, expires_delta=300):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        task_id=task_id,
        operation=operation,
        arguments=arguments if arguments is not None else {"project_name": "mia_story"},
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=expires_delta)).isoformat(),
    )


class StudioApprovalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StudioApprovalStore(Path(self.temp.name) / ".local_agent")

    def test_local_approval_round_trip(self):
        request = self.store.create_request(task())
        self.assertEqual(self.store.get_pending(), request)
        self.assertEqual(self.store.decide(request["task_id"], "approve")["decision"], "approve")
        self.assertEqual(self.store.wait_for_decision(request["task_id"], request["expires_at"], 1), "approve")
        self.store.clear_request(request["task_id"])
        self.assertIsNone(self.store.get_pending())

    def test_auto_approval_is_off_by_default_and_persists(self):
        self.assertFalse(self.store.auto_approve_enabled())
        self.store.set_auto_approve(True)
        reopened = StudioApprovalStore(Path(self.temp.name) / ".local_agent")
        self.assertTrue(reopened.auto_approve_enabled())
        reopened.set_auto_approve(False)
        self.assertFalse(self.store.auto_approve_enabled())

    def test_auto_approval_resolves_pending_task(self):
        request = self.store.create_request(task())
        self.store.set_auto_approve(True)
        self.assertEqual(
            self.store.wait_for_decision(request["task_id"], request["expires_at"], 1),
            "approve",
        )
        decision_path = self.store._decision_path(
            request["task_id"], self.store.decisions_dir
        )
        decision = self.store._read(decision_path, 4096)
        self.assertEqual(decision["approval_mode"], "persistent_toggle")

    def test_rejection_round_trip(self):
        request = self.store.create_request(task())
        self.store.decide(request["task_id"], "reject")
        self.assertEqual(self.store.wait_for_decision(request["task_id"], request["expires_at"], 1), "reject")

    def test_only_matching_pending_task_can_be_decided(self):
        self.store.create_request(task())
        with self.assertRaises(StudioApprovalError):
            self.store.decide("different-task", "approve")

    def test_invalid_decision_is_rejected(self):
        request = self.store.create_request(task())
        with self.assertRaises(StudioApprovalError):
            self.store.decide(request["task_id"], "run_anything")

    def test_second_pending_task_cannot_replace_first(self):
        first = self.store.create_request(task("first-task"))
        with self.assertRaises(StudioApprovalError):
            self.store.create_request(task("second-task"))
        self.assertEqual(self.store.get_pending()["task_id"], first["task_id"])

    def test_expired_task_is_not_presented_or_approved(self):
        stale = task(expires_delta=-1)
        with self.assertRaises(StudioApprovalError):
            self.store.create_request(stale)

    def test_patch_contents_are_available_for_local_review(self):
        patch = "diff --git a/local_agent/a.py b/local_agent/a.py\n+safe change\n"
        request = self.store.create_request(task(operation="apply_patch", arguments={"patch": patch}))
        self.assertEqual(self.store.get_pending()["arguments"]["patch"], patch)

    def test_timeout_returns_without_approval(self):
        request = self.store.create_request(task())
        self.assertEqual(self.store.wait_for_decision(request["task_id"], request["expires_at"], 1), "timeout")


    def test_studio_installer_includes_local_approval_runtime(self):
        installer = Path(__file__).resolve().parents[1] / "install_blender_studio.ps1"
        source = installer.read_text(encoding="utf-8")
        names = source.split("$Names = @(", 1)[1].split(")", 1)[0]
        self.assertIn("'local_agent\\studio_approval.py'", names)
        self.assertIn("'local_agent\\poller.py'", names)
        self.assertIn("'tests\\test_studio_approval.py'", names)


if __name__ == "__main__":
    unittest.main()
