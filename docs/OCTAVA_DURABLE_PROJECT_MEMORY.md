# OctavAPI: project memory independent of API keys

Branch: `feature/octava-durable-memory-20261012` (not deployed automatically).

## Behavior

- No local project session is created by legacy `octava_advice` calls containing only `prompt`.
- For a durable project, submit `{"prompt":"...", "project_id":"mia"}`. The project ID is 1–48 letters, digits, underscores or hyphens.
- Before contacting OctavAPI, the agent atomically saves the pending prompt in `LOCAL_AGENT_WORKSPACE/.local_agent/ai_project_memory/mia.json`.
- A completed response is first archived to `mia.history.jsonl`, then placed in the compact project snapshot. The snapshot keeps 8 recent turns and 40 milestone summaries; the archive keeps every *newly recorded* completed response and milestone indefinitely until the user deletes it.
- On HTTP 401/402/403, the pending request becomes `waiting_for_key`; on HTTP 429/network failure it becomes `retry_later`. Neither error clears the saved context.
- Key replacement via `Настройки → OctavAPI → Проверить и сохранить` does not overwrite memory. If the Studio's local unattended OctavAPI permission is enabled, a successful rotation starts a bounded, best-effort background replay of up to 3 `waiting_for_key` projects. The Studio and poller must use the same Windows user and workspace. This is *advice only*, never a Blender command or executable patch.
- Manual mailbox recovery works irrespective of background replay: `{"project_id":"mia","resume_pending":true}` as arguments of `octava_advice`. Use a new task ID with valid timestamps. If no pending request exists, the operation refuses to invent one.
- A new request in the same project is blocked until a pending request is recovered; old progress cannot be overwritten by accident.
- Existing OctavAPI API keys remain only in Windows Credential Manager (or the legacy opt-in environment fallback). No key is stored in the project snapshot or archive.

## Privacy, limits, and safety

- The model receives *only* the current prompt, up to 4 preceding question/answer pairs, and the latest milestone statuses. Images, logs, arbitrary files, executable commands and the archive are **not** sent automatically.
- Approved question/answer text is transmitted to the external provider for continuity. Do not put secrets or confidential material in prompts. Local checkpoints also contain user-supplied prompt text and model output; protect your Windows profile and backup drive.
- This is memory for text advice, not yet autonomous execution of Blender tasks. `checkpoint_step(...)` is available to future vetted executors, but a successful render must be independently verified before recording a `completed` milestone.
- An interrupted response cannot be reconstructed byte-for-byte; after a crash, the **pending question** is replayed and may be billed again. There is no exactly-once guarantee across the external network.
- A prompt from a previous key that ran *before this feature was deployed* is not retroactively imported into the new memory archive. Existing GitHub mailbox history is separate.
- Changing the model or provider may change its answers; project memory preserves the available context but not hidden internal model state.
- Key-rotation auto-replay is best effort. It does not rewrite earlier GitHub mailbox results; newer completed answers remain in the Windows project archive.
- On unrecoverable memory corruption, the file is preserved and execution stops rather than silently starting empty.

## Offline tests (Windows Python 3.11)

```powershell
cd C:\AI-Agent-Studio-Octava
py -3.11 -m compileall -q local_agent
py -3.11 -m unittest discover -s tests -p "test_octava_*.py" -v
```

Deploy from a reviewed / tested branch with backup and rollback. Run a live Windows smoke test: successful project advice, force mocked 402 or a known exhausted key, inspect pending status, rotate key through Studio, verify the history archive and subsequent response. Never send keys to the GitHub mailbox.
