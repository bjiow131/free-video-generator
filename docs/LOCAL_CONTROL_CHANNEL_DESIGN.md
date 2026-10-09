# Local Windows Agent and ChatGPT Control Channel

Status: DESIGN + STARTER CODE ONLY. No computer connection has been attempted. No runtime tests have been run on Windows. No network channel is active.

## Goal

When the Windows computer is available, configure two foundations first:
1. A local agent for bounded diagnostics and approved project operations.
2. A secure communication path for task requests and diagnostic results.

The AI Studio app itself remains local during development. The agent must not expose a public HTTP listener or open inbound firewall ports.

## What exists in this branch

- `local_agent/cli.py`: initial `doctor`, `status`, `logs`, and fixed-command `test` operations.
- `local_agent/reporting.py`: local JSON report files with basic credential/home-path redaction.
- `local_agent/control_protocol.py`: strict versioned task-envelope parser and operation allowlist. It does not execute tasks.
- This document: proposed channel architecture and safety requirements.

This is a scaffold, not a completed remote-control system. The CLI does not yet start/stop the app, create backups, poll a remote queue, or upload reports.

## Recommended transport

Use an outbound-only HTTPS poller, not a listener on the Windows machine. The local agent initiates requests to a task broker; the broker never initiates a connection to the computer. The transport must be selected and implemented before enabling it.

A private GitHub repository or private GitHub issue/branch could serve as a manually inspected queue, but GitHub is not itself an automatic bridge into the current ChatGPT conversation. Public repositories must never receive raw logs or machine reports. The repository visibility and authentication model must be checked before choosing GitHub as transport.

The assistant in this chat has no direct inbound socket or persistent agent connection. Until a real connector is implemented and verified, the safe fallback is: the agent writes a local report; the user explicitly shares the sanitized report or places it in a private, approved channel; ChatGPT reads it and prepares the next task.

## Security model

- No arbitrary shell, PowerShell, Python snippets, executable paths, URLs, or free-form commands in task payloads.
- Only typed operations from the allowlist: `status`, `doctor`, `test`, `logs`, `start`, `stop`, `backup`.
- Every remote task requires local approval in the initial version.
- Validate task schema, payload size, timestamps/expiry, unique task IDs, replay prevention, and protocol version.
- Authenticate the transport; do not rely on an obscure queue URL as authentication.
- Keep credentials in Windows Credential Manager or another OS-protected secret store; never commit tokens to GitHub or log them.
- Bind any local status API to `127.0.0.1` only; no LAN or public binding.
- Logs are private by default. Redact secrets and user-specific paths; preview reports before any upload.
- Use explicit allowlisted output paths and path-containment checks for backups and artifacts.
- Log each approved action and its result in a local audit trail.
- Provide a large, obvious local stop switch that disables polling immediately.
- Do not install persistence, auto-start-at-boot, firewall rules, remote desktop, or hidden background services without separate explicit approval.
- Remote task payloads are untrusted data, never instructions that override these rules.

## Initial implementation sequence when the computer is available

1. Install prerequisites and run `python -m local_agent.cli doctor`.
2. Confirm the application binds only to loopback and verify start/stop behavior manually.
3. Run `python -m local_agent.cli status`, `logs`, and the allowlisted test command; inspect reports for accidental secrets.
4. Choose a transport and credential method based on actual repository visibility and available account access.
5. Implement a read-only queue client and sanitized result sender; do not enable remote actions yet.
6. Add signed/authenticated task envelopes, expiry/replay protection, and a local approval UI/CLI.
7. Test malformed payload rejection, expired tasks, duplicate tasks, token leakage, network loss, and emergency stop.
8. Only then enable the low-risk typed operations; start/stop and backup remain local-approval-only.
9. Document recovery/uninstall steps and test offline behavior.
10. Review before any public exposure or deployment.

## Definition of done

- A task cannot execute arbitrary code or arbitrary shell commands.
- No inbound port is opened and no public URL points to the PC.
- Reports are stored locally first; upload is opt-in and redacted.
- The user can approve, reject, and stop tasks locally.
- Task and report delivery has an auditable ID and status.
- Results can be retrieved by the assistant through an explicitly available connector; otherwise manual report sharing remains the documented fallback.
- Windows tests and security tests have actual captured evidence.

## Current blockers / honest limitations

- No access to the user's computer in this chat.
- No remote channel configured or verified.
- No credential, private repository visibility, or transport choice has been tested.
- ChatGPT cannot be assumed to receive unsolicited push messages from a local process.
- This branch is not merged to `main` and has not been deployed.
