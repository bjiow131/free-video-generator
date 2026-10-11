# Season 1 production gates

This file separates planned work from verified production assets.

## Character assets
- Confirm approved front, side, back, three-quarter, and expression references exist locally.
- Record approved silhouette, HEX palette, dimensions in metres, clothing/material IDs, and continuity rules.
- Import each exact model into Blender 5.2 and check textures, scale, transforms, rig controls, animation clips, and a short test render.
- Record exact asset page, license text, author, retrieval date, local path, SHA-256, and modifications.
- Adult-proportioned CC0 human packs are technical rig references only, not a likeness for child characters.

## Locations and props
- Build eight reusable location sets with stable asset IDs, scale, palette, lighting notes, and camera-safe paths.
- Reuse master props and hero rigs across episodes; do not duplicate them per scene.
- Record dimensions, origin/pivot, material IDs, attachment points, and continuity rules for recurring props.

## Camera and shots
Each shot needs shot_id, scene_id, duration_seconds, location_id, asset_ids, camera_type, camera_target, aspect_ratio, movement, actor actions, start/end poses, and continuity notes. Validate 9:16 and 16:9 framing independently. Keep faces and speaking mouths visible during dialogue.

## Word-level mouth markers
Audio and music remain separate. For each spoken line, record speaker_id, text, start_seconds, end_seconds, mouth_action (open/close), and source status (script_estimate/audio_aligned/manually_verified). Open the mouth during spoken word spans, close between phrases and after the last word. No phoneme-level system is required. Estimated markers must not be labelled audio-verified.

## Episode completion
A five-beat outline is not a full screenplay. Every episode must have action, dialogue, transitions, emotional progression, an ending, runtime calculation, shot list, and dialogue markers. Target duration: 300–600 seconds.

## Acceptance
An asset is production-ready only after exact license review, local file/hash capture, successful Blender import, scale/material/rig/animation checks, and a test render. Metadata validation alone cannot prove Blender readiness.