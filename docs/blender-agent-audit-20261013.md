# Blender Agent audit — 2026-10-13

## Source and limits

Repository: bjiow131/free-video-generator. Audited base:
`feature/season1-episode-import-20261013` at
`ece4260c021254489ef160e97219deadef28b1bc`.
Main was observed at `e359969ef654854857a99e090025d9fe9c2a35d1` and was not modified.
Both the multiscene-runner and Mia-25D-prototype branch heads are ancestors of this base.
The separate Windows PE fixture branch contains useful test fixes, but also lacks
newer episode-import changes; only its fixture changes were adopted, with missing
Path imports corrected. No wholesale merge was performed.

Execution environment: Linux, Python 3.12.14, FFmpeg 6.1.1. Blender was not found.
Results below are offline contracts and real FFmpeg assembly checks, not proof of
Windows/Blender 5.2 acceptance, character likeness, or production animation.
No local mailbox task, paid model request, or Telegram notification was sent.

## Findings and safe fixes

| Priority | Finding | Change / verification |
|---|---|---|
| High | `create_mia_blockout` references `result` in finally before assignment if generation raises, masking the original error during rollback. | Initialize the result before generation. New regression raises after writing partial output and verifies restoration of the original blend and preservation of the original exception. |
| High | Operational `test_scope all` excludes existing Studio, cancellation, assembly, asset-sync, camera, trusted-update and Mia tests. CI PR branch filters exclude the current working branch. | Explicit agent-only allowlist expanded; no repository-wide discovery. PR checks now apply to relevant changes on any target branch, and audit branches trigger push checks. |
| Medium | Interpreter can accept more than 20 actions or more action windows than frame intervals. Blender-side executor subsequently rejects the first case or silently overwrites same-frame keys in the second. | Reject both cases before job creation; repeat frame-budget check in the Blender executor. Regression tests cover excessive actions and insufficient frames. |
| Medium | Windows tests use non-PE placeholder executables despite production PE validation. | Minimal AMD64 PE-header fixtures; these are validation fixtures, not runnable Blender binaries. Windows execution remains pending. |
| Medium | Failed-overwrite test mocks subprocess.run, but implementation now calls the cancellable process wrapper. | Mock the current seam without changing production execution; retain preservation assertions. |
| Medium | Private reference test configures local-agent-mailbox but asserts a season1-private-bible request URL. | Assert the exact configured repository, path, pinned commit and authorization header. |
| Medium | 100-cycle mock lacks the new single_pass keyword; the caught TypeError produces incomplete status. | Update mock signature and assert single_pass is false. No real 100-cycle job was run. |
| Low | Compatibility helper adds a duplicate world initialization guard even to an already repaired Blender script. | Use already fixed source directly; regression ensures no temporary patched script is created. |
| Low | studio_server uses Any without importing it; FFmpeg filter string contains invalid Python escape. | Import Any and use a raw f-string, preserving the FFmpeg expression. Static checks pass. |

## Confirmed unfinished implementation (not replaced by a demo)

1. `scene_compiler.compile_story_plan` returns `planning_only`, and action steps
   remain `not_executable_yet`. Resolving asset paths does not connect them to an
   action executor or validate rigs.
2. `prompt_interpreter` always reports missing requirements for real project
   characters. `StudioJobs.start` accepts only `ready_fixture` and
   `studio_blender_scene` only `procedural_test_fixture`. A Mia reference or even
   an assets/mia.blend file does not enable real-character Studio animation.
3. `createSeasonEpisode` in studio_static/app.js only displays a blocked or
   not-connected notification. There is no episode-create POST operation joining
   imported episode text, reference selection, Astra planning and Blender execution.
4. `multiscene_cli` renders a fixed three-segment translation/camera test, clears
   object animation, and is not a general interpreter of storyboard action_steps.
5. `LocalProjectRunner` uses an injected generate_i2v backend protocol. Its
   checkpoint/continuity tests do not establish a Blender action backend.
6. Episode-1 blockout/release and Mia 2.5D/model-review paths exist separately;
   their presence does not prove the generic text-to-season production chain.
   Blockouts explicitly use rigid placeholder rigs. 2.5D retains camera and mouth
   limitations documented in its returned metadata.

These require a separately scoped implementation and real asset/rig acceptance;
this audit deliberately does not introduce a new production architecture.

## Remaining risks / follow-up checks

- BlenderBridge's headless production path deliberately returns on a completed
  manifest without waiting for worker exit. A test explicitly enforces this.
  Process exit/cleanup and nonzero exit after manifest are not proven; review the
  existing lifecycle contract before changing it.
- Studio frame completion checks count matching PNG files and check MP4 existence/
  size; they do not validate every PNG or independently probe every rendered MP4.
  The opt-in live acceptance test probes one fixture MP4, not all production jobs.
- 100-cycle V2 stores folders before completion and refuses an existing cycle
  folder on retry. Interrupted-cycle recovery still needs a dedicated acceptance
  case; no automatic deletion of prior work was introduced.
- Real Windows compatibility-dialog closing, process-tree termination, Credential
  Manager, Blender 5.x rig/shape-key behavior and the installed updater's allowed
  file list were not validated on the user's computer.
- Offline green tests do not prove exact Mia identity or acceptable motion.

## Validation actually run

Before corrections:
- Existing operational scope: 525 passed, 1 failed, 1 skipped.
- Initial supplemental agent checks: 217 passed, 1 failed, 2 skipped, 5 subtests passed.
- Adding previously excluded Mia checks exposed the outdated single_pass mock.

Final:
- `python -m local_agent.test_scope all`: **778 passed, 3 skipped, 5 subtests passed**.
- Skips: Windows junction acceptance, trusted-update symlink test (reported privilege limitation),
  opt-in real Blender acceptance.
- `node --test tests/test_studio_frontend_navigation.mjs`: **5 passed**.
- `node --check local_agent/studio_static/app.js`: passed.
- `python -m compileall -q local_agent scripts tests`: passed.
- Compilation of 13 embedded strings containing Blender scripts: passed. This
  checks Python syntax only; it does not check bpy runtime APIs.
- `python -m ruff check --select F821,F822,F823 local_agent tests scripts`: passed.
- `git diff --check`: passed.

## Windows acceptance before merge or installation

Use a separate checkout/worktree, not the active C:\AI-Agent installation. Stop
neither the running agent nor current rendering for these tests. Do not enable
mailbox polling or send new render jobs as part of the offline suite.

```powershell
git clone https://github.com/bjiow131/free-video-generator.git C:\AI-Agent-Audit-20261013
Set-Location C:\AI-Agent-Audit-20261013
git switch audit/blender-agent-20261013
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-github-mailbox.txt
.\.venv\Scripts\python.exe -m compileall -q local_agent scripts tests
.\.venv\Scripts\python.exe -m local_agent.test_scope all
```

For real, explicitly labelled fixture rendering on that Windows machine:

```powershell
$env:BLENDER_EXECUTABLE = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
& $env:BLENDER_EXECUTABLE --version
ffmpeg -version
ffprobe -version
$env:STUDIO_LIVE_BLENDER = '1'
.\.venv\Scripts\python.exe -m pytest -q tests/test_studio_live_blender.py
Remove-Item Env:STUDIO_LIVE_BLENDER
```

The live test renders 18 frames in a temporary workspace, checks changing image
hashes, a saved blend, MP4 dimensions and decoded frame count. Passing it confirms
only the labelled fixture route. A production acceptance must additionally use
approved Mia assets, body/facial rig inspection, ordered action execution, camera
continuity, cancellation/restart and visual review. That route is currently blocked
by the unfinished items above.

Do not merge into main or install this branch automatically. Review the targeted
changes and run Windows acceptance first. Failed/skipped Actions must remain
reported as failed/skipped/pending, never as a successful render.
