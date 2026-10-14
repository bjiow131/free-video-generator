# Blender agent skill roadmap

This roadmap defines how the local agent gains reliable Blender skills without fine-tuning a language model or executing arbitrary remote code.

## Operating model

The language model interprets a request and proposes a typed operation. The local agent validates the operation against an allowlist, obtains local approval, executes a fixed skill or a reviewed template, then validates actual artifacts. Prompts and mailbox JSON are data only; they never become Python source, shell commands, executable paths, or arbitrary Blender operators.

Each skill must declare:
- stable skill ID and version;
- accepted arguments with strict types and bounds;
- required local resources;
- fixed implementation entry point;
- expected output files;
- machine-checkable postconditions;
- known limitations and recovery steps;
- tests that do not require Blender, plus a real Blender smoke test when possible.

## Training stages

### Stage 0 — Reliable environment and evidence
- Locate the configured Blender executable and report its version.
- Create an isolated project directory.
- Save a minimal Blender project and a preview image.
- Validate exit status, output existence, file size, image dimensions, and result manifest.
- Keep logs bounded and redact secrets.

Exit criteria: a real Windows smoke test succeeds twice in a row without overwriting an existing project by default. Unit tests with mocked Blender are necessary but do not satisfy this criterion.

### Stage 1 — Scene-building primitives
Teach and test individual skills for creating named objects, collections, materials, lights, cameras, and ground/environment geometry. Each skill must be deterministic where practical and safe to rerun. Use named collections and stable object names so later skills can inspect or replace only their own outputs.

Exit criteria: a scene audit confirms required objects, material assignments, camera configuration, and render settings.

### Stage 2 — Visual inspection and repair
For every render, collect both machine-readable checks and an image preview. Detect technical failures first (blank/empty render, missing camera, invalid dimensions, missing expected objects). Visual quality judgments should be treated as suggestions until validated by a human or a separately tested vision evaluator. Store the failure reason and the correction that worked.

Exit criteria: a regression set of deliberately broken scenes is detected; repair does not damage unrelated objects or overwrite source projects.

### Stage 3 — Character asset intake
Import a user-provided character reference or an existing licensed model from a local path. Keep source references and generated assets in the private local workspace, never in the public source repository. Initially support reference planes and explicit model import; do not claim that one image automatically yields a production-ready, rigged 3D character.

Exit criteria: the scene records the source asset path, scale, orientation, and license/provenance note; the source asset remains unchanged.

### Stage 4 — Rigging and animation
Start with known rigged assets and reusable animation actions. Validate that the armature exists, required bones are present, actions have nonzero frame ranges, and the character stays within reasonable scene bounds. Automated rigging from a single reference is a separate research task and must not be assumed available.

Exit criteria: a short test animation renders correctly from a saved project and can be repeated on a second scene.

### Stage 5 — Shot assembly and final export
Add a typed shot plan: scene duration, camera, character action, environment, audio assets, and output format. Use local FFmpeg for assembly only after validating each intermediate artifact. Preserve checkpoints and never delete source files during cleanup.

Exit criteria: a short vertical MP4 is produced with expected dimensions, duration, audio state, and a complete report of input/output paths.

## Learning from failures

1. Record the operation ID, skill version, Blender version, arguments after redaction, error category, and validation result.
2. Reproduce the failure in a small isolated test scene.
3. Fix the skill implementation or add a narrowly scoped skill; do not patch behavior by appending untrusted instructions to a prompt.
4. Add a regression test for the exact failure.
5. Re-run the old regression set and confirm the fix.
6. Promote the skill version only after the tests pass; retain the previous version for rollback.

## Current status

Implemented in the repository: a fixed forest_preview task, a local Blender launcher, output checks, an approval-gated mailbox operation, and mocked unit tests.

Not yet proven: actual Blender execution/rendering on Windows, visual quality of the starter scene, reference-to-3D generation, automatic rigging, speech/audio integration, and final animated MP4 export. These require separate implementation and evidence.

## Safety gates

- Remote tasks require explicit local approval.
- The agent re-fetches the mailbox after approval and rejects a changed or expired task before execution.
- Remote task schemas cannot supply scripts, shell commands, URLs, or executable paths.
- Existing output files are not replaced unless the local operator explicitly opts in.
- Never commit access tokens, private reference images, character models, or generated media to the public repository.
