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
## Continuation — five verified work blocks (11 October 2026)

Source of truth remains `feature/blender-studio-ui-20261011`. **Do not modify `main`.** No background task is running.

### Block 1 — inventory and baseline
- The earlier Work state is already in GitHub through `80a704c638fbd1deebc54cacc643cd6d7153b0ba`.
- Independent partial overlay at `/mnt/data/blender_build`: 39 pytest passes, 3 intentionally deselected because its local checkout omits older project modules; `compileall` and `node --check` passed.
- Those 39 tests are **not** a test pass of the canonical GitHub branch.

### Block 2 — subprocess cancellation (committed)
- `c569fdda2757f609bb4ff8e106591cba0afd1423`: atomic cancellation check and process spawn for Blender, scene FFmpeg and multi-scene FFmpeg; replace blocking FFmpeg `subprocess.run` with cancellable `Popen/wait`.
- `031fe688b2bf87e1100dde64aa3fc3160753c92f`: three mocked race regression tests.

### Block 3 — stale project footage / readiness (committed)
- `2588405d59edce2fdddb8df403e83b4cf28ef1a6`: scene fingerprints in saved jobs, refuse assembly after scene/settings/passport changes.
- `589b1d9f215ce90eef847c044259bec7ca165cfa`: FFmpeg assembly regressions for edited prompt and FPS.
- `93ee2f1cd07f358416fe16cf70a66d22d2c087df`: clear stale UI plan when editing scene, participants, props or render settings.

### Block 4 — live acceptance / installer (committed)
- `3b7054f77535a5df782534dc24afd6a2fc04f7b6`: opt-in temporary-workspace real Blender/FFmpeg acceptance, 18 frames + hashes + ffprobe video frames.
- `2fef614f2a28770af17ee0c3777e1520f984f5c0`: installer includes test suite and uniquely named backups.
- `0cd13f74bcd0d65b910d58d8b0903cdbefc0ae3a`: explicit Windows acceptance commands in `docs/BLENDER_STUDIO_WINDOWS_ACCEPTANCE_20261011.md`.

### Block 5 — truth-in-reporting handoff
- GitHub branch HEAD before this checkpoint update: `0cd13f74bcd0d65b910d58d8b0903cdbefc0ae3a`.
- All listed code/test/docs files verified present through the GitHub connector.
- **Not verified**: the new regression suite against the exact GitHub checkout, Blender 5.2.2 real render on Windows, PowerShell installer/rollback on Windows, user GPU, actual Mia rig or non-fixture character animation.
- The chosen canonical engine is Work's `studio_jobs.py` + `studio_blender_scene.py` (fixture only). Do **not** overwrite this with incompatible experimental `studio_executor.py` files from the local overlay.
- Next engineering gate: full Python 3.11 suite and live Blender acceptance on a disposable Windows checkout, then implement a deliberate real-asset/rig importer with its own readiness checks. Do not report fixture rendering as Mia production readiness.

The five-block notes are also saved in `/mnt/data/blender_build/docs/CONTINUE_AFTER_INTERRUPTION.md` in the current local container session.
