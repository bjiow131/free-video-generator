# Season 1 — character library

This folder is the structured starting package for a 30-episode preschool adventure series. The episode scripts are deliberately stored in a separate private branch.

## Included
- 14 character passports under `character_passports/`.
- A CC0/public-domain reference catalog with source links and usage limits.
- Reusable location/prop/effect inventory.
- Passports define intended design and animation needs; they do **not** claim a model or rig already exists.

## Import
The current GUI passport importer imports one passport at a time. Import each JSON from `character_passports/` via **Библиотека → Импортировать паспорт…**. Then add downloaded reference images through the character's reference tab. The script `scripts/prepare_season1_library.py` (added in this branch) automates card creation and writes the season asset manifest for local library use.

## References and licenses
See `asset_catalog.json`. Most links are CC0; where a collection aggregates third-party works, inspect the specific asset page and retain the exact license record. Adult human models are technical rig/style references only and must not determine the appearance of child characters.

## Blender readiness gate
Before production: import candidate assets, inspect scale/origin/materials, verify rig and action clips, test deformation and mouth-open control, render a turntable, record SHA-256 and source/license. A passport marked `design_ready_model_not_built` is not yet production-ready.
