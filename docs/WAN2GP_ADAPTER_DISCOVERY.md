# Wan2GP adapter discovery

## Why this step exists

The local scene runner currently defines the correct orchestration contract, but it does not yet have a real Wan2GP backend. Wan2GP builds and Gradio API names/input ordering can vary by version and selected mode. Hard-coding a guessed endpoint would risk sending the initial image into the wrong control or silently using the wrong generation mode.

The helper `scripts/inspect_wan2gp_api.py` is a read-only first step. It queries Gradio metadata; it does not queue a generation, upload a file, or print component default values.

## When the Windows computer is available

1. Start the installed Wan2GP normally and select the image-to-video workflow that is available in that installation.
2. Find the local web address printed by Wan2GP in its console. The common Gradio default is `http://127.0.0.1:7860`, but use the actual address/port printed by the application.
3. From the repository root, run:

   ```powershell
   python scripts/inspect_wan2gp_api.py --url http://127.0.0.1:7860
   ```

4. Save the JSON output locally for adapter mapping. The report should show the available API names and each endpoint's input/output component labels/types.
5. Do not publish a live public tunnel for Wan2GP. Keep the UI/API bound to localhost; this inspector is intended for the same computer.

If `/config` returns 404 or the connection fails, use the exact local URL shown in Wan2GP's console. Do not infer that a particular API endpoint is supported from a successful page load alone.

## Adapter implementation gate

Implement the actual backend only after inspecting the installed version's metadata and confirming a single manual I2V generation. The adapter must then:

- choose the exact I2V API endpoint and bind prompt, initial image, duration, aspect ratio and any required model controls by verified component IDs/order;
- wait for the actual job completion and surface the full actionable error on failure;
- locate and copy the produced MP4 into the scene output path;
- avoid launching another job while the previous job is still running;
- preserve the runner's checkpoint/retry rules;
- be tested with a two-scene run, proving scene 2 receives the extracted last frame from scene 1.

## Current status

- Scene orchestration/checkpoint core: scaffolded on `feature/local-video-agent`.
- Read-only Wan2GP API inspector: added; not yet run against the user's installed application.
- Real Wan2GP generation adapter: **not implemented yet**, pending the installed app's actual API metadata.
- FFmpeg media adapter and real end-to-end validation: **not verified yet**.
- Nothing has been merged into `main` or deployed to Render.
