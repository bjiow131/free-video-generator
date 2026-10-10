# Local Video Agent — Existing Project Integration Audit

Audit date: 2026-10-09. Scope: read-only inspection of the main branch before wiring the new local automation core into existing production routes.

## Findings

### Existing local ComfyUI bridge

The current server already has optional ComfyUI endpoints:
- GET /api/comfyui/status
- POST /api/comfyui/generate
- POST /api/comfyui/preview

Implementation is in core/api/comfyui.py. It defaults to http://127.0.0.1:8188, can check /system_stats, queue an API-format workflow via /prompt, poll /history/{prompt_id}, parse image/video output descriptors and download outputs via /view. Workflow inputs can be bound through environment variables for prompt, seed, width and height.

Implication: do not build a second ComfyUI HTTP client. If the selected local video program exposes a compatible supported API, extend/reuse the current adapter only after checking workflow inputs, image upload/reference handling, video output format and job completion semantics. The existing client does not yet provide a proven end-to-end image-to-video continuity workflow by itself.

### Existing image and task routes

- POST /api/image/generate creates images; GET /api/image/{task_id} serves an image and GET /api/image/{task_id}/download downloads it.
- POST /api/tasks/simple creates a simple video task.
- POST /api/tasks/creative creates the existing multi-scene creative task.
- GET /api/tasks and GET /api/tasks/{task_id} expose task state.
- GET /api/video/{task_id} and GET /api/video/{task_id}/download serve generated video.
- POST /api/tasks/{task_id}/resume and POST /api/tasks/{task_id}/stop already exist.
- AgnesImageAPI and AgnesVideoAPI are separate clients in core/api/agnes_image.py and core/api/agnes_video.py.

### Existing scene/task state

models/task.py already defines SceneTask fields for scene index/status, end_frame_prompt, end_frame_file, video_id, video_status, video_file, final_clip and duration. CreativeVideoTask includes reference_image, end_frame_images, use_custom_end_frames, generate_end_frames_from_ref, pregenerated_end_frames, scenes, chaining_mode, and pipeline status fields.

core/task_manager.py already writes task_state.json atomically, a checkpoint.json snapshot and an events.jsonl log. The local agent should reuse compatible semantics where practical, but should keep local machine paths separate from server-visible asset references.

### Deployment-mode decision

The first MVP should be desktop-first and must not involve the phone. Two deployment modes are technically distinct:

1. Local mode (recommended first): run the existing FastAPI app on Windows on the same computer as the local video program. The server can call loopback APIs and use local files directly. This avoids remote-agent pairing and cloud-to-LAN access for the initial two-scene test.
2. Render control-plane mode (later, optional): keep the Render-hosted UI and use a paired Windows agent that makes outbound HTTPS requests to Render. Render cannot directly access 127.0.0.1 on the user's computer. This mode requires agent authentication, job leases, asset upload/download and durable cloud storage.

Do not assume that the hosted Render service can read a Windows path or call a local 127.0.0.1 API. Do not expose the local model API to the public internet as a shortcut.

## Recommended integration sequence

1. Keep all new work on feature/local-video-agent; no main merge or Render deployment yet.
2. Add tests for manifest validation, checkpoint recovery and ordered final-frame chaining (the initial hardware-independent core is now present on the feature branch).
3. Implement a media adapter around FFmpeg and verify final-frame extraction/MP4 validation.
4. When the computer is available, inspect the exact installed video program and supported API/CLI. If it is ComfyUI-compatible, reuse core/api/comfyui.py rather than duplicate it. If it is Wan2GP or another program, implement a separate adapter.
5. First run the app locally on Windows and prove a two-scene chain. Only then decide whether to add the Render-to-desktop agent bridge.
6. Before any hosted agent implementation, resolve durable storage: task_manager checkpoints use the configured working directory, and a Render instance's local filesystem must not be treated as durable across redeploys without verification.

## Known unverified items

- Exact local program/model, version and supported automation interface are not yet available for inspection.
- Whether the selected model accepts an input image, exact duration and aspect ratio must be verified against the installed workflow/API.
- Real generation quality, continuity across scene boundaries, GPU memory use and speed cannot be measured until the computer is available.
- No production routes, Render environment variables or main-branch files were changed by this audit.