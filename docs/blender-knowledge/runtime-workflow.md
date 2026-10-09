# Blender runtime workflow

Two typed operations are available to the local agent:

- `blender_preflight` locates Blender from the locally configured executable path or PATH and queries its version. It does not create a scene.
- `blender_open_mia_project` opens an existing generated Mia `.blend` project in the Blender GUI by launching Blender with the validated local file path; it does not click the Open dialog.\n- `blender_mia_blockout` runs a bundled fixed Blender Python script to create an editable starter scene with a simple Mia figure, brown hair, teal outfit, yellow scooter, and snail companion. It saves a `.blend` project and a PNG preview, then validates the outputs.

## Limits and safety

- Task arguments are validated data, not source code. Arbitrary scripts and shell commands are not accepted.
- Outputs stay under `LOCAL_AGENT_WORKSPACE` in a named project folder.
- Existing outputs are not overwritten automatically.
- Blender is launched in background mode through its Python API; the agent does not need to click the GUI Open button for this workflow.
- The blockout is only a rough starting model. It is not production topology, a rigged character, or an animation.
- The workflow has not yet been verified on the user's Windows computer. Mocked tests do not prove that Blender itself renders correctly.
- GUI automation, screenshot interpretation, rigging, animation, and automatic model repair remain future work.

## First computer-side check

1. Install Blender from its official website.
2. Set `BLENDER_EXECUTABLE` to the full path of `blender.exe`.
3. Set `LOCAL_AGENT_WORKSPACE` to a dedicated output folder.
4. Run `blender_preflight`.
5. If Blender is ready, run `blender_mia_blockout` with a new project name, for example `mia_character_v001`.
6. Open the resulting `.blend` file and inspect the render before proceeding.
