"""Interactive GitHub mailbox poller for bounded diagnostic tasks.

This is an initial poll-loop implementation, not a general coding agent.
Code edits and service-control operations remain unsupported until separately
implemented and reviewed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any

from local_agent.cli import doctor, run_tests, status, tail_logs
from local_agent.github_queue import GitHubQueueClient, QueueConfig, QueueTransportError

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / ".local_agent" / "poller_state.json"
SUPPORTED_HANDLERS = {
    "doctor": doctor,
    "status": status,
    "logs": tail_logs,
    "test": run_tests,
}


def _load_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(data: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(STATE_PATH)


def _not_expired(task: Any) -> bool:
    try:
        expiry = datetime.fromisoformat(task.expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            return False
        return expiry > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def _run_one(client: GitHubQueueClient, task: Any) -> None:
    if not _not_expired(task):
        client.publish_result(task.task_id, {
            "task_id": task.task_id, "status": "rejected", "reason": "expired_or_invalid_expiry"
        })
        return
    handler = SUPPORTED_HANDLERS.get(task.operation)
    if handler is None:
        client.publish_result(task.task_id, {
            "task_id": task.task_id,
            "status": "unsupported",
            "reason": "operation_has_no_implemented_local_handler",
            "supported_operations": sorted(SUPPORTED_HANDLERS),
        })
        return
    print(f"\nNew task: {task.task_id} | operation={task.operation}")
    print("Arguments:", json.dumps(task.arguments, ensure_ascii=False))
    print("Only allowlisted diagnostic handlers are currently supported.")
    answer = input("Approve this local operation? Type YES to run: ").strip()
    if answer != "YES":
        result = {"task_id": task.task_id, "status": "declined", "reason": "local_user_declined"}
    else:
        try:
            details = handler()
            result = {"task_id": task.task_id, "status": "completed", "details": details}
        except Exception as exc:  # Keep error details bounded and avoid leaking tracebacks.
            result = {"task_id": task.task_id, "status": "error", "error_type": type(exc).__name__}
    commit_sha = client.publish_result(task.task_id, result)
    print(f"Result published. GitHub commit: {commit_sha}")


def main() -> int:
    try:
        config = QueueConfig.from_environment()
        client = GitHubQueueClient(config)
    except Exception as exc:
        print(f"Cannot start mailbox poller: {type(exc).__name__}: {exc}")
        return 2

    interval = max(5, min(int(os.environ.get("LOCAL_AGENT_POLL_SECONDS", "10")), 30))
    backoff = interval
    last_seen = _load_state().get("last_task_id")
    print(f"Polling private GitHub mailbox every {interval}s. Press Ctrl+C to stop.")
    print("This poller supports diagnostics only; code changes are not implemented.")

    while True:
        try:
            fetched = client.fetch_desired_task()
            if fetched is not None:
                task, manifest_sha = fetched
                if task.task_id != last_seen:
                    _run_one(client, task)
                    last_seen = task.task_id
                    _save_state({"last_task_id": last_seen, "manifest_sha": manifest_sha})
            backoff = interval
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nPoller stopped.")
            return 0
        except QueueTransportError as exc:
            print(f"Mailbox check failed: {exc}. Retry in {backoff}s.")
            time.sleep(backoff)
            backoff = min(max(interval, backoff * 2), 300)
        except (OSError, ValueError) as exc:
            print(f"Poller local error: {type(exc).__name__}. Retry in {backoff}s.")
            time.sleep(backoff)
            backoff = min(max(interval, backoff * 2), 300)


if __name__ == "__main__":
    raise SystemExit(main())
