# Mia reference fitting: measurement-first core

Baseline: pinned release `33e572fb966e747bc444fc3c0475c0afac224d9f`. Work remains on experimental branches. No production `main) or installed-agent update is included here. DINOv3 is excluded; its access request was denied.

## Why the previous loop was insufficient

The older `blender_mia_source_polish` workflow offered a small set of scale, translation, and brush edits. Those operations cannot add missing fringe or bun topology. Different file hashes prove that files changed, not that Mia's appearance improved.

Read-only donor inspections reported:

- Spring: 510 mesh objects, 74,485 vertices, a core armature with 2,259 bones, 4,849 constraints, and 1,704 drivers; donor SHA-256 `8005f5cedb70faccd5557e6b0b001662f8681436f761d1f83e64feb9e02f0502`.
- Tiby Female: 4 meshes, 1,750 vertices, and a 25-bone rig; donor SHA-256 `00ab9444a450773b779bbe40b5793d3b9397c0e836d4c321dbfae12b7549c541`.

These counts do not establish visual identity or animation quality. They are inventory only.

## What the experimental code currently does

In `local_agent/blender_workflow.py`, the bundled Mia look-development script contains a deterministic bounded optimizer:

- It segments a fixed 710×1536 three-column turnaround sheet using chroma thresholds and produces front, side, and back outer-contour profiles. It excludes black margins, but has no human-reviewed confidence map and assumes this exact sheet layout.
- It compares normalized outer contours. It does **not** measure facial landmarks, internal face features, separate garment regions, or calibrated camera projections.
- It searches ten bounded global proportion controls with a deterministic coordinate search (maximum 241 evaluations). Accepted controls deform all mesh vertices by height region; they do not independently edit eyes, cheeks, jaw, fringe, bun, clothing, or hair topology.
- The Blender adapter saves a fit report and segmentation masks and applies a proposed deformation to the generated look-development mesh. These masks are intermediate segmentation evidence, not the region-wise score in `local_agent/mia_fit_metrics.py`.
- The separate `mia_fit_metrics.py` module scores already-measured masks and landmarks and supports keep/rollback decisions. It does not extract those features or drive the Blender optimizer.
- The prototype identifies its metric as an outer-contour error and explicitly never reports identity as verified.

This is useful as a low-cost body/silhouette experiment. It is not yet the full ReferenceFit architecture or a finished Mia model.

## Required next work

1. **Lock the approved reference.** Confirm the exact reference SHA-256 and view layout from the Windows workspace. Preserve camera and image dimensions; never improve the score by changing camera framing.
2. **Build a reviewable analyzer.** Extract per-view silhouette, hair, face, eye, jacket, trousers, boots, and backpack masks plus facial landmarks. Show each extracted overlay for visual review. Missing or low-confidence features must block scoring.
3. **Expand editable controls.** Add independent face and hair geometry controls, including eye placement and size, cheek/jaw shape, hairline, fringe, side locks, and bun. Use a curves-based hair constructor or suitable licensed donor geometry where the control test proves the current topology cannot express the reference.
4. **Use a multi-view objective.** Combine silhouette overlap, normalized landmarks, and region-specific color/mask errors. Keep camera calibration fixed and prevent one view or region from hiding a regression in another.
5. **Keep the source safe.** Fit a copy of the donor or generated static mesh. Do not clear animation data, drivers, constraints, shape keys, or rig data as a side effect. Validate them independently before any rig transfer.
6. **Gate expensive renders.** Search with geometry and low-resolution previews first. Keep at most ten full-resolution checkpoints; save each candidate separately and roll back if measurements regress or the actual geometry is unchanged.
7. **Use licensed sources.** Record source URL, license, and SHA-256 before importing a donor. Do not run external `.blend` auto-execution scripts.

## Verification status

- Experimental outer-contour optimizer and its helpers: **implemented in the experimental branch**.
- Mia metric and optimizer unit tests run in an isolated scratch copy: **13 passed, 1 skipped**. The skipped test requires the private approved reference image, absent from this environment.
- Inclusion of these test modules in the Blender agent's explicit test allowlist: proposed in PR #76.
- Windows execution of these branch-specific tests: **not verified**.
- Blender integration against the approved Mia reference: **not verified**.
- Per-region image extraction and facial landmark scoring: **not implemented**.
- Independent face and hair controls or parameterized curves: **not implemented**.
- Driver, shape-key, and rig preservation checks: **not verified**.
- Final Mia resemblance: **not approved**.

A lower outer-contour error is evidence of a better silhouette fit under these assumptions. It is not evidence by itself that the model is recognizably Mia.

## Technical references

- Blender Lattice modifier: https://docs.blender.org/manual/en/4.0/modeling/modifiers/deform/lattice.html
- Blender Studio Spring: https://studio.blender.org/characters/spring/v1/
- Blender Studio Snow v4: https://studio.blender.org/characters/snow/v4/
- NVIDIA differentiable rasterization: https://github.com/NVlabs/nvdiffrast
