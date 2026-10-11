# Trusted remote repair delivery (Windows Blender AI Agent)

Date: 2026-10-11
Working branch: feature/octava-agent-bridge-20261011. Main untouched.

## Why the first remote repair was blocked

A real forest scene task arrived at the Windows agent and was reported as blocked:
"set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally". The Studio launcher
defined the workspace but run_github_mailbox_agent.bat did not. The code repair
is committed to this branch (both the batch launcher and the forest handler).

The INSTALLED agent from before this change did **not** have a code update
consumer. It intentionally rejected unattended apply_patch, while the repair
channel always required an interactive YES and ran patches in an isolated
worktree, not the active installation. It would be inaccurate to say the
GitHub commit has already been installed on the remote Windows computer.

## New version: standing one-time consent, then autonomous repair

local_agent/trusted_updates.py implements a new, separate, optional channel:
  - Private mailbox source: bjiow131/local-agent-mailbox, main,
    queue/desired_update.json.
  - Source code fixed to public bjiow131/free-video-generator, pinned full
    40-character commit SHA (not a floating branch).
  - Each release manifest specifies update_id, creation/expiry, source repo,
    full commit SHA and a strict list of allowlisted relative paths with SHA256.
    Expiry window at most one day, size and count bounded.
  - User enables via localhost Studio / Настройки /
    GitHub · автоматические исправления программы /
    "Разрешить проверенные обновления агента без YES".
    Locally stored enabled flag defaults to false. No remote mailbox task
    can enable auto-install or change the trusted source.
  - Downloads only fixed paths from the trusted GitHub REST API at that commit.
    All bytes are verified BEFORE writing any live file.
  - Backs up each existing file and writes durable recovery metadata before
    replacing it, validates updates with limited fixed tests; on failure,
    restores the previous set.
  - Records immutable update ID to prevent execution twice across restarts.
    A changed manifest under the same update_id is refused.
  - Results are delivered as queue/results/update-<update_id>.json using
    the existing durable GitHub result-outbox transport.
  - After a passed update the poller returns exit code 75, and the Windows
    batch supervisor automatically restarts the poller with new code.
  - The update check runs at most every 90 seconds when opted in;
    the ordinary task queue polling interval is unchanged.
  - The separate previous repair channel still requires code review/YES.
    Remote free-form shell, scripts, credential file changes and executable
    paths are NOT accepted through the trusted updater.

## Manifest example (NEVER supply instructions/shell in the manifest)

{
  "schema_version": 1,
  "update_id": "trusted-release-20261011-01",
  "created_at": "2026-10-11T18:40:00Z",
  "expires_at": "2026-10-11T19:40:00Z",
  "source_repo": "bjiow131/free-video-generator",
  "commit_sha": "REPLACE_WITH_VERIFIED_FORTY_CHAR_COMMIT",
  "files": [
    {
      "path": "run_github_mailbox_agent.bat",
      "sha256": "REPLACE_WITH_ACTUAL_64_CHAR_SHA256"
    }
  ]
}

For a real release, generate digests from the exact GitHub source commit,
publish the manifest to the private mailbox, and confirm the immutable result.
Never embed any GitHub/OctavAPI token in the update manifest, test output or logs.

## One-time bootstrap limitation

A previously installed program cannot execute a new remote-update protocol
that its installed Python code does not contain. **The first installation of
trusted_updates.py, the loopback consent endpoint, launcher restart loop and
regression tests requires a one-time upgrade to the Windows installation.**
The older agent cannot self-apply this release while it is running, and a
GitHub commit alone cannot magically install code on the computer.
After this initial installation and local opt-in, future trusted releases can
install without repeated YES prompts or ZIP extraction.

No changes were merged to main. Actual Windows execution, bootstrap install,
rendering a Blender forest preview, and the first real trusted release
round-trip need Windows acceptance tests. These have NOT been claimed successful.
