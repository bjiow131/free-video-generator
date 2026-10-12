# Telegram media delivery — staged integration (2026-10-12)

This is a **draft implementation**, not a verified Windows installation.

## User flow

The private paired Telegram chat supports:

- `/preview`: exact last rendered PNG frame of the most recent completed **Studio scene** (not a synthesized preview).
- `/video`: MP4 for the latest completed Studio scene or montage.
- `/reference`: Mia's currently saved reference image from the **local Studio character card**.
- `/help`: shows the commands.

Once a Studio scene finishes, automatic Telegram alerts (when enabled) also send the final frame. Explicit commands still work when automatic alerts are switched off. The files stay on Windows; bytes are transmitted by HTTPS to the chosen Telegram path. The relay forwards bytes in memory and does not write media to a shared cloud storage volume.

## Supported sources and limits

- Studio workspace: `LOCAL_AGENT_WORKSPACE`, defaulting to `~/BlenderAgentWorkspace`.
- Project ID: `mia_story`; jobs under `studio_jobs/<validated 32-hex job id>/`.
- Frame: `frames/frame_NNNN.png` where N is the completed job's `total_frames`.
- Videos: `scene.mp4`, up to 32 MB.
- Studio reference: `studio_media/<validated generated image id>`, up to 9.5 MB.
- No arbitrary Telegram filenames, remote URLs, shell commands, or paths.
- Chat and sender IDs must match the already-paired private Telegram chat.

## Transport

Direct mode: files are uploaded to Telegram Bot API as multipart/form-data.

Relay mode: the Windows client sends raw bytes to the fixed Render HTTPS endpoint
`/api/telegram/media` with fixed headers; the Render process validates content
and forwards multipart/form-data to Telegram. Render is a third-party processor
and temporarily receives the bot token and media bytes in RAM. No persistent
storage is implemented, but network availability and Render size/bandwidth
limits are not yet verified.

Before deploying the Render media endpoint, set the Render environment variable
`TELEGRAM_RELAY_TOKEN_SHA256` to the SHA-256 hex fingerprint of the **paired
BotFather token** (never the raw token). Until the fingerprint is present,
the relay refuses media uploads with HTTP 503. After configuration, both text
requests and media requests from other bot tokens are rejected. This allows
remote delivery without exposing the bot token in GitHub or the setup transcript.

The **currently deployed** Render service tracks branch
`feature/octava-agent-bridge-20261011` and has auto-deploy disabled.
This feature-branch change by itself does NOT update the live relay.
Update the relay source on its tracked branch and explicitly deploy it only
after review; ensure `getUpdates` with offset and allowed_updates works.
Do not change main or reconfigure production AI services.

## Acceptance on Windows

1. Deploy tested relay support and verify the relay /health and /health/upstream responses.
2. Deliver the client changes using the existing trusted updater (check its allowlist and SHA pins).
3. Confirm a private /help, /reference, /preview and /video request.
4. Check an automatic preview after one successful Studio render.
5. Test media with relay on (no VPN) and direct mode only when Telegram is reachable.
6. Test disabled notifications, absent reference, missing render, and invalid file.
7. Record delivery and any HTTP errors without logging token, image bytes or remote URL containing the token.

**Not yet covered:** arbitrary mailbox-produced media outside the Studio project,
or forwarding complete reference libraries. Add after their output manifests are
confirmed rather than guessing local paths.
