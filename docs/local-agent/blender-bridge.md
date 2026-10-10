# Local Blender bridge (first milestone)

This is the first local automation milestone for the Mia 3D-animation workflow. It launches Blender on the user's Windows computer and creates a reusable stylized forest starter scene. It does **not** use cloud rendering, Agnes, or a paid service.

## What it currently does

- Launches the explicitly configured local Blender executable in background mode.
- Creates a simple low-poly forest environment, winding path, lighting and a vertical 9:16 camera.
- Saves `forest_starter.blend` and, unless disabled, renders `forest_preview.png`.
- Validates the project name, keeps output inside the configured workspace, uses a fixed built-in Python scene script, and does not execute arbitrary code from prompts or mailbox attachments. It refuses to replace its known output files unless `--overwrite` is explicitly supplied.
- Limits task execution time and checks Blender's exit code and output files.

## What it does not do yet

- It does not generate or rig Mia from a reference image.
- It does not provide a full scene timeline or a conversational interface by itself. The mailbox poller now recognizes the typed `blender_forest_preview` task, but every remote task still requires typing `YES` on the Windows computer.
- It does not yet integrate with `LocalProjectRunner` or export a finished animated MP4.
- The generated forest is a technical starter scene, not a final art-directed environment.

## Windows quick start

Use a Python environment where this repository's requirements are installed. Find the full path to Blender's executable, typically something like `C:\\Program Files\\Blender Foundation\\Blender 4.x\\blender.exe`.

PowerShell example:

```powershell
$env:BLENDER_EXECUTABLE = "C:\\Program Files\\Blender Foundation\\Blender 4.x\\blender.exe"
$env:LOCAL_AGENT_WORKSPACE = "D:\\AI-Studio\\MiaProjects"
python -m local_agent.blender_cli --project mia_forest
```

Expected outputs:

- `D:\\AI-Studio\\MiaProjects\\mia_forest\\forest_starter.blend`
- `D:\\AI-Studio\\MiaProjects\\mia_forest\\forest_preview.png`
- `D:\\AI-Studio\\MiaProjects\\mia_forest\\blender_result.json`

For a quicker file-generation smoke test without rendering:

```powershell
python -m local_agent.blender_cli --project mia_forest --no-render
```

## Safety and testing

- Use a dedicated project output directory. Do not point the workspace at a system folder or a directory containing unrelated files.
- Only the named task `forest-preview` is accepted; the bridge is not a general-purpose remote Python executor.
- Do not place tokens, private reference images, or generated character assets in the public project repository.
- Unit tests mock the Blender process; they verify validation and output handling but **do not prove** that Blender launches or renders correctly on Windows. A real local smoke test is still required.


If you intentionally want to regenerate the same project and replace the bridge's three known outputs, pass `--overwrite`. Without that flag, existing outputs are left untouched.


## Route a forest-preview request through the local agent

After the private mailbox exists and the local poller is configured, set these variables in the same PowerShell session:

```powershell
$env:BLENDER_EXECUTABLE = "C:\\Program Files\\Blender Foundation\\Blender 4.x\\blender.exe"
$env:LOCAL_AGENT_WORKSPACE = "D:\\AI-Studio\\MiaProjects"
$env:LOCAL_AGENT_GITHUB_REPO = "YOUR_GITHUB_LOGIN/local-agent-mailbox"
python -m local_agent.poller
```

The private mailbox manifest at `queue/desired_task.json` may contain this typed task:

```json
{
  "protocol_version": 1,
  "task_id": "mia-forest-preview-001",
  "operation": "blender_forest_preview",
  "created_at": "2026-10-09T10:00:00Z",
  "expires_at": "2026-10-09T10:10:00Z",
  "requires_local_approval": true,
  "arguments": {
    "project_name": "mia_forest",
    "render": true,
    "preview": true,
    "cycles": false
  }
}
```

Use current UTC timestamps when creating a real task. The example timestamps are illustrative and will expire. The protocol rejects arbitrary script/command/executable fields, invalid project names, unknown arguments, and tasks that do not require local approval. On the PC, the agent prints the task and waits for the user to type `YES`; otherwise it declines the task. Existing generated outputs are never replaced unless the local CLI is run with an explicit overwrite flag (the remote task does not expose that flag).
