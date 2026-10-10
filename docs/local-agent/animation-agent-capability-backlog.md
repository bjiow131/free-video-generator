# Local animation agent — capability backlog

This backlog extends the Blender skill roadmap into a practical, local-first animation production assistant. It is a design plan, not a claim that these capabilities already work.

## Priority 0 — Reliability and project safety

### A. Project manager
- Create projects from a fixed folder template: references, assets, scenes, audio, renders, exports, reports.
- Maintain a project manifest with scene IDs, asset paths, versions, status, and validation results.
- Never modify source references; create versioned outputs and checkpoints.
- Resume after a restart by reading the manifest and checking actual files rather than trusting memory alone.

### B. Task planner and queue
- Turn a Russian-language request into a structured plan with bounded operations, dependencies, estimated steps, and acceptance checks.
- Show a dry-run summary before execution.
- Allow cancellation, pause/resume, retry of safe steps, and explicit approval for destructive or costly operations.
- Mark old tasks as superseded and re-check task identity, content, and expiry immediately before execution.

### C. Diagnostics and recovery
- Check Blender path/version, available disk space, output folder permissions, required local tools, and missing assets before starting.
- Classify errors into environment, input, scene, render, and export categories.
- Offer a repair plan and run only allowlisted repair skills.
- Produce a short human-readable report plus a machine-readable JSON report.

## Priority 1 — Scene and visual workflow

### D. Scene builder
- Typed skills for collections, geometry, materials, lights, cameras, world/background, and render settings.
- Use stable object names and ownership collections to make skills safe to rerun.
- Include a scene audit that checks required objects and camera/render settings before rendering.

### E. Preview and quality gate
- Render low-cost previews before final quality renders.
- Check image dimensions, blank frames, missing camera, missing expected objects, clipping, and render completion.
- Present preview paths and clear pass/fail reasons.
- Never treat successful process exit as proof of visual quality; use visual review for composition and character likeness.

### F. Character continuity
- Keep a character bible per character: reference paths, proportions, palette, clothing, scale, voice notes, and forbidden changes.
- Record approved model versions and animation actions.
- Compare rendered shots against approved references where possible, while reporting uncertainty rather than inventing a likeness score.
- Keep private character references and model assets outside the public Git repository.

## Immediate next milestone — Camera control (before multi-scene timeline)

The first implementation should improve an already-openable/saved scene rather than redesign the application or build the timeline first.

### Camera control adapter — planned, not implemented yet

- Operate only on an existing, validated local `.blend` project inside the configured workspace. Never accept script text, executable paths, arbitrary object names, or output paths from a remote task.
- Provide a small typed preset set: `establishing_wide`, `medium_shot`, `close_up`, `portrait_vertical`, `low_angle`, and `high_angle`. Each preset defines a bounded camera distance, target height, lens range, and safe framing behavior.
- Add bounded shot moves: `static`, `push_in`, `pull_out`, `pan_left`, `pan_right`, and `orbit`. Movement is represented as Blender camera keyframes over a validated frame range; no arbitrary Python or expressions.
- Prefer a dedicated camera target/empty and named camera object. If the scene has no active camera, report a blocker unless a safe preset is explicitly allowed to create one. Do not silently overwrite an existing camera's animation.
- Preserve the source `.blend`: write a versioned copy and preview to a new output path; refuse collisions rather than deleting approved work. Record camera parameters, frame range, output paths, and validation results in a JSON report.
- Run structural checks before rendering: active camera exists, lens and transforms are finite/in bounds, keyframes fit the scene range, render resolution remains unchanged unless explicitly requested, and the output file is non-empty. Render a low-cost preview for visual review.
- Add unit tests for schema rejection, traversal/collision protection, existing-animation preservation, valid keyframe bounds, missing-camera blockers, and mocked Blender subprocess failures. Then perform a real Blender smoke test on Windows before calling this feature complete.

### Acceptance gate

1. A camera-only change can be applied to an existing project without rebuilding its geometry or character assets.
2. The original project remains untouched and a new versioned project/preview/report are produced.
3. Tests pass; the Blender smoke test and manual preview review are recorded separately. Mocked tests alone do not establish rendering correctness.
4. Only after this adapter works should `camera_push_in` and `camera_pan` in `story_plan.json` be upgraded from planning-only to executable actions. The multi-scene timeline follows after camera behavior is reliable.

## Priority 2 — Animation production

### G. Shot and storyboard planner
- Convert a short script into numbered shots with duration, camera, action, location, dialogue, and transition.
- Validate that total shot duration matches target runtime.
- Reuse environments and character assets instead of recreating them for each shot.
- Keep script changes versioned and show a diff before replacing approved shots.

### H. Animation and rigging
- Begin with known rigged models and reusable animation actions.
- Validate armature, required bones, action ranges, and scene bounds.
- Provide a small library of tested actions: idle, walk, turn, point, wave, sit, and simple prop interaction.
- Treat automatic rigging from one still image as a separate experimental capability, not a guaranteed feature.

### I. Audio and final assembly
- Keep dialogue, music, ambience, and effects as separate tracks/assets.
- Validate audio duration, clipping where measurable, sample rate, and synchronization against shot timing.
- Use local FFmpeg for assembly when installed and licensed appropriately.
- Verify final MP4 dimensions, duration, video codec, audio presence, and file integrity.

## Priority 3 — Learning and maintenance

### J. Versioned skill library
Each skill has an ID, version, schema, implementation, postconditions, tests, and recovery guidance. Keep stable skills separate from project-specific data.

### K. Failure memory with regression tests
Store only useful, redacted facts: operation, software version, error category, diagnosis, fix, and test. A failure is not considered “learned from” until a regression test captures it and passes.

### L. Capability registry
At startup, report installed tools and actual availability: Blender, FFmpeg, disk space, supported import/export formats, and optional local models. Do not offer a capability as available unless a check confirms it.

### M. Human control and audit trail
- Show what the agent intends to change.
- Keep an append-only operation log with timestamps and outcomes.
- Require confirmation before deleting files, overwriting approved assets, changing project-wide character references, or installing software.
- Never allow mailbox content to supply arbitrary code, shell commands, or executable paths.

## Recommended implementation order

1. Project manifest and workspace layout.
2. Environment preflight and structured diagnostics.
3. Dry-run plan and task state tracking.
4. Scene audit and preview validation.
5. Character asset intake and continuity bible.
6. Storyboard/shot manifest.
7. Reusable animation actions.
8. Audio and MP4 export validation.
9. Improve repair automation based on real test failures.

## Acceptance rule

A feature is not “done” merely because its code exists. It is done only after unit tests pass, a documented manual/smoke test passes when the feature depends on Blender or Windows, output artifacts are validated, and limitations are documented.
