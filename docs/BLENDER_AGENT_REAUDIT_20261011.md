# Blender agent repeat audit — 11 October 2026

Scope: `audit/blender-agent-windows-only-20261011`, PR #39, starting at
`3b4a2f9b946cfc76a463a44ae594e95bab9a4993`. The separate legacy cloud application
was not executed or modified. No merge to main or workstation deployment.

## Findings repaired

- Inspection could report success from an old `mia_inspection.json` when a new
  Blender script failed to produce a report. Each invocation now writes a private
  temporary report, validates it, and only then replaces the previous report.
- Blender script exceptions did not explicitly set a failing process exit code.
  Bundled script launches now set `--python-exit-code 1`. GUI project opening also
  explicitly disables automatic embedded Python execution. This is not a sandbox.
- Mia workflow and rigging checked project symlinks after resolving their targets.
  They now reject links before resolution. Reparse-point detection covers Windows
  Python 3.11, where `Path.is_junction` is unavailable. Blockout log destinations
  are checked before launch as well.
- Failed explicit blockout overwrite destroyed previous outputs. Existing outputs
  are now backed up before modification and restored on a failed run. A failed
  restoration retains the backup and reports its location. This does not guarantee
  automatic recovery from power loss during the operation.
- Reports of the same kind in the same second overwrote one another. Unique report
  names and private temporary files now preserve each report independently.
- Multiple lines for one speaker reinitialized the mouth at shot start, overwriting
  earlier animation; iterator-based object lists were consumed after one line.
  Initialization now occurs once per speaker, with reusable object lists and time
  ordering. This is tested with fake shape keys, not a real production facial rig.
- Weighted dialogue allocation could assign overlapping frames to short lines, or
  produce adjacent identical mouth states. Every line receives at least one frame;
  generated cues satisfy the existing validator and end closed. A one-frame line
  cannot visibly articulate and remains closed.
- Three repeated registry entries could make an ambiguous asset valid again.
  Ambiguity now remains sticky. Replaced assets-root links are rejected.
- Fixed temporary filenames in asset scans, story saving and compilation could be
  deleted by a second writer that failed to create them. Cleanup now removes only
  a temporary file created by the current invocation.
- Windows device names were accepted as project/scene/output/task filenames, and
  scene IDs could differ only by letter case. Portable filename rules now reject
  these collisions before filesystem operations.
- The alternative PowerShell mailbox installer used the dependency-free local
  launcher requirements, then attempted requests-dependent tests. It now installs
  mailbox dependencies and invokes the complete explicit agent test scope.
- That installer offered an unsupported remote-approval mode; the runner neither
  opted into the mailbox nor displayed approval prompts. It now explains the actual
  local approval requirement, opts in only on explicit mailbox launch, and keeps
  the console visible. Scheduled-task registration does not imply unattended work.

## Verification performed in this session

- Baseline: **457 passed** on Linux, Python 3.12.14.
- New regression reproductions failed against the old code for stale inspection,
  project aliases, log symlinks, duplicate assets, foreign temporary-file cleanup,
  repeated-speaker animation, report collision, overlapping dialogue timing and
  destructive blockout overwrite.
- Final local suite: **476 passed, 1 skipped**. The skipped test requires an actual
  Windows directory junction. Existing Blender calls are mocked; they are not render
  acceptance tests.
- Real FFmpeg/ffprobe integration: a 24-frame changing test clip, exact decoded last
  frame comparison, two-clip stream-copy assembly with byte-identical decoded order,
  4-second output validation and no audio. Unicode, spaces and apostrophe paths used.
- Python compilation and `git diff --check` passed.
- Windows CI for the new commit must be checked separately; previous PR checks do
  not establish that this new revision passes on Windows.

## What this audit does not establish

The current compiler still explicitly emits `planning_only` and
`not_executable_yet`. Camera animation, asset importing and general character actions
are not a working end-to-end Blender scene executor. The generic sequential video
runner relies on an injected backend; this audit does not create a Blender video
backend. The generated Mia rig is a rigid proxy, not production skinning or a facial
rig. Full story-to-animation-to-MP4 is therefore **not demonstrated**.

Required workstation acceptance remains: actual Blender version/API compatibility,
GUI opening, render output, RTX 4060 use, production character/face controls,
Credential Manager with the real account, live private mailbox and interactive
approval, and restart/power-loss behavior. PowerShell installer execution requires
Windows; static contract checks alone do not prove installation on the user's PC.

The mailbox still requires an interactive local confirmation for every task.
No approval checks were weakened. No Agnes service, credentials or cloud-generation
API were used.
