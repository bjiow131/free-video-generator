# Season 1 character library

This branch retains 14 character passport descriptions and the scene inventory. All external visual-reference links have been removed from the passports and asset catalog. The catalog is empty pending original project-generated images and models.

## Policy

Only original project-specific visual assets may be imported into the production reference library. Do not automatically download third-party photos or models. Keep character identity, rig requirements, and scene descriptions as planning metadata, not as proof of completed visuals.

## Import

Run `scripts/prepare_season1_library.py` to import the passport metadata. The script no longer downloads outside reference images. Add original reference files separately using the local library interface. Existing local library content is not automatically deleted by these repository changes.

## Blender readiness

Each character needs an approved turnaround, an actual 3D model, a validated rig, and a Blender preview before production. Status `awaiting_original_references` means these prerequisites have not been met.
