# Hunyuan3D character workflow

## Scope

This route creates a fresh static shape candidate from an original three-view turnaround. A generated GLB or a successful bone count is not a finished, polished or rigged character. Check appearance and geometry separately.

## Existing Windows authorization

- Keep `requires_local_approval: true` in every task envelope.
- `hunyuan3d_mv_character` belongs to `BLENDER_OPERATIONS` and follows the existing locally saved `enabled` and `allow_blender` settings.
- Do not change local consent files remotely or assume an absent result means an interactive prompt. With unattended mode enabled, unsupported operations return a blocked result.

## Install and verify

Use the opted-in pinned updater, `queue/desired_update.json`, with an immutable source commit from this repository and SHA-256 hashes of the exact UTF-8 file bytes. Calculate hashes with Python `hashlib.sha256(path.read_bytes())`; verify Git blob identities against the API's returned blob SHA if transferring source through tools. Do not implement hashing ad hoc.

Read `queue/results/update-<update_id>.json`. A separate `trusted_update_diagnostics` task only verifies the updater test suite; it does not prove that a proposed update was installed. Successful code updates return `status: completed`, `files_updated`, `source_commit` and `restart_needed: true`; the supervisor then reloads the worker.

## Generation task

Operation: `hunyuan3d_mv_character`.

Arguments:

```json
{"character_name":"Tavi","reference_base64":"<JPEG bytes encoded as base64>","reference_sha256":"<SHA-256 of JPEG bytes>"}
```

The turnaround is a 710x1536 JPEG with front/profile/back in three equal columns, at most 35000 bytes. The full envelope must remain below 65536 bytes. Use a unique task ID and a realistic expiry (no more than 24 hours). The handler validates the name, payload hash, local Blender consent, paths, free disk and GPU VRAM.

Tooling: `C:\AI-Agent-Workspace\_Hunyuan3D2mv_tooling`.

Output: `C:\AI-Agent-Workspace\CHARACTER_REFERENCE_REVIEW\<lowercase-name>_HY3DMV_<task-id>`.

Official source: Tencent-Hunyuan/Hunyuan3D-2 commit `f8db63096c8282cb27354314d896feba5ba6ff8a`. Model: tencent/Hunyuan3D-2mv revision `3a761b539b29fe4ff64714813aa9560fd66f5de0`. Run locally with the prepared isolated environment. The shape extractor imports `skimage` even though that dependency is commented in upstream requirements; install `scikit-image==0.24.0`. Check the pipeline import before inference. Compile all generated Python scripts before deployment. Blender 5.2 uses `BLENDER_EEVEE`; choose an available engine at runtime. Set the inference subprocess PYTHONPATH to the pinned source directory.

## Observe without interrupting

Read `queue/results/<generation-task-id>.json`. The current handler publishes the final report, not per-stage progress. Absence of that file does not prove a start, a hang, an approval prompt, a disconnection or success.

The task-control worker treats a changed desired manifest as a request to supersede active work. Do not replace an active generation with status, logs or review tasks merely to observe it. Wait for the result unless the user requests interruption.

## Review after generation

A prepared review extension uses the same operation and reference arguments with one extra field:

```json
{"review_generation_task_id":"<completed generation task ID>"}
```

Give the review its own unique envelope task ID. It reads only the matching generated folder, verifies the stored reference hash, checks paths, reopens the .blend with auto-execution disabled and network offline, reports Blender version/mesh/material/shape-key/armature counts and nonfinite geometry, and exports a bounded JPEG contact sheet to `queue/artifacts/<review-task-id>/review.jpg` in the configured private mailbox. The original candidate is not saved over. Verify its installed update before dispatching review. Appearance remains unverified until the images have actually been inspected.

## Tavi checkpoint — 2026-10-15

- Original character: coral axolotl courier, light muzzle/belly, teal vest and dark shoulder bag.
- JPEG SHA-256: `a61e30dac00b2601f88b960f1a3d618a24b705dfe3595dd250b518a291abb768`; 23478 bytes.
- Update `tavi-hunyuan-handler-20261015-01` failed: wrong SHA-256 digests. It did not install the proposed handler.
- Update `tavi-hunyuan-handler-20261015-02` completed on Windows, 3 files, source `5e22f66c99b06f6749c08ad1320e93247c17e8b7`.
- Generation `tavi-hunyuan3d2mv-20261015-01` ran automatically, prepared the views, then returned incomplete with missing `skimage`.
- Dependency update `tavi-hunyuan-dependencies-20261015-03` completed on Windows, source `9e0d8143a1f440c7b7a04baeaa2451019fca6959`.
- Retry `tavi-hunyuan3d2mv-20261015-02` is the current desired task; no result was available at this checkpoint. Do not duplicate it or claim the mesh exists.
- Review extension `ff5bb4eb08cc43d063b840d51d8b1a1a92edba61` is committed, syntax checked, and queued as update `tavi-hunyuan-review-20261015-04`. Installation/reopen/render checks remain pending.
