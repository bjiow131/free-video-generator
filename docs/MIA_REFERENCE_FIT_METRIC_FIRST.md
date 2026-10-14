# Mia reference fitting: measurement-first core (research prototype)

Baseline: pinned release `33e572fb966e747bc444fc3c0475c0afac224d9f`. The production agent is **not** changed by this branch.

## Problem and direct evidence

Existing `blender_mia_source_polish` takes a few numerical scale/translation/brush edits proposed after viewing renders. Its allowed edits cannot create missing fringe/bun topology. Repeated image hashes prove files differ, **not** that the reference matches.

Agent completed two read-only donor inspections on 2026-10-14:

- Spring: 510 mesh objects, 74,485 vertices, core armature with 2,259 bones, 4,849 constraints, 1,704 drivers; donor SHA-256 `8005f5cedb70faccd5557e6b0b001662f8681436f761d1f83e64feb9e02f0502`.
- Tiby Female: 4 meshes, 1,750 vertices, 25-bone rig; donor SHA-256 `00ab9444a450773b779bbe40b5793d3b9397c0e836d4c321dbfae12b7549c541`.

Both were inspected without modifying source files. Numbers alone are not identity or rig quality acceptance.

## Planned solution

1. **Lock reference and views.** Verify approved reference SHA-256 and keep one canonical camera/lighting specification; forbid changing the camera to disguise geometry errors. Exclude black image margins.
2. **Measure before editing.** Image extraction module (NOT YET IMPLEMENTED) creates human-reviewable binary masks for silhouette, hair, eyes, face and garments, plus normalized 2D facial keypoints. Missing data is a blocker, not a score of zero.
3. **Optimize low-dimensional anatomical controls.** Before moving thousands of vertices, test 20–40 named controls (head width/depth, eye size/location, cheek volume, jaw, hairline, fringe curvature, bun volume/position, clothing silhouette). A parameter vector must connect to editable Blender mesh/Lattice/shape-key operations, with independent control of hair topology.
4. **Two-tier loop.** Cheap 256–512 px EEVEE preview for parameter search; a maximum of 10 expensive acceptance checkpoints, each saved as a distinct .blend. If score regresses or visual evidence repeats, rollback. At each checkpoint, re-open .blend and check deforming armature and facial shape keys.
5. **Objective score + independent visual gate.** `local_agent/mia_fit_metrics.py` is the preliminary no-dependency scoring/rollback core. It operates on *measured*, aligned masks and landmarks. It does not extract them, launch Blender, edit mesh data or claim visual acceptance.
6. **Topology stop condition.** If donor hair/eyes cannot express the approved profile, stop scaling and switch to licensed source geometry/curves. Preserve the donor rig or explicitly report re-rigging is needed.
7. **Security.** No external .blend autoexec; use `--disable-autoexec`; archive URL, licence and SHA-256 before importing. Separate experimental branch and local checkout; no main or installed agent update without tests.
8. **Definition of done.** Measurably improving face/front/profile/back views, non-duplicate actual geometry, preserved editable .blend + deformation smoke tests, and **user approval**. A score alone is never proof that this is Mia.

## Current verification

- Offline unit tests for metric and rollback behavior: 9 passed in an isolated Python environment on the coordinator side.
- Actual Windows execution of metric module: **NOT TESTED**.
- Pixel mask/keypoint extraction on approved Mia: **NOT IMPLEMENTED**.
- Automated parameter optimization and .blend editing: **NOT IMPLEMENTED**.
- Final Mia resemblance: **NOT APPROVED**.

## Sources

- Official Blender Lattice modifier: https://docs.blender.org/manual/en/4.0/modeling/modifiers/deform/lattice.html
- Official Blender Studio Spring: https://studio.blender.org/characters/spring/v1/
- Official Blender Studio Snow v4: https://studio.blender.org/characters/snow/v4/
- Open source differentiable renderer: https://github.com/NVlabs/nvdiffrast
- Stable Fast 3D: https://github.com/Stability-AI/stable-fast-3d
- Hunyuan 3D 2.1 resource requirements: https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
