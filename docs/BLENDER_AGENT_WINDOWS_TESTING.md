# Blender AI Agent — Windows-only target and test scope

This is the **local Blender AI Agent**, not the separate legacy web application
contained in the same repository. The Blender workflow does **not** need Agnes,
an Agnes API key, the AI Studio UI, a Docker server or an online video model.

## Supported scope

- Target platform: Windows 10/11, Python 3.11+, locally installed Blender and FFmpeg.
- The Windows launcher no longer assumes a specific Blender release. It resolves
  an explicit `BLENDER_EXECUTABLE` override first (and fails if that path is
  invalid), otherwise searches standard Blender Foundation installations for
  the newest installed version, then PATH. Setup verifies `blender.exe --version`
  without starting a render.
- The project name typed at the Windows prompt is passed through the environment
  to the Python CLI, never interpolated into a `.bat` command line. The Blender
  bridge validates that name against a strict allowlist before running Blender.
- Agent modules: `local_agent/`; local starter: `setup_blender_agent.bat`
  and `run_blender_agent.bat`; optional remote mailbox is **separate and opt-in**.
- Code-level coverage: GitHub mailbox security, immutable IDs, backup/cleanup,
  persisted scene data, checkpoint/restart, Blender bridge, dialogue cues,
  camera/scene planning, local animation adapters and media validation.
- Current `run_blender_agent.bat` offers a **fixed forest preview**. It is not
  evidence that an arbitrary multi-scene production script or dialogue render works.

## Tests that belong to this project

Run from the checkout root using a Python environment with the optional test dependencies:

```powershell
py -3.11 -m pip install -r requirements-github-mailbox.txt
py -3.11 -m local_agent.test_scope all
py -3.11 -m local_agent.test_scope security
py -3.11 -m local_agent.cli test
py -3.11 -m local_agent.cli status
```

`local_agent.test_scope` names all permitted test files explicitly and refuses
to run if a required file is absent. The mailbox poller's reviewed Git patch
worktree and the CLI's `test` operation run **that same suite**, not
`pytest -q` over the whole monorepo. No Agnes modules are imported by
`local_agent/` itself.

CI workflow: `.github/workflows/local-agent-tests.yml`.
- **Windows — complete Blender agent suite:** primary required target,
  tests actual Windows paths, locking and file-handling behavior, uses mocks
  instead of pretending Blender is installed on the GitHub runner.
- **Portable security contracts:** supplemental Linux job for purely portable
  protocol, replay and patch parser tests.

The unrelated `Server Test` workflow is maintained separately for the
legacy application and should not be interpreted as an agent readiness check.

## What needs the actual user's computer

1. Validate Blender executable path and version, and a writable workspace.
2. Create a real `.blend` project; inspect rendered preview files.
3. Validate camera movement, rig/character identity, speech mouth movements,
   multiscene timeline, final-frame continuity and FFmpeg MP4 export.
4. If opted in, verify GitHub mailbox authentication, task delivery, result
   publication, network outage recovery and local operator approval.
5. Collect error logs and compare real produced assets with acceptance criteria.

Do not claim the entire Blender agent is production-ready based on CI alone.
**Never combine the legacy cloud application's green tests with agent-specific
test counts.** Preserve small PRs, never silently merge into `main`.
