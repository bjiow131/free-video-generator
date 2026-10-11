# Blender AI Agent — GitHub mailbox without per-task YES

Date: 2026-10-11. Branch: `feature/octava-agent-bridge-20261011`.

## What changed

The user explicitly requested that normal remote work continue while they are away
from their computer. The Windows agent now supports a **standing local authorization**
stored in the private `.local_agent/mailbox_policy.json` of its installed checkout.
No API keys, personal scripts or provider credentials go into this file.

This standing authorization is created only through the locally hosted Blender Studio
`Настройки → GitHub · автономное выполнение`. It is **disabled by default**.
Select the main checkbox once and press `Сохранить разрешения`. The running poller
re-reads the local policy for every newly received task, so toggles are live.
After the one-time software upgrade, **restart the old running poller once** to
load the new code. Later tasks do not need `YES`.

## Permissions and limits

- Main checkbox: automatically run bounded **diagnostic** operations:
  `doctor`, `preflight`, `status`, `blender_preflight`,
  `blender_inspect_mia_project`, `blender_knowledge_search`,
  `scan_project_assets`, `compile_story_plan`.
- Separate Blender checkbox: allow `save_story_plan`, `blender_forest_preview`,
  `blender_mia_blockout`, `blender_mia_skeleton`. These can create/change
  local project data and consume CPU/GPU time; enable only if you trust the
  private mailbox collaborators.
- Separate tests checkbox: allow `test`. Executes *installed local test code*;
  potentially long-running, so optional.
- Separate OctavAPI checkbox: allow `octava_advice` with the key already stored
  in Windows Credential Manager, max **20 automatic API calls per UTC day**.
  The counter is durable and increments before each call; timeouts still count
  because the provider might charge. Manual Studio key rotation is unchanged.
- **Never unattended:** `apply_patch`, all repair manifests, arbitrary scripts,
  commands, `blender_open_mia_project`, `start`, `stop`, `backup`, `logs`
  and unknown operations. These are blocked and reported instead of displaying
  YES when unattended mode is active. This prevents execution of arbitrary
  remote-provided Python, shell and risky work without review.

Remote task JSON continues to require `requires_local_approval: true`.
That field cannot grant permissions; the standing authorization is **local**,
made through Studio. Previous safeguards remain: expiry, bounded arguments,
immutable IDs, duplicate/replay protection, manifest-SHA re-check prior to
execution, the private GitHub mailbox, and no inbound network listener.

## One-time installation to the existing Windows app

The user's installed location is `C:\AI-Agent-Studio-Octava`. The patch
installer preserves `C:\AI-Agent` and `C:\AI-Agent-Workspace` entirely.

1. Stop the running `run_github_mailbox_agent.bat` and Studio windows.
2. Run the provided updater archive: `01_INSTALL_UNATTENDED.bat`.
   It fetches a **pinned** GitHub commit, backs up exactly the changed files,
   restores them into the existing checkout, runs local regressions and prints
   backup/rollback info. It does **not** merge into `main`.
3. Start `run_blender_studio.bat` and open `Настройки`.
4. Under GitHub autonomous permissions, enable main checkbox; select
   optional Blender, tests and OctavAPI checkboxes according to task needs;
   click `Сохранить разрешения` **once**.
5. Restart `run_github_mailbox_agent.bat`; leave that process running.
6. ChatGPT can send a new harmless `blender_preflight` with a unique task ID.
   The poller should execute it without a console prompt, publish result JSON
   to the existing private `bjiow131/local-agent-mailbox`, and this chat
   should read it with its existing GitHub connector.

## Security and operational limitations

- This is a standing authorization to a **private repository's writers**:
  anyone with write access to the mailbox could queue the selected operations.
  Do not grant mailbox write access to untrusted accounts; protect both
  GitHub and Windows account.
- No manual approval is needed for allowed tasks, but the computer must be
  powered on, connected, the agent poller running and GitHub/OctavAPI
  reachable from its network route.
- GitHub is a mailbox, not a push notification into ChatGPT. ChatGPT checks
  returned results through the connector when continuing this conversation.
- Provider balances remain finite. `max_tokens=320` per advice, 20 automatic
  calls per UTC day; no promise of spending exactly zero.
- An old waiting `YES` prompt is not bypassed retroactively. **Close and
  restart** that older poller once after installing updated code.
- The new Python policy module's standalone offline tests passed in the
  assistant's environment; **full exact GitHub-branch tests and Windows
  acceptance still require local execution**.
