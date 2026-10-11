# Camera stabilization release gate

Scope: one consolidated update for the local Blender 5.2 multiscene renderer, without changes to main or GUI workflow.

Acceptance criteria:
1. Check evaluated subject mesh surface visibility and camera framing for every output frame.
2. Generate candidate camera paths for the whole timeline; optimize smoothness across frames instead of selecting the first acceptable offset independently at each frame.
3. Validate collisions, camera-subject separation, occlusion, and composition after keyframe baking.
4. Explicitly fail with actionable diagnostics when no valid path exists; do not claim success on partial visibility.
5. Add automated fixtures: static target, crossing occluder, moving target, narrow corridor, no feasible view, near-camera target, multiple objects, and abrupt target direction change.
6. Run syntax/unit tests on the project, Blender 5.2 headless integration tests on available fixtures, and inspect rendered frames for visible occlusion.
7. Preserve current GUI, CLI arguments, MP4 output contract and existing working installation. Deliver one consolidated update only after tests pass.

Current state: evaluated-mesh surface sampling implemented in multiscene_cli.py; trajectory optimization, full fixtures, and Windows Blender acceptance testing are outstanding.
