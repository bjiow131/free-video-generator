# Blender Studio continuation checkpoint — 11 October 2026

## Authoritative GitHub branch
`feature/blender-studio-ui-20261011` in `bjiow131/free-video-generator`. **Never push directly to `main`.**

Work produced commits:
- `7fc57b37a38435b90a8dd4a90adfe677855f0d25`: Studio UI plus bounded **fixture-only** Blender pipeline.
- `1efd5609360c8194b515b1619348690dfd06603b`: ordered FFmpeg multi-scene composition.
- `67f769d90972dc5971ae7a52068d0063fd5a3fb8`: Blender launched with `--offline-mode --python-exit-code 12` in addition to `--disable-autoexec`. This is a source change, **not** a proven Windows render fix.

## Independent local development overlay
During continuity recovery, a separate experimental implementation was developed in `/mnt/data/blender_build/` with source files stored in the ChatGPT Library folder `/Blender_Agent_Work_20261011/Sources`.
It includes `studio_executor.py`, `studio_blender_execute.py`, real actor `.blend` import contract (`AgentRoot`), optional `MouthOpen` shape key animation, safe installer/rollback, and Python regression tests.

**Do not blindly overwrite the GitHub Studio code with this overlay.** The two implementations use different interfaces (`studio_jobs.py` vs `studio_executor.py`, `studio_blender_scene.py` vs `studio_blender_execute.py`, and incompatible interpreter signatures). Reconcile on a dedicated child branch after reviewing the files.

Local isolated overlay verification: 39 tests passed, 3 legacy tests deselected because `local_agent.story_plan` / `scene_compiler` from the full repo were not present in the overlay. Real FFmpeg did concatenate two synthetic MP4 clips and pixel samples established correct order. `node --check` and `compileall` passed. **These test counts do not validate the exact GitHub branch implementation.**

## Strictly unverified
No real Blender 5.2.2 execution on Windows/RTX 4060, actual render-frame changes, 3D Mia rig, installer/rollback PowerShell, or end-to-end real-character video have been verified. The Work branch intentionally blocks real characters; fixture-only success is not acceptance of real-character production.

## Resume steps
1. Fetch the latest GitHub branch HEAD before edits. Work advanced asynchronously from `60c6e6a` to `1efd5609` while the assistant was working; preserve its later commits.
2. Compare the Work fixture pipeline to the independent source overlay and choose a single canonical renderer; do not merge two competing code paths without design/integration tests.
3. Run full repository tests on Windows Python 3.11; isolate the agent suite from legacy Agnes cloud modules.
4. Validate actual Blender fixture render with two non-identical frames, scene.blend, playable MP4, mouth keyframes, and two-scene concatenation.
5. Only then opt in real actor .blend libraries with strict root/rig readiness. No 2D PNG as a 3D character.
6. Check installer and rollback on a disposable Windows checkout before changing `C:\\AI-Agent` or valuable `C:\\AI-Agent-Workspace` data.

No work is running in the background under this checkpoint.