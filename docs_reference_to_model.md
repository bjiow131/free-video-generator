# Reference-to-Model: reusable character fitting core

The project goal is reusable: each character is a new, hash-pinned reference package and a compatible editable base mesh. Mia is the pilot. The pipeline is staged: source audit, calibrated reference map, parameterized geometry, measured fitting, topology/animation quality gates, then final look development and rig transfer.

## Current implementation

`local_agent/reference_to_model.py` is a Blender-independent core. It validates a versioned JSON specification, SHA-256 identity, camera-normalized landmarks, optional sampled silhouette contours, and bounded controls. Allowed controls are shape keys, object scale, and a selected object-location component. It computes confidence-weighted landmark loss and a symmetric sampled contour distance, plus optional regularization. `optimize()` uses bounded `scipy.optimize.least_squares` if SciPy is installed.

`build_hair_curves()` creates independent stylized Curve objects from explicit local-space strand control points. These generated objects can be recreated without modifying donor hair geometry. They are a deterministic construction utility, not an automatic hairstyle extractor.

The Mia pilot module remains for backwards compatibility and its existing local operation. Its project resolver accepts a direct project folder or the fixed `SOURCE_ADAPTATIONS/<project>` folder and rejects linked paths. The older fitting stage remains shape-key-only.

## Input contract

Use `schema_version: 1`, `coordinate_convention: camera_frame_bottom_left_normalized`, `character_name`, `reference_sha256`, `views`, and `controls`. Every view names a fixed Blender camera and has landmarks and/or a sampled silhouette. Each landmark names a mesh object and vertex index, target XY, confidence, and visibility. Controls specify one of the bounded types with initial/lower/upper values and optional regularization.

Keep separate source images for each view and region. Record per-image hash and provenance in the surrounding reference package. A single view cannot determine hidden depth; the core returns `underconstrained` for one view. Three or more useful views are recommended, but do not remove the need for human review.

## Current limits and next gates

This core does not yet automatically segment reference images, infer landmarks, generate arbitrary topology, measure color-region loss, construct clothing, or produce a finished rig. Silhouette loss currently compares supplied contour samples; it is not a rasterized mask loss. The generic core has not yet been wired as a new Windows mailbox operation or exercised against Blender 5.2.2. The next integration step is to add the typed protocol operation and Blender-side generic controller application, then run a read-only donor passport followed by a low-cost projection test.

Donor choice is per asset and per Blender version. The audit shortlist includes Blender Studio Storm (Blender 5.0+), Snow v4 (Blender 4.1, CC-BY), Rain, and any user-provided or legally usable source. No donor is assumed compatible until its file opens, mesh/shape-key/driver inventory is measured, and license provenance is recorded. Do not import a donor's rig into the modeling stage by default.
