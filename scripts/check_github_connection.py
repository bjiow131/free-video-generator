"""Check GitHub mailbox credentials and write a harmless connection-test result.

This script does not fetch or execute queue/desired_task.json.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json

from local_agent.github_queue import GitHubQueueClient, QueueConfig

def main() -> int:
    try:
        client = GitHubQueueClient(QueueConfig.from_environment())
        client._require_private_repo()
        task_id = "connection-check-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        commit_sha = client.publish_result(task_id, {
            "task_id": task_id,
            "status": "connection_test",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "message": "GitHub mailbox authentication, private-repository access, and result write succeeded.",
        })
        print(json.dumps({
            "status": "connected",
            "repository": client.config.repository,
            "result_path": f"queue/results/{task_id}.json",
            "commit_sha": commit_sha,
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        # Do not print request headers, tokens, or raw response bodies.
        print(json.dumps({
            "status": "failed",
            "error_type": type(exc).__name__,
            "message": str(exc)[:240],
        }, ensure_ascii=False, indent=2))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
