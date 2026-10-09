# Local Video Agent — Progress Log

Updated: 2026-10-09 (Task 2 reliability pass)

## Confirmed repository state

- Working branch: `feature/local-video-agent`.
- Draft PR #9 remains open against `main`: https://github.com/bjiow131/free-video-generator/pull/9
- The branch is ahead of `main`; no merge or Render deployment was performed.
- The existing GitHub Actions workflow is `.github/workflows/server-test.yml`. It runs on matching branch pushes and includes compile/import, unit tests, Docker build, UI syntax, and Windows launcher checks.
- The GitHub connector did not return workflow-run records for the inspected commits. This is **not** evidence of a passing or failing CI run.

## Changes made in this offline development pass

- Added `local_agent/ffmpeg_media.py`: subprocess calls use argument lists and `shell=False`; ffprobe metadata is checked; missing/empty files, missing video streams, unreasonable duration/dimensions, incompatible stream-copy concatenation, command failures and timeouts raise actionable `MediaError` messages.
- Added mocked tests for FFmpeg argument safety, Unicode/space-containing paths, duration/stream failures, timeouts, concat ordering, compatibility checks and source-overwrite prevention.
- Hardened `local_agent/manifest.py`: schema version is checked; project/scene IDs are restricted to safe path components; durations must be integers; ratios and MP4 output filenames are validated; project name is preserved.
- Hardened `local_agent/checkpoint.py`: unsupported/corrupt checkpoint shapes and changed manifests are rejected rather than silently resumed; checkpoint locks are shared across store instances in one process.
- Fixed runner recovery so a completed scene whose stored media fails revalidation is invalidated and regenerated instead of aborting before the retry path.
- Runner exceptions during setup now persist a terminal `failed` state when possible; explicit asyncio task cancellation persists `cancelled` and is re-raised to the caller.
- A pause requested during generation takes effect when the active backend call returns, before validation proceeds. Cooperative cancellation requests are checked at generation, frame-extraction and assembly boundaries; they do not forcibly terminate a backend's native operation mid-call.
- Permanent media-validation and input errors do not consume the retry loop. Scene attempt budgets are total per scene across resumes, not reset on each invocation.
- A scene exhausted by retries is now marked `failed` rather than `paused`, and the runner never advances beyond it.
- Added an ownership-token runner lock file with PID checks to reject concurrent execution of the same project across processes; the lock is released only when its token matches. Stale dead-PID locks are reclaimed, while malformed/unverifiable locks fail closed.
- Added two-, ten- and one-hundred-scene fictional manifests under `examples/local_video_agent/` and tests that validate their scene counts.
- Added duplicate-run regression coverage, checkpoint corruption-preservation coverage, permanent-validation-error coverage, cancellation-state coverage, setup-exception coverage and a test for retry-budget enforcement across resume.
- Checkpoint writes now use unique temporary files in the same directory and atomically replace the last known-good checkpoint only after flush/fsync; orphaned temporary files are never treated as valid checkpoints.
- Added workspace containment validation so a project output directory redirected by a symlink/junction is rejected.
- Added manifest validation tests for traversal-like identifiers, invalid duration types/ranges, unsafe output names and schema-version rejection.
- Hardened `scripts/inspect_wan2gp_api.py`: loopback-only URLs, positive timeout, bounded response reads, malformed/unexpected JSON reporting, and reduced risk of printing URL credentials/query data.
- Added mocked inspector tests for success, HTTP/connection errors, malformed and oversized responses, loopback restrictions, and omission of component default values.
- Updated Wan2GP discovery notes based on upstream public API/CLI/settings documentation.

## Verification status

### Executed and passed
- No Python test suite or real FFmpeg command has been executed in this development environment.

### Executed and failed
- Attempted to clone the branch for local test execution, but the environment could not resolve `github.com` (`Could not resolve host: github.com`). This blocked checkout; pytest itself did not run.

### Not executed
- All newly authored and existing pytest tests, including mocks. New regression coverage includes changed-manifest rejection, regeneration after saved-output revalidation failure, duplicate-run rejection/release, corrupted-checkpoint preservation and example-manifest parsing.
- GitHub Actions CI status: the workflow-run query returned an empty list for the inspected latest commit; no run result is available, so CI is unconfirmed.
- Real FFmpeg/ffprobe media validation and assembly.
- Windows-specific filesystem/subprocess behavior.
- Wan2GP API inspection against the user's installed version.
- Real GPU generation and two-scene end-to-end continuity.

## Concurrency and local service decision

- Runner ownership is guarded within the process and with a per-project exclusive lock file for cross-process exclusion. A lock with an unverifiable owner fails closed; manual inspection may be required after an abnormal shutdown if PID information is malformed. This mechanism has not yet been exercised on Windows.
- No local HTTP service was added in this pass. The runner state machine, cancellation of an in-flight backend job, and Windows lock behavior need executed tests before exposing lifecycle controls over HTTP. The first MVP remains a local CLI/process, not a Render-connected service.
- FFmpeg assembly remains stream-copy concat only; incompatible clips fail explicitly. Crossfades and normalization are not implemented.

## Known next engineering items

- Add direct checkpoint version/recovery tests and execute pause/cancel/restart regression tests under CI or a local Python runtime.
- Test cross-process locking on Windows, including PID reuse and stale lock recovery; current lock strategy has not been executed on Windows.
- Decide whether to use Wan2GP's documented in-process Python API or its inspected local Gradio API only after comparing against the installed version.
- Implement and test the Windows-local service only after the runner state machine and backend contract are reliable.
