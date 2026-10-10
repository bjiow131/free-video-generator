# Local Video Agent — Architecture and Implementation Plan

Status: design baseline (2026-10-09). This proposal is on feature/local-video-agent; it does not change production behavior or deploy to Render.

## Goal

Add a Windows desktop agent that executes video scenes on the user's computer and integrates with the existing AI Studio web application. The phone is explicitly out of scope. The existing Agnes image-generation capability may create the initial reference image; video generation is delegated to a local video backend through an adapter. The exact backend is selected only after inspecting the computer and the installed model.

The user can submit a project with N ordered scene prompts (10, 50, 100+), per-scene duration, aspect ratio, global character/style instructions, and an optional initial image. The agent processes dependent scenes sequentially, extracts the last valid frame of each completed video, and uses it as the next scene's input image.

## Existing repository capabilities to reuse

- FastAPI server in server.py and existing task APIs.
- AgnesImageAPI in core/api/agnes_image.py for initial/reference image generation.
- AgnesVideoAPI in core/api/agnes_video.py remains available but is not the planned local-video engine.
- TaskManager and task checkpoints/event logs in core/task_manager.py.
- SceneTask / CreativeVideoTask in models/task.py, which already contain scene status, video file, end-frame fields and chaining-related fields.
- Existing FFmpeg utilities and video concatenation implementation.

Do not duplicate existing pipeline functionality until the current endpoint and model contracts have been mapped. The first implementation pass must inspect server.py, current CreativeVideoTask orchestration, file paths, and deployment persistence behavior.

## Target architecture

1. AI Studio / Render control plane
   - Accepts and validates a project manifest.
   - Shows project/scene states and progress.
   - Issues authenticated work to a paired desktop agent.
   - Receives scene status, metadata, final-frame image and video outputs.
   - Stores only durable references in task state; large binary files should not be placed in JSON state.
2. Windows Local Agent (outbound-only connection)
   - Runs as a separate Python process on the computer; no mobile dependency and no router port-forwarding.
   - Pairs with the web app using a one-time pairing code or generated agent token. Store tokens in the OS credential store where practical; never log secrets.
   - Polls/long-polls the control plane over outbound HTTPS. WebSocket is optional later, not required for the first version.
   - Claims one project/scene lease at a time and reports heartbeats.
   - Downloads input images, verifies content type/size/checksum, calls a backend adapter, waits for completion, validates the resulting MP4, extracts the final frame, and uploads results.
   - Writes local durable job checkpoints so computer/agent restarts do not force successful scenes to be regenerated.
   - Uses bounded retries, exponential backoff, timeouts and a user-visible failed state.
3. Local video backend adapter
   - Interface boundary isolates the agent from a specific local program/model.
   - Initial contract: capabilities(), generate_i2v(prompt, input_image, duration_seconds, aspect_ratio, output_path, options), cancel(job_id) where supported, and health checks.
   - Do not automate a GUI or depend on undocumented/private endpoints when a supported local API/CLI is available.
   - Backend-specific integration is blocked until the actual installed program, version, launch method and API/CLI are inspected on the computer.
4. Media processing
   - Use FFmpeg for metadata validation and final-frame extraction; do not assume a hard-coded FPS or frame count.
   - Extract the last decodable frame (optionally a small safety offset before EOF if the final frame is corrupted/black), then write atomically.
   - Validate non-zero file size, video stream presence, duration tolerance and decodability before marking a scene complete.
   - Store a checksum and frame/video paths or remote object IDs in the scene result.

## Sequential scene algorithm

For scene 1, resolve the supplied start image; if none is supplied, request/generate one through the configured image-generation path. Validate the image and save a durable copy.

For each scene i from 1..N:
1. Confirm scene i has a prompt and valid parameters.
2. Use the project start image for i=1; otherwise use the verified final frame of scene i-1.
3. Append global character identity, wardrobe, style and continuity instructions to the scene prompt without overwriting the authored scene action.
4. Submit image-to-video generation to the local backend.
5. Wait using backend status or process supervision; publish real progress only when available. Never fabricate percentage or ETA.
6. Validate the video; extract and validate its last frame.
7. Atomically persist video, final frame, metadata, checksums and completion state.
8. Only then release scene i+1.
9. On a recoverable failure, retry the same scene with a configurable cap. Never advance the chain without a valid final frame. If retries are exhausted, pause the dependent chain and retain all completed work.
10. After all scenes complete, concatenate in scene order with FFmpeg, verify the final MP4, and produce a manifest/report.

Independent scenes may later support a separate parallel mode. Continuity mode must be sequential by default.

## Data and reliability rules

- Use stable project_id, scene_id, agent_id, attempt_id, and idempotency keys.
- States: draft, queued, claimed, running, validating, completed, retry_wait, failed, paused, cancelled.
- Persist every transition and error summary; never store API keys, pairing tokens or raw base64 image contents in logs.
- Scene completion is idempotent: reprocessing a completed scene must not silently overwrite a valid result.
- Store binary assets separately from task JSON. Use temporary upload URLs or authenticated upload endpoints with checksums and size limits.
- A Render filesystem may be ephemeral; do not assume a local path or in-memory queue survives redeploys. Before production integration, verify available persistent storage/database and choose durable asset storage or explicitly document local-only storage.
- Enforce maximum prompt length, maximum scene count configurable by server, allowed image/video MIME types, request timeouts, path traversal protections and agent authorization.
- The agent must only download assets from the configured trusted AI Studio origin or explicitly allowed storage host; prevent arbitrary-URL fetch/SSRF.
- User can pause/cancel a project. Cancellation must stop future scene claims and request cancellation of the current backend job when supported.
- No silent switch to cloud video generation if the local backend is unavailable.

## UI scope (desktop-first)

Add a dedicated production/project screen to the existing AI Studio rather than redesigning unrelated pages:
- project name and global continuity/style instructions;
- ordered multiline scene editor (one prompt per scene; allow import/export JSON or TXT);
- scene count, duration, aspect ratio and initial image selection;
- selected agent/backend health and pairing state;
- project progress with completed/running/failed/queued counts;
- per-scene preview for input frame, video and extracted final frame;
- pause, resume, cancel and retry failed scene;
- final MP4 and a downloadable project manifest.

The web UI is only the control plane. The desktop agent and local model keep running if the browser tab is closed.

## Milestones

### M0 — repository and protocol audit
- Map existing endpoints, state model, file paths, task lifecycle, auth, and Render persistence.
- Confirm compatibility with current Agnes image generation and existing scene-chain fields.
- Deliver an endpoint/data-flow map before touching production routes.

### M1 — testable local core (no hardware required)
- Implement manifest validation, state machine, adapter protocol, durable local checkpoint format, media validation abstractions and mocked-backend tests.
- Test N-scene sequencing, retries, pause/resume, restart recovery, missing frame, corrupt MP4, duplicate result and cancellation.
- No actual model inference and no Render deployment in this milestone.

### M2 — Windows agent shell
- CLI startup, config file, health command, structured logs, local workspace and secure pairing.
- Backend adapter selected after inspecting the computer.
- Add packaging/start-on-login only after CLI reliability.

### M3 — control-plane integration
- Add authenticated agent pairing, lease/heartbeat/result endpoints, asset transfer and UI status.
- Verify durable queue and asset persistence before connecting production deployment.
- Integrate behind a feature flag; keep current AI Studio flows unchanged.

### M4 — end-to-end validation
- Two-scene continuity test, then 5, 10 and 100-scene mocked/load tests.
- Real 2-scene model test on the computer; inspect actual seam continuity and runtime.
- Verify interruption/restart, storage pressure, failed generation and final MP4 assembly.

## Acceptance criteria

- The phone is not part of the workflow.
- A project of 100 prompts can be accepted without creating 100 manual jobs.
- Continuity mode never starts scene i+1 until scene i video and final frame pass validation.
- Completed scenes survive browser closure and agent restart; they are not regenerated unnecessarily.
- Failure at scene i preserves scenes 1..i-1 and can resume at i after retry.
- Progress reflects actual states and backend-reported progress only.
- The final MP4 is assembled in exact scene order and validated.
- Existing Agnes image generation and unrelated AI Studio workflows remain functional.
- All changes are developed on this feature branch first; do not merge or deploy automatically before tests and explicit review of the resulting diff.