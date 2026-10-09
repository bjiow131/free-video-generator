# Private mailbox task template

The source repository and the control mailbox are separate. Create a dedicated **private** GitHub repository for the mailbox, then create this file on its `main` branch:

`queue/desired_task.json`

Start with a harmless preflight task. Replace the ID and timestamps with a fresh unique ID and current UTC timestamps before committing. Expiry should be short (for example, 10 minutes); expired tasks are rejected.

~~~json
{
  "protocol_version": 1,
  "task_id": "preflight-REPLACE-WITH-UNIQUE-ID",
  "operation": "preflight",
  "created_at": "REPLACE_WITH_CURRENT_UTC_ISO8601",
  "expires_at": "REPLACE_WITH_CURRENT_UTC_ISO8601_PLUS_10_MINUTES",
  "requires_local_approval": true,
  "arguments": {}
}
~~~

The timestamp placeholders above are explanatory and are **not valid timestamps** until replaced. The protocol requires timezone-aware ISO 8601 values, such as `2026-10-09T20:30:00Z`.

## Operating rules

- Every new request gets a new `task_id`. Never edit the meaning of an existing ID; the agent treats IDs as immutable.
- The agent polls the configured branch/path every 5–30 seconds (10 seconds by default) and asks for local `YES` approval.
- A successful task result is written to `queue/results/<task_id>.json`. The agent does not execute the same task again just because the manifest remains in place.
- If the task is expired, declined, superseded, or the result is uncertain after a crash, create a new task ID only after reviewing the local files and the result.
- Do not put secrets, arbitrary shell commands, Python source, executable paths, private reference images, or generated media in the mailbox.
- Keep token access limited to this private repository with Contents read/write. The local agent checks repository privacy before reading or writing.

## First connection checklist

1. Configure `LOCAL_AGENT_GITHUB_REPO` as `owner/private-mailbox-repo`, `LOCAL_AGENT_GITHUB_REF=main`, and `LOCAL_AGENT_GITHUB_MANIFEST=queue/desired_task.json`.
2. Store a fine-grained token in Windows Credential Manager with Contents read/write on that mailbox repository only.
3. Start the local poller and approve the preflight task at the PC.
4. Verify that the result JSON appears under `queue/results/`. This first round-trip proves the configured token can read the manifest and write a result; it does not prove Blender can render.
5. Only after that succeeds, try a safe Blender preview with a fresh task ID.
