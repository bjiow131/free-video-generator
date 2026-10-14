# Blender runtime workflow

## Available typed operations

- `blender_preflight`: locate Blender from the locally configured executable path or PATH and query its version. It does not create a scene.
- `blender_mia_blockout`: run a bundled, fixed Blender Python script to create an editable starter scene with a simple Mia figure, brown hair, teal outfit, yellow scooter, and snail companion. Save a `.blend` project and a PNG preview.
- `blender_open_mia_project`: open an existing generated Mia `.blend` project in the Blender GUI by launching Blender with the validated local file path; it does not click the Open dialog.
- `blender_inspect_mia_project`: open the saved project in background mode with Blender auto-execution disabled, then report object/mesh/camera/light/material counts, render settings, and missing image files. This is structural inspection, not visual-quality analysis.
- `blender_knowledge_search`: search the bundled read-only Blender knowledge base; results are guidance, not executable code.

## Output validation

The blockout operation checks that the manifest and non-empty `.blend` file exist, then validates the PNG preview's signature, chunk boundaries, CRC checksums, end marker, and expected 360×640 pixel dimensions. This catches many truncated or corrupted output files; it does not judge composition, character likeness, or visual quality.

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
6. Check that the result reports a validated preview, then open the `.blend` file and inspect the render manually before proceeding.


## Skeleton smoke-test prototype

- `blender_mia_skeleton` reads the existing `mia_blockout.blend` and writes a separate `mia_skeleton.blend` plus a result manifest.
- It creates a 13-bone armature and briefly rotates one forearm pose bone, then resets the pose before saving.
- The output is intentionally separate; existing files are never overwritten.
- **Important:** this stage only proves that Blender can create an armature and perform a basic pose update. The existing character meshes are not yet parented or weighted to the rig, so they will not deform with the bones. Skinning, joint placement refinement, and visual validation remain future work.
