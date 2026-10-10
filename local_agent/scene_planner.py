"""Data-only scene planner for the Blender Work Agent."""
from __future__ import annotations
from typing import Any

ENVIRONMENT_ASSETS = {
    "forest": ["ground", "tree_line", "foliage"],
    "room": ["floor", "walls", "interior_lighting"],
    "city": ["street", "buildings", "street_lighting"],
    "space": ["space_backdrop", "stars"],
    "island": ["sand", "ocean_surface", "shoreline"],
    "coast": ["coastal_ground", "ocean_surface", "beach_strip", "cycling_path", "shoreline", "horizon"],
    "mountains": ["ground", "distant_mountains"],
    "underwater": ["water_backdrop", "coral", "fish"],
    "desert": ["sand", "dunes"],
    "winter": ["snow_ground", "winter_trees"],
    "village": ["ground", "houses"],
    "playground": ["ground", "trees"],
    "fantasy": ["fantasy_backdrop", "distant_shapes"],
    "studio": ["studio_ground", "studio_lighting"],
    "auto": ["ground", "prompt_selected_environment"],
}

def build_scene_plan(prompt: str, objects: list[dict[str, Any]], environment: str,
                     animation: dict[str, Any], relationships: dict[str, Any] | None = None,
                     camera_angle: str = "auto") -> dict[str, Any]:
    """Compile scene intent into inspectable data; do not execute prompt text."""
    text = prompt.casefold()
    links = relationships or {}
    actors = [
        {"id": str(obj.get("character_card_id") or obj.get("name", "")),
         "name": str(obj.get("name", "")),
         "type": str(obj.get("profile_type") or obj.get("primitive", "object")),
         "source": "character_card" if obj.get("character_card_id") else "scene_object"}
        for obj in objects if obj.get("character_card_id") or obj.get("primitive") in {"person", "animal"}
    ]
    props = [{"name": str(obj.get("name", "")), "kind": str(obj.get("primitive", "object"))}
             for obj in objects if not obj.get("character_card_id")]
    frames = max(24, min(240, int(animation.get("frames", 150))))
    seconds = round(frames / 30, 2)
    vehicle = next((obj for obj in objects if obj.get("primitive") in {"bicycle", "scooter"}), None)
    actor = actors[0] if actors else None
    actions = []
    if vehicle and actor and any(word in text for word in ("едет", "катается", "крутит педали", "верхом")):
        actions.append({
            "action": "ride_vehicle", "actor_id": actor["id"], "target": vehicle["name"],
            "duration_seconds": seconds, "status": "partial_blockout",
            "implementation": "root_translation_and_wheel_rotation",
            "limitation": "No seated riding pose, articulated pedaling, or character rig yet.",
        })
    elif animation.get("enabled"):
        actions.append({"action": str(animation.get("kind", "move")),
                        "actor_id": actor["id"] if actor else None,
                        "duration_seconds": seconds, "status": "basic_keyframes"})
    if vehicle and actor and actions or any(word in text for word in ("камера следует", "камера сопровождает", "tracking shot")):
        camera = {"shot": "tracking", "motion": "follow_actor",
                  "target_actor_id": actor["id"] if actor else None,
                  "status": "basic_linear_follow",
                  "limitation": "Only linear X-axis tracking is implemented; no adaptive framing or obstacle avoidance."}
    elif any(word in text for word in ("крупный план", "приближение", "наезд камеры", "close-up")):
        camera = {"shot": "close_up", "motion": "push_in", "status": "planned_not_executed"}
    elif any(word in text for word in ("панорама", "камера поворачивается")):
        camera = {"shot": "wide", "motion": "pan", "status": "planned_not_executed"}
    else:
        camera = {"shot": "top_down" if camera_angle == "top" else "establishing",
                  "motion": "static", "status": "static_camera"}
    return {
        "schema_version": 1, "duration_seconds": seconds, "fps": 30,
        "location": {"environment_id": environment,
                     "environment_assets": list(ENVIRONMENT_ASSETS.get(environment, ENVIRONMENT_ASSETS["auto"]))},
        "actors": actors, "props": props, "relationships": dict(links),
        "action_steps": actions, "camera": camera,
        "reference_policy": {
            "characters": "Use character-card references when available.",
            "environment": "Reuse a location asset or build from a procedural recipe; a user location reference is optional."
        }
    }
