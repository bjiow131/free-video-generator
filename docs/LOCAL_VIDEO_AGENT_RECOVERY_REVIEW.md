# Local Video Agent — Recovery and Path-Boundary Review

Review date: 2026-10-09. This is a code-review note, not a claim that tests passed.

## Confirmed design observations

- Checkpoints store each scene's input-frame SHA-256 and output hashes. Resume can detect when a regenerated upstream scene changes the input for a later scene.
- Scene generation is sequential; the next scene receives the previous scene's extracted final frame.
- The runner uses an OS-managed non-blocking lock: `fcntl.flock` on POSIX and `msvcrt.locking` on Windows.
- Checkpoint writes use a unique temporary file, flush/fsync, and atomic replacement.
- The media adapter refuses incompatible stream-copy concatenation instead of silently transcoding.

## Required before local MVP

1. **Bind the checkpoint store to the runner workspace.** The runner should reject a `CheckpointStore` whose resolved root is not exactly the workspace's project directory for the manifest's `project_id`. This prevents mismatched injected dependencies from writing project state outside the configured workspace.
2. **Contain every generated and resumed media path.** Before probing, hashing, frame extraction or assembly, resolve saved video/frame paths and backend-returned paths and require them to remain inside the project's output directory. A checkpoint is local data and must not be treated as trusted path authority.
3. **Exercise lock behavior on both operating systems.** Run a two-owner exclusion test on Windows and POSIX, and verify lock release after process termination. The persistent lock file is not itself evidence that a process owns the lock.
4. **Exercise crash windows.** Test termination after backend output creation, after frame extraction, after scene checkpoint update and during final assembly. Recovery must never join downstream clips from a stale input-frame chain.
5. **Verify real media semantics.** Use actual FFmpeg/ffprobe and short clips with/without audio. Check final-frame extraction, duration tolerances, stream compatibility, and concat list escaping on Windows paths.
6. **Run CI and report actual outcomes.** Until GitHub Actions returns a result or a local runtime executes the suite, all tests remain unverified.

## Current scope boundary

No Wan2GP adapter, local HTTP control service, Render-to-Windows pairing, public LAN exposure or deployment is justified yet. First inspect the exact installed application/API and prove the two-scene workflow on the Windows PC.
