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

This core does not yet automatically segment reference images, infer landmarks, generate arbitrary topology, measure color-region loss, construct clothing, or produce a finished rig. Silhouette loss currently compares supplied contour samples; it is not a rasterized mask loss. Typed local mailbox operations are now wired, but have not yet been installed on the Windows agent or exercised in Blender 5.2.2. The next engineering step is automatic reference analysis and camera calibration, followed by a read-only donor passport and a low-cost projection test.

## Base-mesh generation options

The system must not depend on one donor. For references with multiple views, the provider adapter can generate a base mesh, which is then measured, corrected, and rigged through separate stages. Current candidates are:

- **Tripo**: official API has multiview-to-model endpoints, named front/left/back/right views, a P-series described as low-poly with cleaner topology, and a separate rigging endpoint. This requires an API key, incurs credit usage, and uploads reference images outside the local computer. Treat it as an opt-in generator and keep the provider output as a draft until the local Quality Gate passes.
- **Meshy**: official multi-image API accepts image URLs or data URIs and returns GLB among its model outputs. Its response includes consumed credits. It is another opt-in cloud backend with the same privacy/cost gate.
- **Hunyuan3D 2.1**: local Windows-capable option. The official repository reports roughly 10 GB VRAM for shape generation and 29 GB for shape plus texture. Its community license has conditions, so check intended use before choosing it.

No cloud API is called automatically and no key is stored in the mailbox. Use one of these only after the user selects/authorizes that provider and the local machine or account credentials are configured. A generated mesh is a starting surface, not proof of identity, clean topology, facial controls, or animation readiness.

Donor choice is per asset and per Blender version. The audit shortlist includes Blender Studio Storm (Blender 5.0+), Snow v4 (Blender 4.1, CC-BY), Rain, and any user-provided or legally usable source. No donor is assumed compatible until its file opens, mesh/shape-key/driver inventory is measured, and license provenance is recorded. Do not import a donor's rig into the modeling stage by default.
