# Local Migration Audit — Current State and Preparation Plan

Last updated: 2026-10-09
Repository: bjiow131/free-video-generator
Audit branch: feature/local-first-migration
Scope: static review of repository files only. No Windows machine, real generator, or local runtime was available during this pass.

## Executive summary

The repository already contains a local FastAPI application, a Windows launcher, a POSIX launcher, a Docker option bound to loopback on the host, local settings/workspace directories, and filesystem-backed task state. Therefore, leaving Render does not appear to require moving the whole application from a cloud-only runtime: the main app has a documented local launch path.

However, this is not yet proof that the complete product works reliably on Windows. The local-agent code is an orchestration foundation, not a finished independent generation engine. It defines a `VideoBackend` protocol but no concrete adapter in `local_agent`, and it has no standalone CLI. A real generator integration, Windows tests, real-media tests, and recovery tests remain open.

## Evidence inspected

- `README.md`: now documents the Windows first-run sequence (`setup_windows.bat` then `start_windows.bat`), loopback URL `http://127.0.0.1:8765`, FFmpeg/ffprobe requirements, and that the Agnes key is needed for generation but not for opening the UI. Provider availability/limits remain controlled by Agnes.
- `start_windows.bat`: checks for an existing `.venv` and `ffmpeg`, starts `server.py`, and opens the UI after readiness. The original unbounded readiness loop has now been changed to a maximum of 30 two-second attempts; Windows runtime behavior is still unverified.
- `setup_windows.bat` (added on this branch): checks Python 3.10+, `ffmpeg`, and `ffprobe`; creates `.venv` if missing; installs `requirements.txt`. It does not install FFmpeg itself and has not been run on Windows.
- `start.sh`: validates Python and FFmpeg, creates a venv, installs requirements, checks port 8765 when `lsof` exists, and runs `server.py`.
- `Dockerfile`: installs FFmpeg and runs `server.py`; container environment sets `HOST=0.0.0.0`. This is safe only when its port is published as intended.
- `docker-compose.yml`: maps host port 8765 to container port 8765 on `127.0.0.1`; persists `.working_dir` and `.agnes_config`.
- `.gitignore`: excludes `.env`, `.working_dir/`, `.agnes_config/`, and Python build/runtime artifacts.
- `core/config.py`: default output/workspace is project-local `.working_dir`; configuration is stored in `.agnes_config/config.json`; API key may come from `AGNES_API_KEY` or local config.
- `server.py`: FastAPI application defaults to `HOST=127.0.0.1` and `PORT=8765`; local origin/host checks include a compatibility path for `RENDER_EXTERNAL_HOSTNAME`. App lifecycle indexes local task files and handles interrupted task state.
- `local_agent/runner.py`, `manifest.py`, `checkpoint.py`, `ffmpeg_media.py`: local orchestration, manifest validation, atomic checkpoint approach, and FFmpeg tooling exist, but the technical backlog already records security/resource-limit gaps and missing real backend/CLI.
- `requirements.txt`: Python dependencies are declared; Python version and dependency resolution still need a clean Windows install test.
- `.github/workflows/server-test.yml`: Linux CI compiles/imports/tests, builds Docker, checks JS syntax and checks launcher text. On this branch, feature-branch pushes are included and the static launcher contract now requires bounded-wait markers. Its own summary states it does not replace Windows or real-media checks.

## Findings

### F1 — Local operation is already an intended mode
**Status:** FOUND (static)
The main server and launch scripts are designed for local use. First migration task is to verify and harden the existing local path, not to invent a new hosting stack.

### F2 — Windows launcher can wait indefinitely after a failed startup
**Status:** FIXED IN SOURCE; runtime behavior NOT RUN
The original launcher polled `http://127.0.0.1:8765/health` without a timeout. On this branch, `start_windows.bat` now stops waiting after 30 two-second attempts and displays an actionable startup error. This prevents an infinite readiness loop, but it does not yet monitor the child process directly or guarantee child cleanup. Windows execution and stop behavior remain unverified; a later pass should improve process lifecycle handling if tests show it is needed.

### F3 — Listener defaults are local-only, but Docker differs internally
**Status:** FOUND (static)
`server.py` defaults to loopback. The Docker image sets `HOST=0.0.0.0`, while Compose publishes the host port on `127.0.0.1`. Keep this distinction documented and verify that no default configuration exposes the app to LAN/public networks.

### F4 — Render-specific host compatibility remains in application code
**Status:** FOUND (static)
`server.py` reads `RENDER_EXTERNAL_HOSTNAME` as a configured host. This does not by itself prove a runtime dependency, but it is a cloud-specific compatibility branch that should be removed or isolated after tests confirm local host/origin protections remain correct.

### F5 — Local data is file-based and has implicit default locations
**Status:** FOUND (static)
Task state, generated media, workspace paths, and API-key config are stored in local directories. Migration needs a documented data-root contract, backup/restore behavior, and a safe upgrade policy before changing any paths. Do not relocate or delete existing user data automatically.

### F6 — Local agent is not yet a standalone generation server
**Status:** FOUND (static; real backend unverified)
`local_agent` defines protocols and an orchestrator, but no concrete `VideoBackend` implementation or standalone CLI is present in the package. Do not present it as a ready replacement for the current `server.py` generation pipelines until a real, supported adapter is implemented and tested.

### F7 — External AI API use is separate from where the app runs
**Status:** CONFIRMED BY README
Local hosting removes Render from the app runtime, but Agnes calls still require internet and remain subject to the provider's access, rate limits, and availability. Offline inference is a separate project milestone.

### F8 — Existing tests do not prove Windows or real-media readiness
**Status:** FOUND (static)
Current CI's launcher check is textual. Existing local-agent tests use fake media bytes according to the master backlog. Need Windows execution, real FFmpeg fixtures, real MP4/PNG validation, and an actual backend end-to-end run before claiming readiness.

## Recommended migration sequence

1. Preserve current working branch and user data; continue only on `feature/local-first-migration`.
2. Complete source inventory: startup, host binding, Render references, environment variables, storage paths, health checks, subprocesses, and CI triggers.
3. Harden `start_windows.bat`: finite readiness deadline, process-exit detection, actionable error display, port-conflict check, and stop behavior.
4. Add a documented local configuration contract: loopback host by default, port override, explicit data/config directories where safe, secret handling, and diagnostic output. Avoid changing existing paths until a backward-compatible migration plan exists.
5. Review and isolate Render-only host logic while preserving host/origin security tests.
6. Complete the existing `local_agent` backlog before making it the production task runner; do not duplicate task engines unnecessarily.
7. Verify official generator automation support on the target Windows computer; implement an adapter only after its real interface and capabilities are confirmed.
8. Execute clean Windows setup, UI/health checks, real-media tests, generation, multi-scene assembly, restart/resume, and backup/restore.
9. Only after evidence is complete, decide whether to deprecate Render-specific files/configuration. No deployment or merge without explicit approval.

## Acceptance checklist (initial)

- [ ] Clean Windows install succeeds from a path containing spaces and Cyrillic characters.
- [ ] Missing Python/venv, dependencies, FFmpeg, occupied port, and import errors produce actionable messages.
- [ ] Server starts once, binds only to 127.0.0.1 by default, and exposes UI and health endpoint.
- [ ] Launcher times out instead of looping indefinitely when startup fails.
- [ ] Ctrl+C/stop closes the server without orphaned processes.
- [ ] Existing task history, workspace paths, config, and generated files remain intact after upgrade.
- [ ] No Render URL or environment variable is required for local operation.
- [ ] API key is not logged or committed; runtime data and media remain outside Git.
- [ ] Real FFmpeg validates a known-good MP4 and rejects corrupt/empty files.
- [ ] Actual generator adapter creates a real clip and reports honest job state.
- [ ] Multi-scene generation, final-frame chaining, assembly, playback, restart/resume, and failure recovery are tested.
- [ ] Backup and restore are demonstrated.
- [ ] All test results are recorded with command/output; unrun items remain NOT RUN.

## Limitations of this audit

This was a static repository review performed through GitHub file access. No code was executed, no Windows machine was accessed, no API request was sent to a generator, and no actual media was produced. Findings labeled FOUND are source-level observations, not claims of runtime reproduction.


## Work completed after initial static review

- `start_windows.bat` now has a bounded readiness loop (up to 60 seconds) and an explicit failure message rather than waiting indefinitely.
- Added `setup_windows.bat` for a repeatable first-run Python environment/dependency setup; FFmpeg remains a separately installed prerequisite.
- Corrected the Windows README instructions so they no longer falsely say an API key is required just to start the server.
- `.github/workflows/server-test.yml` now runs for `feature/**` pushes and checks that the launcher includes the bounded readiness logic.
- Source changes are committed on `feature/local-first-migration`; no Windows runtime test or CI result has yet been observed for these commits.
