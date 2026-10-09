# Wan2GP adapter discovery

## Public integration surface verified

The current upstream repository documents a Python integration API in [docs/API.md](https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/API.md), including:

- `init(...)` to create a reusable `WanGPSession`;
- `WanGPSession.submit_task(settings, callbacks=None)` for a single task;
- `submit_manifest(...)` for batch tasks;
- a returned `SessionJob` whose result can be awaited/read through its documented job interface;
- settings dictionaries, including fields such as `model_type`, `prompt`, `resolution`, `video_length`, and mode-specific media fields.

This is a stronger candidate than guessed Gradio REST input ordering. Prefer the documented in-process Python API if the installed copy exposes the same API and its Python environment can import Wan2GP without conflicting dependencies. Do not import or initialize its GPU runtime from the Render service.

Upstream docs also describe a Gradio launch via `python wgp.py`, with `--server-port` and `--server-name` options; `--listen` is for network exposure and must not be enabled for this local-only MVP. The CLI reference states that generation can continue with browser windows closed.

Sources:
- [Wan2GP API documentation](https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/API.md)
- [Wan2GP CLI documentation](https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/CLI.md)
- [Wan2GP settings reference](https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/SETTINGS.md)

## What remains unverified

Public upstream documentation is not proof that the user's installed version matches the current `main` branch. We have not verified the installed commit, package imports, available model IDs, I2V field names, supported durations, frame-rate behavior, or returned output artifact paths on the target Windows computer. The docs' examples are model-specific; do not assume one `model_type` or parameter set works with every model.

The real adapter must not be written against a guessed configuration. When the computer is available:

1. Start the installed Wan2GP normally, without `--listen` or `--share`.
2. Record the version/commit printed by its repository and the Python executable/environment used to launch it.
3. Run the read-only inspector against the actual local URL:
   ```powershell
   python scripts/inspect_wan2gp_api.py --url http://127.0.0.1:7860
   ```
4. Confirm one manual image-to-video generation and inspect the resulting local output location.
5. Check whether the installed source includes the documented Python API. If yes, prefer a thin adapter that calls `submit_task` and reads the returned job/artifact fields; if not, map the local Gradio metadata and use only the verified endpoint contract.

Do not upload the inspector output publicly if it contains private local directory names. The inspector is read-only and must never submit generation requests.

## Adapter acceptance gate

- Confirm model and input-image fields against installed source/docs.
- Confirm prompt, duration/frame count, resolution and aspect-ratio representation.
- Wait for job completion and preserve actionable failure details.
- Discover the produced MP4 through the documented result/artifact contract, not by guessing a newest file in a directory.
- Ensure no duplicate job is submitted while a previous scene is active.
- Prove a two-scene chain: scene 2 must receive the validated extracted final frame of scene 1.
- Keep Wan2GP bound to loopback; no public tunnel.

## Current status

- Orchestration core: scaffolded; real inference remains unverified.
- Read-only Gradio inspector: present; not yet run against the user's installed version.
- Public upstream Python API: documented and researched; compatibility with installed version is unknown.
- FFmpeg adapter: added on `feature/local-video-agent`; subprocess behavior has mock-based tests authored, but tests have not been executed in this environment.
- Real FFmpeg media validation and end-to-end generation: not executed.
- No changes merged to `main`; no Render deployment.


## Local proof-of-concept handoff

Before adapter implementation, the Windows machine must provide the installed Wan2GP repository revision and the Python environment used to launch it. Do not install or run Wan2GP inside the hosted Render process.

Once Windows is available:

1. From the existing Wan2GP installation directory, capture the commit/version with `git rev-parse HEAD` (if it is a Git checkout) and the launch command currently used.
2. Start Wan2GP without public-listen/share options. Keep its interface bound to loopback.
3. From the agent repository's Python environment, run `python scripts/inspect_wan2gp_api.py --url http://127.0.0.1:7860` only after confirming the actual port from the local startup output.
4. Save the inspector's text output locally and provide only the relevant endpoint names, component types/labels and version details. Redact personal directory names if necessary; do not send credentials or tokens.
5. Manually generate one short I2V clip and confirm where Wan2GP reports the resulting MP4. This verifies the installed build's actual output behavior.
6. Only after these observations, implement a thin adapter and run the two-scene test: scene 2's input must be the validated final frame extracted from scene 1.

Do not add a local HTTP service or Render pairing before this local two-scene proof succeeds. The runner's new lock and example manifests are still unexecuted code and are not evidence of end-to-end readiness.
