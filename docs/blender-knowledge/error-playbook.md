# Blender Error Playbook

Use this playbook as a diagnostic sequence, not as permission to make speculative changes.

## First response to any failure
1. Preserve the input .blend and make a checkpoint before repair.
2. Capture Blender version, OS, exact task/template, exit code, elapsed time, and bounded stdout/stderr.
3. Read the traceback from the first relevant task-script frame to the final exception.
4. Classify the failure and reproduce on a copy or minimal scene.
5. Apply one narrow change at a time.
6. Re-run the smallest relevant check, then a preview render.
7. If the diagnosis remains uncertain, stop and escalate with sanitized logs.

## Common symptom → checks

### `ModuleNotFoundError` or `ImportError`
- Confirm which Python is running. Blender bundles its own Python; packages installed in the system Python may not be available inside Blender.
- Prefer Blender's bundled modules and documented API. Do not silently install packages or upgrade Blender dependencies.
- Verify exact Blender version and the import path.

### `AttributeError` for a `bpy` property or operator
- Suspect API differences or an incorrect object/context type.
- Check the official API docs for the installed version.
- Inspect the property on the actual datablock before changing code.
- Avoid guessing property names or changing unrelated parts of the scene.

### Operator poll/context failure
- Many `bpy.ops` operators depend on active object, mode, selection, editor context, or window context.
- Prefer direct data API operations when practical; otherwise set and validate the required context.
- Test in background mode separately if the task uses `blender.exe --background`.

### Object or material not found
- Check exact name, current scene, collection membership, linked/overridden data, and whether the operation ran twice.
- Search by stable identifiers or explicit collection, not by whichever object is selected.
- Never delete/recreate unrelated objects to make a missing-name error disappear.

### Rig deforms badly
- Verify armature modifier target, rest pose, transforms, vertex groups, weight normalization, and bone roll/parent relationships.
- Test standard joint poses. Correct the smallest affected region and compare against a saved baseline.
- Do not rebuild the rig as a first reaction.

### Pink or missing textures
- Check image datablock paths, whether resources are packed, file existence, node links, and color-space assumptions.
- Do not replace textures automatically without preserving originals.

### Black or empty render
- Verify active camera, camera clipping, object render visibility, light placement/energy, world nodes, render engine, frame number, and output path.
- Render a low-resolution preview before changing quality settings.

### Blender hangs or times out
- Distinguish slow rendering from deadlock/crash using logs, process state, elapsed time, and output growth.
- Use a bounded timeout and avoid starting duplicate Blender processes for the same task.
- Do not kill unrelated Blender sessions. If cancellation is required, target only the process started for this task.

### Invalid or missing output
- Check exit code, file existence, non-zero size, image header/dimensions, and whether the .blend reopens.
- A log message claiming success is not sufficient proof.

## Automatic-fix policy
The knowledge base currently recommends checks only. It does not authorize automatic repairs. A repair may be automated only after the operation has a bounded, reviewed procedure, a backup/checkpoint, a reproducible test, and a post-change validation. Data loss, credential issues, unknown exceptions, and project corruption require escalation.
