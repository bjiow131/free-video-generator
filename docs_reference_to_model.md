# Reference-to-Model: reusable character fitting core

The project goal is reusable: each character is a new, hash-pinned reference package and a compatible editable base mesh. Mia is the pilot. The pipeline is staged: source audit, calibrated reference map, parameterized geometry, measured fitting, topology/animation quality gates, then final look development and rig transfer.

## Current implementation

`local_agent/reference_image_analyzer.py` is the first image-ingestion stage. It reads reference images locally, uses an existing alpha channel or a conservative flat-border estimate, writes reviewable mask PNGs, samples the silhouette into normalized camera coordinates, and pins all views to a deterministic SHA-256. It rejects textured/uneven backgrounds rather than silently treating them as foreground. It does not upload images. The mask must be visually reviewed before fitting.

`local_agent/reference_to_model.py` is a Blender-independent core. It validates a versioned JSON specification, SHA-256 identity, camera-normalized landmarks, optional sampled silhouette contours, and bounded controls. Allowed controls are shape keys, object scale, and a selected object-location component. It computes confidence-weighted landmark loss and a symmetric sampled contour distance, plus optional regularization. `optimize()` uses bounded `scipy.optimize.least_squares` if SciPy is installed.

`build_hair_curves()` creates independent stylized Curve objects from explicit local-space strand control points. These generated objects can be recreated without modifying donor hair geometry. They are a deterministic construction utility, not an automatic hairstyle extractor.

The Mia pilot module remains for backwards compatibility and its existing local operation. Its project resolver accepts a direct project folder or the fixed `SOURCE_ADAPTATIONS/<project>` folder and rejects linked paths. The older fitting stage remains shape-key-only.

## Input contract

Use `schema_version: 1`, `coordinate_convention: camera_frame_bottom_left_normalized`, `character_name`, `reference_sha256`, `views`, and `controls`. Every view names a fixed Blender camera and has landmarks and/or a sampled silhouette. Each landmark names a mesh object and vertex index, target XY, confidence, and visibility. Controls specify one of the bounded types with initial/lower/upper values and optional regularization.

Keep separate source images for each view and region. Record per-image hash and provenance in the surrounding reference package. A single view cannot determine hidden depth; the core returns `underconstrained` for one view. Three or more useful views are recommended, but do not remove the need for human review.

### Local image-analysis command

Install the local agent requirements, then run this from the repository root:

```powershell
python -m local_agent.reference_image_analyzer `
  --view front=C:\refs\front.png `
  --view left=C:\refs\left.png `
  --view back=C:\refs\back.png `
  --output-dir C:\AIStudioWorkspace\projects\referencefit\analysis
```

The command writes `reference_map.json` and one `mask_<view>.png` per image. Inspect every mask first. This stage produces a reviewable silhouette reference package; it deliberately reports `fit_ready: false` until the Blender cameras and model controls are calibrated. Transparent PNGs are preferred. Opaque images work only when the border is a reasonably uniform background.

### One-command geometric smoke run

The donor-independent first-draft command connects mask analysis to a coarse visual hull. Supply at least two calibrated orthographic views, world-axis mapping for each view, and approximate model-space bounds. On Windows PowerShell:

```powershell
python -m local_agent.reference_to_model_pipeline `
  --view front=C:\refs\front.png,x,z `
  --view side=C:\refs\side.png,y,z `
  --bounds-x -0.35 0.35 `
  --bounds-y -0.25 0.25 `
  --bounds-z 0 1.9 `
  --output-dir C:\AIStudioWorkspace\projects\referencefit\first_run `
  --grid-size 64
```

This writes review masks, a hash-pinned reference map, and an OBJ visual-hull draft. The masks and camera-axis mapping must be checked against the source before interpreting the mesh. The output is only a coarse silhouette volume; facial detail, hidden concavities, clothing seams, production topology, materials, and animation controls remain later stages. The command reports `fit_ready: false` and `production_ready: false` until those stages are implemented and verified.

## Current limits and next gates

This stage does not infer semantic landmarks, calibrate cameras, generate arbitrary topology, measure color-region loss, construct clothing, or produce a finished rig. Silhouette loss currently compares supplied contour samples; it is not a rasterized mask loss. The Blender fit adapter still needs an executable Blender 5.2.2 validation, including confirmation that SciPy is available inside Blender's bundled Python. The next engineering step is camera calibration and a generic Blender-side silhouette fit, followed by a read-only base-mesh passport and a low-cost projection test.

## Base-mesh generation options

The system must not depend on one donor. For references with multiple views, the provider adapter can generate a base mesh, which is then measured, corrected, and rigged through separate stages. Current candidates are:

- **Tripo**: official API has multiview-to-model endpoints, named front/left/back/right views, a P-series described as low-poly with cleaner topology, and a separate rigging endpoint. This requires an API key, incurs credit usage, and uploads reference images outside the local computer. Treat it as an opt-in generator and keep the provider output as a draft until the local Quality Gate passes.
- **Meshy**: official multi-image API accepts image URLs or data URIs and returns GLB among its model outputs. Its response includes consumed credits. It is another opt-in cloud backend with the same privacy/cost gate.
- **Hunyuan3D 2.1**: local Windows-capable option. The official repository reports roughly 10 GB VRAM for shape generation and 29 GB for shape plus texture. Its community license has conditions, so check intended use before choosing it.

No cloud API is called automatically and no key is stored in the mailbox. Use one of these only after the user selects/authorizes that provider and the local machine or account credentials are configured. A generated mesh is a starting surface, not proof of identity, clean topology, facial controls, or animation readiness.

Donor choice is per asset and per Blender version. The audit shortlist includes Blender Studio Storm (Blender 5.0+), Snow v4 (Blender 4.1, CC-BY), Rain, and any user-provided or legally usable source. No donor is assumed compatible until its file opens, mesh/shape-key/driver inventory is measured, and license provenance is recorded. Do not import a donor's rig into the modeling stage by default.
