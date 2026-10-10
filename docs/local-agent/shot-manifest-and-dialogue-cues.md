# Shot manifest and dialogue cue contract

Status: design specification. This document does not claim that the full shot executor or character animation is implemented.

## Purpose

Connect the existing local-first scene planner/compiler, asset registry, and Blender bridge without creating a second competing planner. All prompts remain data; the agent must never execute Python or shell commands supplied in a prompt or manifest.

## Pipeline boundary

1. `scene_language` extracts a structured request.
2. `scene_planner` proposes actions and camera intent, with an explicit capability status.
3. `scene_compiler` validates the plan and resolves asset IDs against the project asset registry.
4. A shot manifest records the exact scene, action, camera, continuity IDs, and dialogue cues.
5. The Blender bridge accepts only a validated, allowlisted operation plan. It reports unsupported actions before opening Blender.
6. A scene audit checks postconditions and writes a result manifest. A process exit code alone is not proof of a valid scene or render.

The current bridge only supports `forest_preview`. Until a shot executor is implemented, shot manifests must remain planning artifacts and must not be passed to the bridge as executable tasks.

## Shot manifest v1

Each shot has stable identifiers and is independently resumable:

- `schema_version`: integer.
- `episode_id`, `shot_id`: stable IDs such as `S01E01` and `S01E01_SH001`.
- `duration_seconds`, `fps`, `frame_start`, `frame_end`.
- `location_id`: registry ID, not an arbitrary filesystem path.
- `characters[]`: `character_id`, `continuity_profile`, `action_id`, `action_variant`, and optional `rig_asset_id`.
- `props[]`: `asset_id`, optional `attached_to`, and continuity-critical flag.
- `camera`: shot type, target ID, motion ID, framing constraint.
- `dialogue_cues[]`: speech cue records described below.
- `audio_policy`: voice and music remain separate tracks; timings stay estimated until voice recordings exist.
- `validation`: required assets, active camera, frame bounds, source preservation, and action/rig compatibility.

All IDs must resolve through the project manifest or asset registry. Do not accept arbitrary absolute paths from prompt text. Missing references are validation errors, not implicit asset creation.

## Simple dialogue mouth cues

Voice and music are added after the 30 videos are complete. Before voiceover, use approximate script-based mouth opening/closing only; do not claim phoneme-level lip sync or exact word alignment.

A cue contains:

- `speaker_id`: stable character ID.
- `line_id`: unique line ID within the episode.
- `text`: dialogue text, kept separate from timing metadata.
- `timing_status`: `estimated_until_voiceover` or `confirmed_from_audio`.
- `events[]`: ordered events with `frame` and `mouth_state` (`open` or `closed`).

For an estimated line, a simple alternating open/closed pattern may approximate speaking rhythm. Events must be within the shot frame range and monotonically ordered. Adjacent duplicate states should be collapsed. Silence and non-speaking characters default to closed. After voice recording, adjust event timing against the actual recording if needed; never silently label estimated timing as confirmed.

Example (illustrative only; frame numbers are not final voice synchronization):

```json
{
  "speaker_id": "char.mia.master",
  "line_id": "S01E01_L001",
  "text": "Смотри, улитка!",
  "timing_status": "estimated_until_voiceover",
  "events": [
    {"frame": 18, "mouth_state": "open"},
    {"frame": 22, "mouth_state": "closed"},
    {"frame": 26, "mouth_state": "open"},
    {"frame": 30, "mouth_state": "closed"}
  ]
}
```

The rig adapter must declare whether it supports mouth-state control. If no compatible mouth control exists, report `unsupported_rig_control`; do not pretend the cue was applied.

For Blender object discovery, character mesh objects may carry the custom property `local_agent_character_id` with a stable value such as `char.mia.master`. The adapter indexes only explicit IDs, groups multiple mesh parts under one character, and does not infer identity from object names. Untagged objects remain unindexed; non-mesh objects are excluded. This index helper is available to callers but is not yet wired into the bridge task executor.

## Action capability registry

Each action ID must declare:

- accepted parameters and bounds;
- required object/rig capabilities;
- executor implementation/version;
- expected postconditions;
- test fixture and regression test;
- current status: `implemented`, `partial`, `planned`, or `unsupported`.

The planner must not translate a generic natural-language action into an executable action unless the capability registry resolves it. For example, `ride_vehicle` remains partial until the actor has a compatible riding pose/rig, the vehicle is attached or aligned correctly, wheel motion is supported, and the camera keeps the character inside frame.

## Safety and continuity checks

Before execution:
- reject unknown schema versions and unknown action IDs;
- verify all asset IDs, rig compatibility, camera target, frame range, and output containment;
- ensure output paths cannot escape the configured workspace;
- never overwrite source/reference assets;
- require a new versioned output when a prior approved shot exists.

After execution:
- verify the saved .blend is non-empty and the expected scene/camera/actions exist;
- validate preview file signature and dimensions;
- report missing/unsupported actions and unresolved assets separately;
- save a machine-readable report and preserve bounded logs.

## Implementation order

1. Add schema validators and tests for shot IDs, frame ranges, dialogue cue ordering, and capability resolution.
2. Add an action/rig capability registry and connect it to `scene_compiler`.
3. Add a non-destructive shot-manifest writer with versioned outputs.
4. Implement one narrow Blender action end-to-end (for example, idle/look-at) with a real fixture and postcondition tests.
5. Add mouth open/close only for rigs with a verified mouth control.
6. Expand to walk, turn, point, wave, and simple prop interactions one tested capability at a time.
7. Add reusable episode/shot manifests for all 30 episodes after the executor is reliable.

## Acceptance rule

A capability is complete only when its unit tests pass and a Blender smoke test validates the saved scene and preview on the target installation. Until then, label it planning-only or unverified. The target installation is Blender 5.2.2; no compatibility claim should be made until that version is actually tested.
