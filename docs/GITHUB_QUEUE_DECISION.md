# GitHub Queue: Security Decision and First-Run Plan

Status: DESIGN DECISION ONLY. No live queue is configured; no Windows runtime tests have run.

## Verified repository fact

On 2026-10-09, the connected GitHub repository lookup reported `bjiow131/free-video-generator` as **public**. Therefore it MUST NOT be used to store raw local logs, machine diagnostics, credentials, private task payloads, or personal paths.

The existing public repository may hold agent source code and public documentation only.

## Recommended split

Use a separate **private** repository as the control mailbox, after creating it and verifying that the connected GitHub integration can access it.

Suggested layout in that private repository:

- `queue/pending/<task-id>.json` — new bounded task envelope.
- `queue/claimed/<task-id>.json` — task accepted by one agent instance.
- `queue/results/<task-id>.json` — sanitized result and completion status.
- `queue/rejected/<task-id>.json` — rejected task plus a safe reason code.

Do not store access tokens or other secrets in these files. Do not include raw logs by default.

## End-to-end workflow

1. The user asks ChatGPT to perform a task.
2. ChatGPT writes a task envelope to the private mailbox using an available, authorized GitHub write integration. This write capability must be tested against the chosen private repository before claiming the flow works.
3. A Windows agent makes outbound HTTPS requests to the GitHub API on a configurable interval.
4. The agent validates the envelope (schema, allowlisted operation, size, expiry, unique task ID) and records the task ID locally to prevent replay.
5. The agent requires local approval for operations that change files, start/stop services, or perform backups. No remote shell or arbitrary script execution is allowed.
6. The agent executes only a locally implemented handler for the approved operation.
7. The agent redacts sensitive values and writes a result JSON to the private mailbox. Raw logs stay local unless the user explicitly chooses to share them.
8. The user tells ChatGPT to inspect the report. ChatGPT reads the result through the connected GitHub integration and recommends the next task.

## Authentication and access

- Prefer a narrowly scoped fine-grained token or GitHub App credential with access only to the private mailbox repository and required contents operations.
- Store the credential in Windows Credential Manager or another protected OS store; never in source code, a committed `.env`, task JSON, or logs.
- Verify private repository visibility and the actual permissions of the ChatGPT GitHub integration before relying on it.
- Never enable inbound ports, a public webhook receiver, or public report hosting for this design.
- Add polling backoff, request timeouts, bounded payloads, rate-limit handling, and clear offline status.
- Avoid concurrent agents claiming the same task; use conditional updates / unique claims and a local processed-task ledger.

## What is not yet proven

- A private mailbox repository has not yet been created or connected.
- ChatGPT's connected GitHub integration has not been tested for writing tasks to that private repository.
- The Windows poller and result uploader are not implemented or tested.
- End-to-end transfer, duplicate prevention, approval UI, token storage, and report redaction still require implementation and real tests on Windows.

## First computer session acceptance test

1. Create a dedicated private mailbox repository.
2. Verify ChatGPT's connected GitHub integration can read and write a harmless test file there.
3. Configure the Windows credential securely without committing it.
4. Run the agent once in manual/poll-only mode.
5. Send a harmless `doctor` task with local approval enabled.
6. Verify the agent claims it once, executes the fixed local handler, and writes a sanitized result.
7. Ask ChatGPT to inspect that result and verify it can read the report.
8. Only then consider enabling periodic polling. Keep the app local; do not merge to `main` or deploy Render without explicit approval.
