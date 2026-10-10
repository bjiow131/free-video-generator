# GitHub polling cadence and task supersession

## Poll interval

Default target: **10 seconds**, configurable between 5 and 30 seconds. At 10 seconds, one idle agent makes about 360 manifest reads per hour, before result writes and retries. Five seconds means about 720 reads/hour and should be used only if latency matters and API rate-limit headroom has been verified. Requests use finite timeouts; failures must use exponential backoff rather than hammering the API.

Expected idle-to-detection delay is roughly 0–10 seconds with the default interval, plus network/API latency. This is a design estimate, not a measured performance result; it must be tested on Windows.

## Rapid edits and supersession

Use one `queue/desired_task.json` manifest for the latest desired state, not a growing list of every text edit. A newer task ID replaces an older task that has not started. The agent compares task IDs and records processed IDs locally.

For the example “add a button” followed 20 seconds later by “rename that button”:
- If the first task is still pending, the second replaces it; the agent should implement only the latest request.
- If the first task has started, the agent must check for a newer manifest at safe checkpoints and stop/supersede the stale task before applying further changes.
- If a change has already been applied, the new task is a follow-up edit, not a time machine. It should update the same working branch and avoid conflicting implementations.
- Never run two code-changing tasks concurrently in the same working tree.

## Current implementation boundary

The initial GitHub transport and interactive poll loop are implemented in source. The poller checks the single manifest every 10 seconds by default (configurable 5–30 seconds), validates the task, asks for local approval, runs fixed diagnostic handlers, and publishes a bounded sanitized result. A bounded apply_patch operation is also implemented: it validates relative repository paths, runs git apply --check, then git apply only after the user types YES. It does not run tests automatically after patching. These paths are not runtime-tested yet.

## Private mailbox required

The project repository `bjiow131/free-video-generator` is public. It must contain source code and public docs only. Create a separate private repository for `queue/desired_task.json` and `queue/results/`. **The current prototype reads `LOCAL_AGENT_GITHUB_TOKEN` from an environment variable; Windows Credential Manager support is not implemented yet. Do not configure or run the poller with a real token until OS-protected credential retrieval is added and reviewed.** Verify that the ChatGPT GitHub connector can read and write the private mailbox before claiming the full round trip works.