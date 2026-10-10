"""Regression tests for mailbox result delivery state."""
from local_agent.poller import _task_delivery_status


def test_pending_result_is_not_marked_processed() -> None:
    assert _task_delivery_status("task-123", {"task-123"}) == "pending_delivery"


def test_result_without_outbox_entry_is_marked_processed() -> None:
    assert _task_delivery_status("task-123", set()) == "processed"


def test_other_task_pending_does_not_block_this_task() -> None:
    assert _task_delivery_status("task-123", {"task-456"}) == "processed"
