# Reference library: implementation status

## Implemented in this branch
- Data-only character passport schema and strict validation in `local_agent/reference_library.py`.
- Deterministic camera-view selection for explicitly named characters. Missing views remain **missing**, not guessed.
- Create-only passport writer in a project-local `passports/` directory.
- Draft passports for Мия, Стёпа and Спираль in `docs/reference-library/passports/`.
- Unit tests in `tests/test_reference_library.py`.

## Important limitations
This is a first implementation slice, **not a finished library UI**. The sample passports contain **planned** reference slots only; the actual image generated in chat has not been installed on the user's computer or committed to GitHub. No image slicing, computer-vision detection, Blender model construction, 3D rigging or end-to-end scene rendering is implemented by this module. The full approved 30-scene script was not located in the inspected repository files, so no invented asset-to-scene mapping is supplied.

## Integration design
The local app owns the passport and reference registry. Each character has stable ID, canonical description, model asset ID, and view-specific image references. An importer must take a local source image, offer **reviewable** normalized crop regions, write cropped images to `assets/`, and only then mark reference slots ready. The scene compiler can consume `build_scene_reference_plan` once integrated with the app. Blender should load the **single canonical 3D model**, not swap 2D images every time the camera changes.

## UI sketches (planned, not current screenshots)
- Library: Characters | Environments | Props | Actions
- Character passport: portrait, identity, approved outfit, 6 view slots, expression sheet, Blender model status
- Scene editor: prompt, scene asset matches, missing-reference warnings, camera, action, preview
- Timeline: scenes 1–30 with render/continuity states

## Audit checklist
- [x] Strict schema, bounded text/reference count
- [x] Path traversal rejected for declared image files
- [x] Missing views explicit
- [x] Duplicate reference IDs rejected
- [x] No overwrite of passport files
- [ ] Actual app UI wired to passport storage
- [ ] Crop/import workflow and real image files
- [ ] Full scene-to-asset inventory against final 30-scene script
- [ ] Blender integration and visual QA
- [ ] Tests executed in GitHub Actions and on Windows
