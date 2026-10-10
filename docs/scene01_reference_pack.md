# Scene 01 reference pack

The desktop app has a **«Референсы сцены 01…»** action in the character library. Downloads happen only after the user explicitly clicks it.

## Included sources

- `snail_moss_cc0.jpg` — [Albino snail walking on green moss](https://commons.wikimedia.org/wiki/File:Albino_snail_walking_on_green_moss.jpg), CC0 1.0. Shell/body/ground-contact reference.
- `garden_snail_wood_cc0.jpg` — [Garden snail on wooden fence](https://commons.wikimedia.org/wiki/File:Garden_snail_on_wooden_fence.jpg), CC0 1.0. Additional snail anatomy reference.
- `woodland_path_cc0.jpg` — [Forest path along wall](https://commons.wikimedia.org/wiki/File:Forest_path_along_wall.jpg), CC0 1.0. Environment and composition reference.
- Optional `opengameart_3d_character_pack.zip` — [3D Character Pack](https://opengameart.org/content/3d-character-pack), marked CC0 by its author. This is a generic pack of character candidates, **not** a confirmed match for Mia and not guaranteed to contain a suitable child model.

## Storage

Files are stored outside the source checkout in `<character library>/scene01_reference_pack/`. The `manifest.json` records source pages, license declarations, file sizes, hashes, download failures, and filenames.

The download helper validates image signatures, ZIP integrity and archive paths, enforces size limits, rejects symlinks and uses atomic replacement. The optional ZIP is not automatically extracted or imported into Blender.

## Production caveat

The photos are visual references, not 3D assets. The downloaded character pack must be inspected manually before any character is chosen for the scene. Do not replace the established Mia design solely because a generic asset exists.
