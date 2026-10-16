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


if __name__ == "__main__":
    unittest.main()
