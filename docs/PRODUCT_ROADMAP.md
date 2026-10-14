# Product Roadmap — Local-First AI Studio

Last updated: 2026-10-09
Status: Planning baseline; implementation and acceptance tests are tracked separately.

## Product direction

Build a dependable AI production studio that is installed and operated locally on the user's Windows computer. It should support projects that can be resumed, audited, and exported without requiring Render or any public deployment. Network publication is a later, explicit release decision—not part of development or acceptance.

## Non-negotiable architecture rules

1. Local-first runtime: the application UI, task orchestration, project metadata, history, logs, and media outputs run/store locally by default.
2. No Render runtime dependency: no required Render service, URL, database, filesystem, or deployment workflow for local development or operation.
3. GitHub is source control only. Generated media, API keys, user projects, and runtime state must not be stored in the repository.
4. External model providers are adapters, not the application core. A local app may use a remote AI API when configured, but must clearly disclose that inference then requires internet/provider availability.
5. Local model execution is a separate capability milestone; do not claim full offline AI generation until an actual local model adapter has been installed and tested.
6. Bind the local server to loopback by default (127.0.0.1). LAN/public exposure is out of scope until a deliberate security review and explicit release approval.
7. Do not merge into `main`, deploy, or publish the product without explicit user approval.
8. Never report a test as passed without recorded execution evidence.

## Product workstreams

### A. Local application and startup
- A reliable Windows setup path with clear Python, virtual-environment, FFmpeg/ffprobe, port, and configuration diagnostics.
- One-command start/stop behavior that does not silently loop forever if the server fails.
- Health/readiness checks, logs, and a safe loopback-only default.
- Reproducible setup from a clean Windows account and a path containing spaces/non-ASCII characters.

### B. Project and asset persistence
- Local project library with stable IDs, metadata, assets, outputs, and history.
- Durable task state/checkpoints and recovery after application or machine interruption.
- Backups, disk-space warnings, and conservative cleanup of temporary/partial outputs.
- Explicit path boundaries; credentials and media must remain outside version control.

### C. Production engine
- Common task contract for image generation, video generation, TTS, and assembly.
- Provider adapters isolated from orchestration; capability discovery for ratios, durations, image references, progress, cancellation, and job IDs.
- Idempotent task submission where supported, bounded retries, truthful cancellation, and validated artifacts before marking work complete.
- Reuse valid completed scenes; invalidate downstream work when an upstream reference or prompt changes.

### D. Creative workflow modules
1. Character Studio: reference images, appearance/voice/traits, version history, and consistency notes.
2. Story Engine: worlds, characters, seasons, episodes, scripts, storyboards, and continuity.
3. Scene Studio: prompts, reference assets, durations, aspect ratios, generation status, and selective regeneration.
4. Editing and export: voice, music, timing, captions when requested, transitions, and MP4 assembly.
5. Multi-format output: 9:16, 16:9, and 1:1 profiles with safe zones and platform-specific export presets.
6. Asset library: searchable reusable images, audio, video, prompts, styles, and provenance.
7. Quality Gate: file integrity, duration, dimensions, black/empty frames, audio presence, and semantic checks only where a suitable model is actually available.
8. Studio Control Center: projects, task queue, stage-based progress, logs, failures, recovery, and estimates grounded in observed measurements.
9. Growth Lab: optional manual/imported publishing metrics and comparisons; no platform integrations until access, policy, and reliability are verified.

These are roadmap targets, not claims that the features currently exist.

## Delivery milestones

### M0 — Audit and establish baseline (current)
- Inspect current application startup, configuration, data paths, task persistence, API boundaries, and deployment assumptions.
- Separate confirmed static findings from runtime-only unknowns.
- Create a prioritized migration plan and a reproducible acceptance checklist.

**Exit:** documented current-state map; findings have evidence/status; no unverified runtime claims.

### M1 — Safe local launch
- Make the current FastAPI application start predictably on Windows.
- Keep the listener on 127.0.0.1 by default.
- Add diagnostics for Python, dependencies, FFmpeg/ffprobe, port conflicts, and startup failures.
- Verify clean start, health endpoint, UI, shutdown, and restart on the target computer.

**Exit:** recorded Windows evidence; Render not required.

### M2 — Local data reliability
- Confirm and document data locations for settings, workspaces, task state, generated assets, logs, and backups.
- Test crash recovery, interrupted writes, duplicate launches, and safe cleanup.
- Preserve existing user data during upgrades and recovery.

**Exit:** recovery tests and backup/restore test pass on real local storage.

### M3 — Local-agent integration
- Harden the `local_agent` lifecycle, checkpoint semantics, manifest limits, filesystem safety, and media subprocess handling.
- Implement a concrete, officially supported generator adapter only after its Windows API/CLI and capabilities are verified.
- Provide usable local-agent commands or API operations for status, resume, cancel, and recovery.

**Exit:** real backend contract and tests, or an explicitly documented blocked dependency—never a mock presented as a working generator.

### M4 — End-to-end production
- Generate at least two dependent scenes using a verified backend.
- Validate frame chaining, assembly, audio where applicable, output checksums, and playable MP4.
- Test failure/retry/resume without duplicating completed work.

**Exit:** recorded real-media/backend evidence on Windows.

### M5 — Product workflows and quality
- Expand character, story, scene, asset, editing, export, and quality modules incrementally.
- Keep each feature independently testable and avoid broad rewrites without audit evidence.
- Run regression tests after each material change.

**Exit:** acceptance criteria for each module are documented and demonstrated.

### M6 — Release readiness (not authorized yet)
- Clean installation, security/privacy review, backup/restore, resource limits, error reporting, documentation, accessibility, and regression review.
- Decide separately whether any network exposure is needed.
- Obtain explicit approval before public deployment.

## Out of scope before release approval

- Public hosting, Render deployment, public URLs, and remote access tunnels.
- Exposing the local server to the LAN or internet by default.
- Rewriting the entire codebase without evidence that incremental changes cannot meet requirements.
- Claiming fully offline generation while using cloud APIs.
- Adding paid or quota-limited dependencies without evaluating and clearly disclosing them.

## Current risks and constraints

- The existing FastAPI app appears designed to run locally already, but Windows runtime behavior has not been verified in this audit.
- Existing cloud API use means local hosting does not itself make inference offline or unlimited.
- `local_agent` currently defines a backend protocol but has no verified concrete generator adapter or standalone CLI.
- CI on Linux is not a substitute for Windows, real FFmpeg/media, or real-model integration tests.
- Render-related host allowlisting remains in the current server source and should be reviewed/cleaned only after understanding the existing security checks.
- Current generated-media and task state are largely filesystem-based; migration must preserve them and avoid moving secrets/assets into Git.

## Change control

Every work session should update the existing `docs/LOCAL_AGENT_MASTER_BACKLOG.txt` with status and evidence. Use a new document only for a distinct purpose (this roadmap and the migration audit are distinct from the technical checklist). Keep work on a feature branch; do not merge or deploy without approval.
