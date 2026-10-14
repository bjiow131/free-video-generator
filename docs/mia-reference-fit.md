# Mia ReferenceFit: first-stage contract

ReferenceFit measures a candidate model against an approved, hash-pinned reference map. It optimizes only explicitly mapped, bounded shape keys and writes an accepted result to a new `.blend` file. The source file is opened read-only by the workflow and is checked against its starting SHA-256 after Blender exits.

Run `blender_mia_reference_fit_preflight` first. It produces a read-only geometry passport with the Blender version, camera names, mesh topology counts, shape keys, animation/driver counts, armature summary, curve objects, and whether SciPy imports in Blender's Python. It does not save the scene. The actual fit operation requires this passport to confirm that the chosen model and Blender installation are suitable.

The first stage does not move arbitrary vertices, retarget Spring, create hair, or render with Cycles. Those are later steps after the projection fit proves useful. A shape key with animation data or drivers cannot be selected as an optimization parameter. Existing animation data is never cleared.

## Reference map

Store a UTF-8 JSON file inside the local Mia project directory. The optimizer task must also pass the `passport_file` name returned by the read-only preflight; the passport's source SHA must match the `.blend` being fitted, and it must confirm at least two cameras, usable shape keys, and SciPy in Blender's Python. It must include:

- `schema_version`: `1`.
- `coordinate_convention`: `camera_frame_bottom_left_normalized`.
- `reference_sha256`: the approved reference image-set SHA-256.
- `views`: at least two entries, each using an existing fixed Blender camera, with measured landmarks.
- `parameters`: bounded shape-key controls. Every `initial` value must match the current key value in the source `.blend`.

Each landmark records a unique `name`, `object_name`, nonnegative `vertex_index`, normalized `target: [x, y]`, optional `confidence` from 0 to 1, and optional `visible` flag. Set `visible` to false for occluded or uncertain points. Image measurements use the same camera frame as Blender's `world_to_camera_view`, with the origin at the bottom-left.

Each parameter records a unique `name`, `object_name`, `key_name`, `initial`, `lower`, `upper`, and optional nonnegative `regularization`. Bounds must include the initial value. Values are author-supplied from measurements and reviewed mesh controls; the system does not invent targets.

## Quality gate

The optimizer uses bounded robust least squares and a confidence-weighted multi-view residual. A candidate is saved only if the optimizer converges, total residual falls by at least 1%, no view worsens by more than 2%, and the animation/driver inventory stays unchanged. A rejected pass keeps a JSON report and does not save a candidate `.blend`. Each task ID gets its own report and candidate filename so successive experiments retain their evidence.

Before the first real run, verify the approved reference digest, camera names, mesh vertex indices, and shape-key parameter ranges. Missing SciPy in Blender's Python is reported as a blocker; no dependency is silently installed.
