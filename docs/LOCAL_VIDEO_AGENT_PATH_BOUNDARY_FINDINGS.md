# Path Boundary Findings — Local Video Agent

Review date: 2026-10-09. These are static code-review findings; no exploit or runtime failure has been demonstrated.

## High-priority follow-up

1. **Checkpoint-store binding:** `LocalProjectRunner.run()` accepts an injected `CheckpointStore` without confirming its resolved root matches `workspace / manifest.project_id`. Production wiring should reject mismatches before acquiring the lock or touching state.
2. **Persisted media paths:** completed scene paths are loaded from checkpoint state. Resolve both saved video and saved frame paths and require them to remain under the project's output directory before probing, hashing or concatenating.
3. **Backend return path:** after generation, require the backend-returned video path to resolve under the project's output directory before validation and assembly.
4. **Extracted frame path:** require the media adapter's returned frame path to resolve under the project's output directory before recording it as the next scene's reference.

The initial reference image is a separate input and may intentionally be outside the project directory; it should be validated as an explicit user-supplied input rather than accidentally subjected to the generated-output path rule.

## Verification requirements

- Add regression tests for mismatched checkpoint stores, a checkpoint with output paths pointing outside the workspace, and a backend returning a path outside the project directory.
- Run the full test suite on GitHub Actions and on Windows.
- Confirm the lock behavior with two separate processes, not only two calls in one process.

No local HTTP service, Render pairing or public exposure should be added until these boundaries are enforced and tested.
