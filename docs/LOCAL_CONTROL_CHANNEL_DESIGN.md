# Local Windows Agent and ChatGPT Control Channel

Status: **transport and task poller implemented in the feature branch; end-to-end connection not yet configured or verified**. No Windows computer has been accessed from this chat. Do not describe the agent as installed or connected until the real round-trip test passes.

## Goal

Allow the user to submit typed, bounded tasks from ChatGPT on the iPhone to a local Windows agent, then retrieve its sanitized results. The local AI Studio app and Blender work remain on the Windows computer. The agent must not expose an inbound listener or open firewall ports.

## Implemented in this branch

- `local_agent/control_protocol.py`: versioned JSON task envelope, strict allowlist and argument validation, timestamps/expiry and bounded payloads.
- `local_agent/github_queue.py`: GitHub REST mailbox client; confirms the repository is private before reading tasks or publishing results; uses HTTPS, size limits, redaction, and Windows Credential Manager-backed credentials.
- `local_agent/credentials_cli.py` and `local_agent/windows_credentials.py`: store/read/delete a token through Windows Credential Manager, without writing it to a plain-text token file.
- `local_agent/poller.py`: outbound polling (default 10 seconds, bounded 5–30 seconds), single-instance lock, persistent task-ID/replay handling, local approval flow, local report first, then result publication. Network failures use bounded backoff.
- `local_agent/cli.py`: diagnostics and preflight checks, including mailbox configuration and Blender availability.
- `local_agent/blender_workflow.py`, `local_agent/blender_rigging.py` and related handlers: allowlisted local Blender operations, including Mia blockout and a prototype skeleton.
- `tests/test_github_queue.py`, `tests/test_control_protocol.py`, `tests/test_poller.py` and other safety tests: mocked/automated tests are present in the branch; they are not a substitute for a real Windows test.
- `docs/LOCAL_AGENT_CHANNEL_SETUP.md`: private mailbox setup and round-trip verification instructions.

## Transport architecture

1. ChatGPT writes a typed JSON manifest at `queue/desired_task.json` in a dedicated **private** GitHub mailbox repository.
2. The Windows poller initiates outbound HTTPS requests to GitHub; no inbound port is needed.
3. The agent validates the manifest and checks task expiry, operation allowlist, task ID and replay state.
4. By default, the local console must approve each task. Only explicitly allowlisted low-risk typed operations can be configured for remote approval; code changes and generic tests remain local-approval-only.
5. A redacted report is saved locally before the agent attempts to publish the result to `queue/results/<task_id>.json`.
6. ChatGPT can retrieve the result only if that private repository is accessible to the connected GitHub integration. GitHub polling is not a push connection and cannot spontaneously send a message into this conversation.

## Security requirements and known limits

- Never use the public `bjiow131/free-video-generator` repository as the mailbox. The client fails closed unless GitHub confirms the mailbox repository is private.
- Use a dedicated fine-grained token limited to the mailbox repository, with Contents read/write permission. Store it in Windows Credential Manager; never commit or paste it into chat.
- Task payloads are untrusted data, never shell commands or Python source. Unknown operations and unexpected arguments are rejected.
- Do not enable `LOCAL_AGENT_ALLOW_REMOTE_APPROVAL=1` during initial setup. Start in the foreground with local approval.
- Logs, machine details and generated assets remain local by default. Only bounded, redacted task result JSON is sent to the mailbox.
- Task IDs are immutable. If the same ID appears with changed content, the task is rejected; uncertain interrupted operations are not blindly replayed.
- Replay-state corruption or unreadable state now stops the poller instead of silently resetting task history; automated tests cover missing, malformed, and invalid state files.
- No auto-start, hidden service, firewall change or remote desktop is installed.
- Task authentication currently relies on GitHub HTTPS plus the restricted token and private-repository access; the protocol does not add a separate cryptographic signature to each manifest.
- No actual Windows, Blender render, notification, or live mailbox round-trip has yet been verified.

## Remaining setup and verification

1. Create a new private mailbox repository and make it available to the GitHub integration in ChatGPT. Do not repurpose an unrelated private repository.
2. Create `queue/desired_task.json` with a fresh, short-lived `doctor` task using the documented schema.
3. On the Windows computer, install Python 3.11+, Git and Blender; install `requirements-local-agent.txt`; configure mailbox/workspace/Blender paths; save the fine-grained token through `python -m local_agent.credentials_cli set`.
4. Run `python -m local_agent.cli preflight`, then start `python -m local_agent.poller` in a foreground terminal.
5. Approve the harmless diagnostic task locally. Confirm that `queue/results/<task_id>.json` appears in the private mailbox and can be read through ChatGPT's GitHub integration.
6. Test expired/invalid manifests, duplicate task IDs, token redaction, network failure, emergency stop, and Blender preflight before considering background operation.

## Definition of done

The channel is connected only after the actual Windows poller asks for approval of the test task, completes the fixed diagnostic, saves a local report, publishes a result JSON file, and that result is readable from ChatGPT through the connected GitHub integration. Until then, the accurate status is: **code prepared; private mailbox and Windows endpoint still need setup and live verification**.
