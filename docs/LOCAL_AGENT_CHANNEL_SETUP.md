# Private GitHub mailbox setup for the local Windows agent

Status: implementation exists on `feature/local-first-migration`; the end-to-end channel is **not active yet**. Do not use the public `free-video-generator` repository as the mailbox. The poller intentionally refuses any repository that GitHub does not confirm is private.

## What the channel will do

1. ChatGPT writes one validated JSON task to `queue/desired_task.json` in a dedicated private mailbox repository.
2. The Windows agent polls GitHub over outbound HTTPS (default: every 10 seconds; bounded to 5–30 seconds).
3. The agent validates the schema, expiry, operation allowlist, and task ID. It records the task ID before execution to prevent blind replay.
4. By default, the agent asks for local console approval before executing a task.
5. It writes a redacted local report first, then publishes the bounded result to `queue/results/<task_id>.json`.
6. ChatGPT can read that result only if the private mailbox repository is also available through the connected GitHub integration. This is not a push connection: the local agent cannot send an unsolicited message into this chat.

## One-time GitHub setup

1. Create a **new private repository** dedicated to this agent, e.g. `local-agent-mailbox`. Do not use the public application repository or an unrelated private repository.
2. Add a `queue` directory and commit `queue/desired_task.json` using the initial task template below. The agent expects this exact path by default.
3. Make the new private repository available to the GitHub integration used in ChatGPT. If it is not listed as accessible, the assistant will not be able to write or read mailbox files from this chat.
4. Create a fine-grained GitHub token restricted to that single mailbox repository. Grant only **Contents: Read and write** (GitHub's repository metadata permission is read-only by default). Do not paste the token into ChatGPT or commit it to a file.
5. On the Windows computer, install Python 3.11+, Git, and Blender. Clone/check out this project branch and install the agent requirements:
   `python -m pip install -r requirements-local-agent.txt`
6. Set the non-secret mailbox settings in PowerShell for the agent's launch environment:
   `$env:LOCAL_AGENT_GITHUB_REPO = "YOUR_LOGIN/local-agent-mailbox"`
   `$env:LOCAL_AGENT_GITHUB_REF = "main"`
   `$env:LOCAL_AGENT_GITHUB_MANIFEST = "queue/desired_task.json"`
   `$env:LOCAL_AGENT_WORKSPACE = "D:\\AI-Agent-Workspace"`
   `$env:BLENDER_EXECUTABLE = "C:\\Program Files\\Blender Foundation\\Blender 4.x\\blender.exe"`
   Replace example paths with the real paths on that PC.
7. Store the token in Windows Credential Manager, with hidden terminal input:
   `python -m local_agent.credentials_cli set`
8. Run `python -m local_agent.cli preflight`. The mailbox configuration should be reported without exposing the token. Resolve any missing checks.
9. Start the interactive poller from the project root:
   `python -m local_agent.poller`
   Keep the terminal open for the first test. Do not install auto-start or a background service until the foreground round-trip is verified.

## Initial task manifest

Use this exact shape for the first harmless connectivity test. Set timestamps to current UTC ISO-8601 values, and make expiry later than creation but no more than 24 hours after it.

```json
{
  "protocol_version": 1,
  "task_id": "connectivity-check-001",
  "operation": "doctor",
  "created_at": "2026-10-10T10:00:00Z",
  "expires_at": "2026-10-10T10:10:00Z",
  "requires_local_approval": true,
  "arguments": {}
}
```

The timestamps above are examples only; replace them when creating the actual manifest. For this first test, the agent should ask for local approval, run only its fixed diagnostic routine, write a local report, and publish a JSON result.

## Safe task rules

- Task messages are data, never shell commands or Python source.
- Use only operations accepted by `local_agent/control_protocol.py`. Unknown operations and extra arguments are rejected.
- Do not enable `LOCAL_AGENT_ALLOW_REMOTE_APPROVAL=1 during the initial test. Local approval should remain on.
- Do not put secrets, private project files, source assets, raw logs, or generated media in task manifests or result JSON.
- A task result is not proof that Blender visually works; Blender version/preflight and a separate test render are needed.
- Do not reuse a task ID for a different manifest. Use a new ID for every task.
- To stop polling, press Ctrl+C in the foreground terminal. No inbound port is opened.

## Definition of a verified connection

The channel is only verified when all of these are observed on the real Windows machine:

- `preflight` reports Python, workspace, Blender, and mailbox configuration as ready.
- The poller confirms it is polling the private repository.
- The agent prompts for local approval of `connectivity-check-001`.
- A result file appears at `queue/results/connectivity-check-001.json`.
- ChatGPT can read that result through the connected GitHub integration.

Until those checks pass, describe the channel as prepared in code but **not connected or tested**.
