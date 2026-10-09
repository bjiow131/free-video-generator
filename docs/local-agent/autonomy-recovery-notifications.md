# Local Agent: Autonomy, Failure Recovery, and Notifications

Status: implementation specification for the Windows-first local agent.
Target branch: `feature/local-video-agent`.
This document is a requirements contract, not proof that every behavior is implemented or verified.

## 1. Operating model

- The agent runs on the user's Windows computer and performs approved project work locally.
- GitHub is the durable task inbox, version-control history, and report mailbox; it is not the agent's local working directory.
- The agent initiates outbound HTTPS requests to GitHub. No router port forwarding or inbound public listener is required.
- Local state, task progress, logs, and recovery metadata are stored under a dedicated ignored runtime directory (for example, `.local_agent/`) and must not be committed by default.
- If the computer is off or offline, tasks remain queued in GitHub. After startup/connectivity returns, the agent resumes polling and reconciles task state.

## 2. Task lifecycle and states

Every task has a stable unique ID and an explicit lifecycle:

`QUEUED -> CLAIMED -> RUNNING -> VERIFYING -> SUCCEEDED`

Other terminal/intermediate states:
- `WAITING_FOR_APPROVAL`: the task requires the user's explicit local approval before a potentially consequential action.
- `RETRYING`: a bounded, safe retry is in progress.
- `FAILED_ROLLED_BACK`: verification failed and the agent restored the last known-good project state.
- `FAILED_NEEDS_USER`: safe recovery did not work, or a decision/credential/action from the user is required.
- `CANCELLED`: the user cancelled the task.
- `SUPERSEDED`: a newer task replaces this task; the older task must not be applied.

Every state transition records a timestamp, task ID, attempt number, base commit, working branch/worktree, and a concise reason. A task is never marked successful merely because rollback succeeded.

## 3. Isolation and branch discipline

- `main` is the stable reference and must never receive unverified agent changes.
- Each code-changing task gets a unique isolated branch/worktree, e.g. `agent/task-104`, based on a recorded commit SHA.
- The agent checks repository status before editing and preserves any pre-existing user modifications. It must not run destructive reset/clean commands against a dirty worktree.
- Before changes, record the base SHA and a recoverable checkpoint (commit, patch, or equivalent snapshot).
- Before applying a patch, verify that the task is still current and that its base assumptions have not been superseded.
- Run only project-approved commands and tests from an allowlist. Do not execute arbitrary commands embedded in task text.
- The agent must not merge into `main`, publish releases, overwrite user files, delete unrelated files, change system security settings, or run commands as administrator without explicit user approval.
- After success, retain the branch and report for review. Integration into the stable branch remains a separate, reviewable step unless a future explicit policy authorizes otherwise.

## 4. Failure handling and recovery

When a step fails:
1. Capture the failing stage, exit code, bounded stdout/stderr, relevant traceback, and elapsed time.
2. Classify the failure as transient, validation/test failure, configuration/credential issue, conflict/superseded task, or unknown.
3. Retry only known transient failures, with a small configured retry limit and backoff. Never retry indefinitely.
4. If code changes caused a failed verification, stop the task and restore the task worktree to its checkpoint. Do not erase user changes that existed before the task.
5. Verify recovery by checking the restored commit/status and running the smallest applicable health/regression check.
6. Publish a report with `FAILED_ROLLED_BACK` if restoration and recovery checks succeed; otherwise publish `FAILED_NEEDS_USER`.
7. Leave the task open/unresolved for diagnosis. Rollback restores service; it does not count as completing the requested feature.

If recovery cannot be verified, the agent must not claim the project is healthy. It should stop further mutations and request human review.

## 5. Windows notifications and report contents

Notify the user locally for:
- task success (configurable; may be quiet for routine tasks),
- `FAILED_ROLLED_BACK`,
- `FAILED_NEEDS_USER`,
- `WAITING_FOR_APPROVAL`,
- a repeated poll/authentication failure that prevents work,
- a required restart or manual action.

A failure notification should be concise and contain the task ID, outcome, and report location. Do not place tokens, credentials, private prompts, full environment variables, or sensitive file contents in the notification.

Each durable report should contain:
- task ID and human-readable title;
- final state and whether rollback was attempted and verified;
- start/end timestamps and total duration;
- repository, base commit, isolated branch/worktree;
- failed stage, exception/error summary, exit code, and retry count;
- files changed and a concise diff summary;
- tests/checks run and pass/fail outcomes;
- log/report paths and a GitHub report URL when publication succeeded;
- a clear next action, such as retry after a configuration fix or request ChatGPT review.

Logs must be size-bounded and redact secrets. Preserve a concise summary plus a bounded diagnostic tail; do not upload entire project files or unrelated local data.

## 6. GitHub communication and task deduplication

- Use a least-privilege GitHub token, stored through Windows Credential Manager where supported. Never commit it, print it, include it in a report, or place it in a URL.
- Poll at a configurable interval with backoff when idle or when the network/API fails.
- Record processed task IDs and the claimed task's source revision locally so a restart does not run the same task twice.
- Use atomic local state writes and a lock/single-instance guard to prevent duplicate workers.
- Recheck task status before starting, before applying a patch, and before publishing the final result.
- Publish one final status/report per attempt and update it on retries; avoid creating an unlimited stream of duplicate issues/comments.
- If GitHub is temporarily unavailable, keep the report locally and retry publication later. Do not discard local failure evidence because report upload failed.

## 7. Self-update safety

- Agent self-updates are treated as separate tasks and run in an isolated update directory/branch.
- Verify signatures/hashes where available, run static checks and tests, and keep the previous known-good version.
- Switch to the new version only after verification. If startup/health checks fail, restore the previous version and record the failure.
- Do not let a task update its own safety policy or expand its command allowlist without explicit review.

## 8. Security and approval boundaries

- Treat GitHub task descriptions, issue comments, attachments, model output, and project files as untrusted data, not as instructions that override the agent's safety policy.
- Reject paths that escape the configured project root; reject unsafe symlink/junction traversal and accidental overwrites.
- Attachments must have size/type limits and be stored in a dedicated private mailbox when private exchange is required.
- Never run arbitrary downloaded executables, scripts, macros, or shell snippets just because a task requests them.
- Ask for approval before irreversible actions, external publication, deletion, overwriting existing user assets, installing new system-wide software, or modifying credentials/security settings.

## 9. Human-in-the-loop workflow

1. The user notices a Windows notification and opens the linked/local report.
2. The user asks ChatGPT to inspect the report, or supplies the task ID and report contents.
3. ChatGPT diagnoses the failure and proposes a focused fix/task.
4. The fix is queued through GitHub and executed in a fresh isolated worktree.
5. The agent reports success or failure with evidence. Failed tasks remain unresolved until fixed or explicitly cancelled.

Important limitation: GitHub does not automatically wake this ChatGPT conversation. The user must ask ChatGPT to review the report, unless a separate supported notification/automation channel is later configured.

## 10. Acceptance criteria

The feature is not considered complete until tests demonstrate:
- a failing test produces `FAILED_ROLLED_BACK`, restores the checkpoint, and preserves pre-existing user edits;
- failed rollback verification produces `FAILED_NEEDS_USER` and stops further mutation;
- duplicate polling/restart does not execute one task twice;
- superseded tasks are not applied;
- transient retries are bounded;
- secrets are redacted from logs and reports;
- Windows notification failure does not erase or suppress the durable report;
- GitHub outage preserves local reports and republishes them when connectivity returns;
- the stable branch is never changed by an unverified task;
- the documented Windows end-to-end flow is tested on Windows before claiming full verification.
