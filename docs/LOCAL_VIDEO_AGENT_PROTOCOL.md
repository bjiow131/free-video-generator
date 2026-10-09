# Local Video Agent — Control Plane Contract (Draft)

Status: draft for implementation; endpoints below are proposed and are not active until implemented. All requests use HTTPS and JSON unless uploading binary data.

## Agent identity and pairing

Pairing should be initiated by the desktop agent or an authenticated user in AI Studio. The server issues a short-lived one-time pairing code; exchanging it creates a revocable agent token. Tokens must be scoped to this application, stored hashed server-side where possible, sent only in Authorization headers, and never returned in routine status payloads. Rate-limit pairing attempts and support revocation.

## Proposed endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | /api/local-agent/pair | Exchange one-time pairing code for agent identity/token |
| GET | /api/local-agent/health | Agent reports local runtime, backend capabilities and version |
| POST | /api/local-agent/heartbeat | Renew lease and report agent availability |
| POST | /api/local-agent/claim | Claim the next eligible scene job; one active scene per agent in continuity mode |
| GET | /api/local-agent/jobs/{job_id} | Read assigned job details and asset references |
| POST | /api/local-agent/jobs/{job_id}/events | Report started/progress/validation/retry/failure events |
| POST | /api/local-agent/jobs/{job_id}/assets | Upload video/final-frame metadata or request an upload target |
| POST | /api/local-agent/jobs/{job_id}/complete | Commit validated outputs and release the next dependent scene |
| POST | /api/local-agent/jobs/{job_id}/fail | Record terminal failure and pause dependent chain |
| POST | /api/local-agent/jobs/{job_id}/cancelled | Acknowledge cancellation |

These routes are a proposal. Before implementation, inspect server.py for route conventions, authentication/session behavior, and any existing equivalent endpoints; reuse compatible routes rather than creating duplicates.

## Job claim response example

    {
      "job_id": "job_01J...",
      "project_id": "project_01J...",
      "scene_id": "scene_0001",
      "scene_index": 1,
      "scene_count": 100,
      "attempt": 1,
      "lease_expires_at": "2026-10-09T12:00:00Z",
      "prompt": "Mia rides a yellow scooter along the garden path",
      "continuity_prompt": "Preserve the same character identity, clothing, lighting and motion direction.",
      "duration_seconds": 5,
      "aspect_ratio": "9:16",
      "input_image": {
        "asset_id": "asset_start_001",
        "download_url": "short-lived trusted HTTPS URL",
        "sha256": "hex checksum",
        "content_type": "image/png"
      },
      "output_policy": {
        "video_format": "mp4",
        "extract_final_frame": true
      }
    }

Do not include raw image/video bytes, API keys, or local filesystem paths in the job JSON.

## Completion payload example

    {
      "job_id": "job_01J...",
      "scene_id": "scene_0001",
      "attempt": 1,
      "status": "completed",
      "video": {
        "asset_id": "asset_video_001",
        "sha256": "hex checksum",
        "size_bytes": 12345678,
        "duration_seconds": 5.02,
        "content_type": "video/mp4"
      },
      "final_frame": {
        "asset_id": "asset_frame_001",
        "sha256": "hex checksum",
        "size_bytes": 234567,
        "content_type": "image/png"
      },
      "validation": {
        "video_stream_found": true,
        "video_decodable": true,
        "final_frame_decodable": true
      }
    }

Only a successful completion transaction should make scene i+1 eligible. Completion must be idempotent for the same job_id + attempt and should reject stale leases.

## Event model

Event types: agent_online, agent_offline, job_claimed, generation_started, generation_progress, generation_finished, video_validation_passed, video_validation_failed, final_frame_extracted, asset_uploaded, retry_scheduled, job_completed, job_failed, job_cancelled, project_paused, project_resumed.

Each event includes event_id, timestamp, agent_id, project_id, scene_id, job_id, attempt, type, and a small sanitized payload. Progress may be numeric only if reported by the backend; otherwise report a stage label without inventing percentages or ETA.

## Asset transport

- Use authenticated upload or short-lived pre-signed URLs for large outputs; avoid JSON/base64 for MP4 transfer.
- Enforce per-file and per-project size limits, content-type allowlists, checksum verification and expiry.
- The agent must validate URL host and TLS; never follow arbitrary URLs supplied by scene prompts or backend output.
- The control plane must not expose local computer paths to the browser.
- Before implementation, choose durable storage. Render local disk is not assumed to survive deploy/restart. A task state must not point to a temporary URL after it expires.

## Failure and recovery

- Lease expiry makes a claimed job eligible for reclaim only after server-side state reconciliation.
- A late result from an expired attempt must not overwrite a newer successful attempt.
- Transient network errors use exponential backoff with jitter; generation errors use a configurable small retry cap.
- If a scene in continuity mode fails permanently, later scenes remain blocked until retry or explicit user decision to restart from a new anchor.
- Pause/cancel is authoritative at project level; the agent stops claiming new work and cancels the active backend job if supported.

## Security checklist

- Agent token authentication and revocation.
- One-time pairing code with short expiry and brute-force rate limits.
- Strict JSON schema validation and bounds on scene count, duration, prompt length, file size and accepted ratios.
- Host allowlist for downloads and uploads; SSRF protection.
- No secret material in logs or error payloads.
- Verify checksums and file types from file content, not only client-supplied MIME type.
- Do not permit the server to issue arbitrary shell commands; backend adapters are fixed and locally configured.
- Audit logs for pairing, claim, completion, retry, pause and cancellation.