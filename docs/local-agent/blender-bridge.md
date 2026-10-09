# Local Blender bridge (first milestone)

This is the first local automation milestone for the Mia 3D-animation workflow. It launches Blender on the user's Windows computer and creates a reusable stylized forest starter scene. It does **not** use cloud rendering, Agnes, or a paid service.

## What it currently does

- Launches the explicitly configured local Blender executable in background mode.
- Creates a simple low-poly forest environment, winding path, lighting and a vertical 9:16 camera.
- Saves `forest_starter.blend` and, unless disabled, renders `forest_preview.png`.
- Validates the project name, keeps output inside the configured workspace, uses a fixed built-in Python scene script, and does not execute arbitrary code from prompts or mailbox attachments.
- Limits task execution time and checks Blender's exit code and output files.

## What it does not do yet

- It does not generate or rig Mia from a reference image.
- It does not provide a conversational interface, automatic mailbox polling, or a full scene timeline.
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
