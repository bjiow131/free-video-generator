# Windows first run and failure-readiness matrix

This is an implementation checklist, not a claim that a real Windows smoke test has passed. The setup script is intended to run only after the source repository is present on the PC.

## Safe first setup

1. Install Python 3.11+ and Blender from their official sources. Install Git if you want the agent to apply reviewed Git patches. The script does not download or silently install these tools.
2. Use a **dedicated PRIVATE GitHub mailbox repository**. Do not use a public source-code repository as the mailbox: the transport deliberately refuses public repositories.
3. Give a fine-grained GitHub token access to that private mailbox repository only, with Contents read/write. Store it in Windows Credential Manager using `python -m local_agent.credentials_cli set`; never put it in task JSON, source code, chat, or a committed .env file.
4. Run `powershell -ExecutionPolicy Bypass -File .\scripts\windows\setup_local_agent.ps1` from the checked-out source repository.
5. Review the diagnostic output and focused tests. Do not start polling if tests fail, the mailbox is public, the token is unconfigured, or the manifest format is invalid.
6. Configure `queue/desired_task.json` in the private mailbox with a valid, short-lived task ID that has never been used before. First task should be a non-destructive `doctor` or `status` check. The agent asks for local approval before running a task.

The setup script stores only non-secret configuration as Windows user environment variables. It creates an isolated `.venv` and a workspace outside the source checkout. It does not install Blender, open firewall ports, enable remote desktop, create a service, or start at Windows login.

## Failure scenarios and expected behavior

| Scenario | Required behavior |
|---|---|
| PC is offline, sleeping, or GitHub is unavailable | Back off and retry; never mark a task successful without a result. |
| GitHub rate limit / HTTP 429 | Back off; do not loop aggressively. |
| Mailbox repository is public | Refuse access. |
| Token missing, expired, or lacks write permission | Stop or report a bounded configuration/access error; never print the token. |
| Manifest is missing, too large, malformed, or has unknown fields | Reject safely; never interpret task text as code. |
| Task is expired before approval or while waiting | Reject without execution. |
| Desired task changes or is removed while approval is open | Supersede the stale task and do not run its old payload. |
| A task ID is reused with different content | Reject the changed manifest; create a new unique ID for a new task. |
| Same manifest remains in the mailbox after restart | Do not execute it a second time. Local state tracks a bounded history of recent task IDs. |
| Agent is closed or Windows restarts | Restart manually; unfinished task status must be checked against actual files and result manifests before resuming. Automatic Windows service/startup is not enabled yet. |
| User changes a request quickly | Use a new task ID for a new desired task. The agent polls every 5–30 seconds (default 10); changes are not instantaneous. |
| Blender is missing or configured path is wrong | Block the Blender operation; diagnostics should identify the missing prerequisite. |
| GPU driver is absent or GPU memory is insufficient | Prefer a low-cost Eevee preview or report a bounded failure; never claim rendering completed if output validation fails. |
| Project folder, output, or registry path is a symlink/junction or escapes workspace | Reject the operation. |
| Asset is missing, duplicated, unsupported, or ambiguous | Mark it unresolved; do not pick a random file or silently replace it. |
| Existing output would be overwritten | Refuse by default; use a versioned output or require a clearly scoped local approval. |
| Render hangs or Blender crashes | Apply a timeout, preserve logs/checkpoints, and report the last completed stage. Automatic timeout/recovery for every Blender skill remains to be implemented. |
| Disk is low or output file is empty | Stop before final export; keep source assets and report the failed postcondition. Disk-space preflight is a remaining implementation item. |
| Private references or generated videos are involved | Keep them in the local workspace; never commit them to the public source repository or upload them to the mailbox by default. |
| A patch is requested remotely | Show it locally, require approval, run `git apply --check`, and test after application. A rollback/checkpoint workflow is still required before treating this as production-safe. |
| Local test suite fails | Do not start the mailbox poller or promote the branch. Preserve the failure output for diagnosis. |

## Connection architecture

- Outbound HTTPS from the PC to the GitHub API only; no inbound listener or port forwarding.
- The private mailbox stores a single desired-task manifest and bounded result JSON.
- A task is typed data, not a shell command, Python source, arbitrary URL, or executable path.
- The PC is the execution boundary: every operation requires a local `YES` approval.
- Windows Credential Manager stores the token; source code and task payloads must never contain secrets.
- The source checkout, private mailbox, and local project workspace are three separate things.

## Still required before relying on the agent

- Real Windows first-run and repeated Blender smoke tests.
- Robust status recovery for a process killed during an operation.
- Disk-space checks and timeouts for every long-running operation.
- Transactional patch backup/rollback and post-patch tests.
- A first-run preflight that confirms mailbox privacy, token read/write access, valid workspace and Blender version without printing secrets.
- A clear pause/resume/cancel protocol, task progress reporting, and per-operation time limits.
- Blender output validation for actual scene contents, image dimensions, non-empty renders, and final MP4 metadata.
- A user-visible summary that separates completed, blocked, failed, and unverified work.
