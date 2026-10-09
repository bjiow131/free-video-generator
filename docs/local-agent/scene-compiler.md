# Scene compiler milestone

The scene compiler turns a validated `story_plan.json` into `storyboard_compile.json`, a structured and inspectable scene manifest. It does not execute text, call Blender, or claim to create animation.

## What it records

- Scene order, timing, locations, action and camera briefs.
- Dialogue, sound notes, asset references and typed action steps.
- Explicit readiness blockers. Character actions require a rigged character and an animation adapter; camera moves require a camera-animation adapter; named assets require an asset registry.
- A clear `planning_only` readiness state until those dependencies exist.

## Local mailbox operation

`compile_story_plan` accepts only a validated project name. The local agent reads the already-saved plan from its configured workspace, validates it again, and writes `storyboard_compile.json` without overwriting an existing file. The task requires local approval, uses no remote file path, and never launches Blender.

## Next implementation steps

1. Create a local asset registry for approved character models, props and locations.
2. Add Blender scene-blockout generation from a fixed set of typed operations.
3. Add preview validation and report missing assets/actions before attempting animation.
4. Add rig-aware character motion and camera keyframes only after the needed assets are present.
