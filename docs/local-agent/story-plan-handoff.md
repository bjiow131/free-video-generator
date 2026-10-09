# Story plan handoff: remote creative director, local Blender executor

## Goal

Do not install a second language model on the PC just to write stories. ChatGPT can act as the creative director: it writes a structured, bounded story plan; the local agent receives that plan as JSON and stores it in the selected project. The local agent remains responsible for execution, safety checks, Blender, media processing and reports.

## First implementation milestone

The local_agent/story_plan.py module validates title, logline, character continuity notes, scene duration, location, action, camera, dialogue, assets, sound, transition and a finite allowlist of typed action steps (such as look_at, walk_to, wave and camera_pan). It rejects unknown fields, unsafe identifiers, invalid durations, duplicate scene IDs and oversized plans. It stores story_plan.json atomically inside the configured workspace, refuses symlink/junction project folders and refuses to overwrite an existing plan. Text is inert data; no scripts are executed.

A successful save_story_plan result means the plan was stored only. It does not claim that a scene has been built or rendered.

## Expected plan shape

~~~json
{
  "schema_version": 1,
  "project_name": "mia_snail",
  "title": "Мия и потерявшаяся улитка",
  "logline": "Мия помогает улитке вернуться домой до заката.",
  "target_duration_seconds": 180,
  "language": "ru",
  "character_bible": {"Мия": "Сохранять утверждённую внешность и пропорции."},
  "scenes": [{
    "scene_id": "scene_001",
    "title": "Шорох в траве",
    "duration_seconds": 12,
    "location": "Солнечная лесная тропинка",
    "action": "Мия слышит шорох, останавливается и замечает улитку.",
    "camera": "Общий план, затем крупный план на уровне улитки",
    "dialogue": [{"speaker": "Мия", "text": "Ты потерялась?", "delivery": "любопытно и доброжелательно"}],\n    "action_steps": [{"action": "look_at", "actor": "Mia", "target": "snail", "duration_seconds": 1.5}],
    "assets": ["Mia_reference_model", "snail", "forest_path"],
    "sound": "Пение птиц и шелест листьев",
    "transition": "cut",
    "visual_prompt": "Добрая стилизованная 3D-анимация, постоянный дизайн героини."
  }],
  "continuity_notes": "Не менять возраст и внешность Мии."
}
~~~

## Next milestones

This is a safe first stage, not a full natural-language-to-animation system. Next: project/asset registry; scene-plan compiler mapping supported action types to fixed Blender operations; preview rendering and visual QA; animation, dialogue/audio and MP4 assembly. Unsupported actions must be reported, not silently claimed complete.

## Mailbox

The mailbox uses a single desired-task JSON file and every remote operation requires explicit local approval. A save_story_plan task carries a validated story_plan object. The PC stores it locally; private reference images are not uploaded to the public repository. Keep the mailbox repository private and never put tokens in task arguments.
