# Windows first run and failure-readiness matrix

This is an implementation checklist, not a claim that a real Windows smoke test has passed. The setup script is intended to run only after the source repository is present on the PC.

## Safe first setup

1. Install Git and Python 3.11+ from their official sources. Obtain this branch with `git clone --branch feature/local-first-migration https://github.com/bjiow131/free-video-generator.git`, then run commands from the cloned repository folder. If you use a ZIP instead, Git-based patch application will remain unavailable until you make a proper clone. Install Blender separately; the setup script does not download or silently install these tools.
2. Use a **dedicated PRIVATE GitHub mailbox repository**. Do not use a public source-code repository as the mailbox: the transport deliberately refuses public repositories.
3. Give a fine-grained GitHub token access to that private mailbox repository only, with Contents read/write. Store it in Windows Credential Manager using `python -m local_agent.credentials_cli set`; never put it in task JSON, source code, chat, or a committed .env file.
4. Run `powershell -ExecutionPolicy Bypass -File .\scripts\windows\setup_local_agent.ps1` from the checked-out source repository.
5. Review the diagnostic output and focused tests. Do not start polling if tests fail, the mailbox is public, the token is unconfigured, or the manifest format is invalid.
6. Configure `queue/desired_task.json` in the private mailbox with a valid, short-lived task ID that has never been used before. Use the exact sample and timestamp rules in [the private mailbox task template](private-mailbox-task-template.md). First task should be the non-destructive `preflight` check and should require local approval. The setup script asks separately whether to enable phone-driven remote approval for a strict allowlist of typed operations; default is No.

The setup script stores only non-secret configuration as Windows user environment variables. It creates an isolated `.venv` and a workspace outside the source checkout. It does not install Blender, open firewall ports, enable remote desktop, or register background startup automatically. After tests pass and the first private-mailbox preflight succeeds, register the user-level background task with `powershell -ExecutionPolicy Bypass -File .\\scripts\\windows\\register_local_agent_task.ps1`. It starts at Windows sign-in, writes bounded rotating logs under `.local_agent\\logs\\poller.log`, and can be removed with `unregister_local_agent_task.ps1`. The task uses the current interactive user and does not enable automatic Windows sign-in; after a full reboot, a user must sign in once.

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
| Agent is closed or Windows restarts | A task claim is saved before execution. If it remains in progress after restart, the agent reports an uncertain outcome and refuses blind replay; inspect files/results and submit a new task ID only after deciding whether retry is safe. The optional scheduled task starts at user sign-in, not before sign-in. |
| User changes a request quickly | Use a new task ID for a new desired task. The agent polls every 5–30 seconds (default 10); changes are not instantaneous. |\n| A task requires local approval but the poller is running hidden | Publish a `blocked` result instead of hanging on an invisible console prompt. Use an allowlisted remote-approved task only after the owner opted in locally. |
| Blender is missing or configured path is wrong | Block the Blender operation; diagnostics should identify the missing prerequisite. |
| GPU driver is absent or GPU memory is insufficient | Prefer a low-cost Eevee preview or report a bounded failure; never claim rendering completed if output validation fails. |
| Project folder, output, or registry path is a symlink/junction or escapes workspace | Reject the operation. |
| Asset is missing, duplicated, unsupported, or ambiguous | Mark it unresolved; do not pick a random file or silently replace it. |
| Existing output would be overwritten | Refuse by default; use a versioned output or require a clearly scoped local approval. |
| Render hangs or Blender crashes | Apply a timeout, preserve logs/checkpoints, and report the last completed stage. Automatic timeout/recovery for every Blender skill remains to be implemented. |
| Disk is low or output file is empty | Stop before final export; keep source assets and report the failed postcondition. Disk-space preflight is a remaining implementation item. |
| Private references or generated videos are involved | Keep them in the local workspace; never commit them to the public source repository or upload them to the mailbox by default. |
| A patch is requested remotely | Require local approval, create an isolated `agent/task-<id>` worktree from the recorded base commit, run `git apply --check`, apply the patch only in that worktree, and run pytest there. On failure, remove the temporary worktree and branch; if cleanup cannot be verified, report `FAILED_NEEDS_USER`. A successful branch is retained for review and is not auto-merged. |
| Local test suite fails | Do not start the mailbox poller or promote the branch. Preserve the failure output for diagnosis. |

## Connection architecture

- Outbound HTTPS from the PC to the GitHub API only; no inbound listener or port forwarding.
- The private mailbox stores a single desired-task manifest and bounded result JSON.
- A task is typed data, not a shell command, Python source, arbitrary URL, or executable path.
- The PC is the execution boundary. Local approval is the default. If the owner explicitly enables `LOCAL_AGENT_ALLOW_REMOTE_APPROVAL=1`, only typed low-risk operations in the protocol allowlist may omit local approval. Patch application and generic test execution remain local-approval-only. Remote tasks are revalidated against the latest manifest before execution. The background runner blocks local-approval tasks if no interactive console exists.
- Windows Credential Manager stores the token; source code and task payloads must never contain secrets.
- The source checkout, private mailbox, and local project workspace are three separate things. The source repository is public, so it must never be used as the control mailbox.

## Current protections and remaining work

- The poller now writes a redacted local JSON report before attempting to publish the result. Failed/blocked outcomes trigger a best-effort native Windows notification; the notification contains no credential and does not replace the report. Notification and report-publication behavior has automated test coverage authored, but the GitHub Actions run is currently queued, not passing/verified.
- Reviewed patch tasks now use an isolated worktree and run pytest there. Failed tests trigger cleanup of the task worktree and branch; cleanup failure is surfaced as `failed_needs_user`. Successful work remains on its named task branch for review and is not automatically merged into the active checkout.

- The local-only `preflight` command checks Python, workspace writability/free space, local mailbox configuration, Blender availability/version and optional tools without starting a render or making a network request. It does **not** prove that GitHub confirms the mailbox is private or that the token can read/write it; the first real mailbox connection must verify those conditions.
- An OS-level singleton lock prevents two poller instances on the same PC from processing tasks concurrently.

## Still required before relying on the agent

- Real Windows first-run and repeated Blender smoke tests.
- Robust status recovery for a process killed during an operation.
- Disk-space checks and timeouts for every long-running operation.
- Confirm transactional patch rollback tests pass in CI; perform Windows runtime verification of notifications, report paths, and worktree cleanup.
- A first-run preflight that confirms mailbox privacy, token read/write access, valid workspace and Blender version without printing secrets.
- A clear pause/resume/cancel protocol, task progress reporting, and per-operation time limits.
- Blender output validation for actual scene contents, image dimensions, non-empty renders, and final MP4 metadata.
- A user-visible summary that separates completed, blocked, failed, and unverified work.
