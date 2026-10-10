# Workflow for the persistent character project (Mia)

## Goal
Maintain a consistent, reusable 3D character and build repeatable scenes and animations around that character. The reference images and approved proportions are the source of truth; generated previews do not silently replace them.

## Stage 0 — Project setup
- Record the installed Blender version and render engine availability.
- Create a clear project structure for references, blend files, previews, textures, animation exports, and logs.
- Keep approved reference images and notes read-only; use copies for experiments.
- Save a baseline .blend file and a separate checkpoint before structural changes.

## Stage 1 — Character blockout
- Match the silhouette and proportions before fine detail.
- Review front, side, and three-quarter views under neutral lighting.
- Keep a short written proportion sheet: overall height, head-to-body ratio, limb lengths, eye spacing, and distinguishing features.
- Do not proceed to rigging until the shape is approved against references.

## Stage 2 — Mesh and materials
- Use stable object names and collections for body, head, eyes, hair, clothing, and accessories where appropriate.
- Keep a named material palette; avoid creating duplicates on every rerun.
- Check normals, transforms, modifier order, material slots, and shader links.
- Render a small preview under the intended lighting.

## Stage 3 — Rigging
- Decide the rest pose and bone naming before building animation.
- Separate deformation from control bones when the rig requires it.
- Test automatic weights, then inspect shoulders, elbows, wrists, hips, knees, ankles, and neck.
- Preserve a pre-rig checkpoint. Structural rig edits can break actions and constraints.

## Stage 4 — Animation
- Specify action name, frame range, frame rate, and whether it loops.
- Start with simple repeatable actions (idle, walk, turn, reach, pick up an object).
- Check contact points, balance, foot sliding, intersections, and silhouette at key poses.
- Review at normal speed as well as by scrubbing individual frames.

## Stage 5 — Scene assembly
- Use separate collections for character, environment, props, lights, and cameras.
- Set the active camera explicitly; check the composition in the target aspect ratio.
- For vertical story content, set the final aspect ratio early so framing is not an afterthought.
- Use preview rendering to validate lighting, clipping, exposure, and object visibility.

## Stage 6 — Delivery and verification
- Save a new version rather than overwriting the last known-good project.
- Verify the .blend file exists and has non-zero size; reopen it when possible.
- Verify preview image signature, dimensions, and that it visually contains the expected scene.
- Store task ID, Blender version, script/template version, output paths, warnings, and test results in the report.
- Mark the task complete only when the defined checks pass. Otherwise report partial completion and the exact blocker.

## Definition of done for a task
Every task should state: expected changes, files allowed to change, output files, validation checks, timeout, and rollback point. Do not accept "script ran" as equivalent to "3D result is correct".
