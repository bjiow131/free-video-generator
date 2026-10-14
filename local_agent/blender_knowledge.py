"""Curated, searchable Blender knowledge for the local 3D agent.

Original operational notes, not a copied Blender manual. Advice is version-aware
where possible; always verify version-specific details in Blender's official docs.
This module is read-only: it returns guidance and never executes scripts.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeEntry:
    id: str
    title: str
    tags: tuple[str, ...]
    guidance: tuple[str, ...]
    verify: tuple[str, ...]
    docs_url: str


_ENTRIES: tuple[KnowledgeEntry, ...] = (
    KnowledgeEntry(
        "scene-objects",
        "Scene and object operations",
        ("scene", "object", "collection", "объект", "сцена", "коллекция", "bpy.data", "bpy.ops"),
        (
            "Prefer direct data API operations for deterministic object/material setup; use bpy.ops when an operator is genuinely required.",
            "Before modifying an existing project, inspect the active scene, selected objects, collections, and current file path.",
            "Use descriptive stable names and collections for character, rig, environment, lights, and cameras.",
            "Do not clear or delete a scene unless the task explicitly requests it and a backup/checkpoint exists.",
        ),
        ("Check object count and expected names after the operation.", "Confirm objects are in the intended collection and scene."),
        "https://docs.blender.org/api/current/bpy.types.Scene.html",
    ),
    KnowledgeEntry(
        "materials",
        "Materials and shader nodes",
        ("material", "shader", "principled", "texture", "материал", "шейдер", "текстура", "узлы"),
        (
            "Create materials explicitly and set Principled BSDF inputs by socket name when available; socket identifiers can change between Blender versions.",
            "Check whether nodes are enabled and whether the material is assigned to the intended mesh.",
            "For a stylized character, keep a named material palette and avoid creating duplicate materials on every run.",
        ),
        ("Inspect material slots and node links.", "Render a small preview under the actual scene lighting."),
        "https://docs.blender.org/manual/en/latest/render/shader_nodes/shader/principled.html",
    ),
    KnowledgeEntry(
        "modifiers-geometry",
        "Mesh, transforms, and modifiers",
        ("mesh", "geometry", "modifier", "bevel", "subdivision", "normal", "сетка", "геометрия", "модификатор"),
        (
            "Apply transforms only when required; applying transforms changes the object's editable state.",
            "Before adding a modifier, check whether an equivalent modifier already exists to avoid stacking duplicates on reruns.",
            "Validate dimensions, scale, normals, and modifier order when geometry looks wrong.",
            "Use a duplicate or checkpoint before destructive mesh edits.",
        ),
        ("Check object dimensions and scale.", "Inspect modifier names, order, viewport/render toggles, and mesh normals."),
        "https://docs.blender.org/manual/en/latest/modeling/modifiers/index.html",
    ),
    KnowledgeEntry(
        "character-modeling",
        "Character modeling and consistent proportions",
        ("character", "model", "proportions", "reference", "мия", "персонаж", "пропорции", "референс"),
        (
            "Keep approved reference images and proportion notes in a project-specific reference folder; never infer that a new render replaces the canonical reference.",
            "Build and validate the character in stages: blockout silhouette, proportions, face, clothing, hands/feet, then materials and detail.",
            "Use named body-part objects or clearly named mesh regions while the design is changing; join meshes only when the workflow benefits from it.",
            "Compare front, side, and three-quarter views under neutral lighting before adding complex materials.",
        ),
        ("Compare silhouette and head-to-body ratio against the approved reference.", "Check front, side, and three-quarter views at matching scale."),
        "https://docs.blender.org/manual/en/latest/modeling/meshes/index.html",
    ),
    KnowledgeEntry(
        "armature-rigging",
        "Armatures and rigging",
        ("armature", "rig", "bone", "parent", "weight", "rigging", "скелет", "кости", "риггинг", "веса"),
        (
            "Establish the rest pose and bone naming before animation; keep a saved checkpoint before changing the rig.",
            "Use deform bones for skinning and separate control bones when the rig design requires them.",
            "After parenting with automatic weights, inspect shoulders, hips, elbows, knees, wrists, and neck; automatic weights are a starting point, not proof of good deformation.",
            "Do not rename or restructure bones in an animation project without checking existing actions and constraints.",
        ),
        ("Test a small set of extreme poses.", "Inspect weight paint and deformation at joints.", "Verify constraints and bone collections."),
        "https://docs.blender.org/manual/en/latest/animation/armatures/index.html",
    ),
    KnowledgeEntry(
        "weight-paint",
        "Skinning and weight paint",
        ("weight paint", "weights", "deform", "skin", "weight painting", "веса", "скиннинг"),
        (
            "Each deform vertex should have sensible influence from nearby bones; inspect normalized weights and unintended influences.",
            "Check mesh and armature transforms and the Armature modifier target when deformation fails.",
            "Correct one joint region at a time and re-test the same repeatable poses.",
        ),
        ("Test elbow/knee bends, arm raise, hip rotation, and neck turns.", "Look for pinching, collapsing volume, and vertices following the wrong bone."),
        "https://docs.blender.org/manual/en/latest/sculpt_paint/weight_paint/index.html",
    ),
    KnowledgeEntry(
        "animation-actions",
        "Actions, keyframes, and animation",
        ("animation", "action", "keyframe", "fcurve", "nla", "анимация", "ключевой кадр", "движение"),
        (
            "Define the target action, frame range, frame rate, and intended looping behavior before creating keyframes.",
            "Use named actions and explicit frame numbers; avoid relying on whichever object happens to be active.",
            "When editing animation data, confirm whether the action is shared by multiple objects before changing it.",
            "Review motion at normal playback speed and inspect silhouettes at key poses, not only at the first frame.",
        ),
        ("Scrub the full frame range.", "Check foot sliding, balance, clipping, and abrupt interpolation.", "Confirm action assignment and frame range."),
        "https://docs.blender.org/manual/en/latest/animation/index.html",
    ),
    KnowledgeEntry(
        "camera-lighting",
        "Camera, lighting, and composition",
        ("camera", "lighting", "light", "composition", "render", "камера", "свет", "композиция"),
        (
            "Set the active camera explicitly and verify framing before spending time on final render settings.",
            "Use a preview render to validate silhouette, clipping, exposure, and background before a full-quality render.",
            "For vertical story scenes, set output dimensions intentionally and confirm camera composition in the final aspect ratio.",
            "Keep character key light, fill, and rim/background lighting conceptually separate so errors are easier to diagnose.",
        ),
        ("Verify active camera, clipping range, resolution, frame, and render engine.", "Inspect a preview render before full render."),
        "https://docs.blender.org/manual/en/latest/render/cameras.html",
    ),
    KnowledgeEntry(
        "render-pipeline",
        "Rendering and output validation",
        ("render", "eevee", "cycles", "png", "output", "рендер", "рендеринг", "eevee", "cycles"),
        (
            "Prefer a low-cost preview first; raise samples, resolution, and expensive effects only after composition is approved.",
            "Check the selected render engine against the installed Blender version instead of assuming an enum value exists.",
            "Use absolute output paths inside the project workspace and ensure the destination directory exists.",
            "A successful process exit is not enough: verify that the output file exists, has non-zero size, and can be opened.",
        ),
        ("Check process exit code and bounded stdout/stderr logs.", "Validate image signature and dimensions.", "Open the .blend file and confirm the expected scene."),
        "https://docs.blender.org/manual/en/latest/render/index.html",
    ),
    KnowledgeEntry(
        "python-api-versioning",
        "Blender Python API and version differences",
        ("python api", "bpy", "version", "api", "python", "версия", "api blender"),
        (
            "Record bpy.app.version_string and bpy.app.version before relying on API behavior.",
            "Prefer official API documentation matching the installed Blender version when a property or operator fails.",
            "Avoid assuming that context-sensitive bpy.ops calls work in background mode; use data API or a valid context override where appropriate.",
            "Never execute arbitrary code received from a remote task manifest. Use fixed, reviewed task templates and validated data arguments.",
        ),
        ("Capture Blender version, operation, traceback, and whether Blender was launched in background mode.", "Reproduce with the smallest scene and a copy of the project."),
        "https://docs.blender.org/api/current/",
    ),
    KnowledgeEntry(
        "background-mode",
        "Headless/background execution",
        ("background", "headless", "subprocess", "blender.exe", "background mode", "фоновый режим", "командная строка"),
        (
            "Use Blender's background mode for repeatable batch tasks, with a bounded timeout and separate stdout/stderr logs.",
            "Pass configuration as a data file or validated arguments, not by interpolating untrusted prompts into Python source.",
            "Treat timeout, crash, missing output, and invalid output as distinct failure classes.",
            "Keep task outputs within a configured workspace and reject path traversal, symlinks, and unexpected overwrite.",
        ),
        ("Check executable path and Blender version.", "Check timeout and exit code.", "Check logs and output files.", "Preserve the input .blend file."),
        "https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html",
    ),
    KnowledgeEntry(
        "project-safety",
        "Project safety, backups, and checkpoints",
        ("backup", "checkpoint", "save", "versioning", "безопасность", "резервная копия", "сохранение"),
        (
            "Create a checkpoint before changing topology, rig structure, actions, or shared materials.",
            "Never overwrite an existing project output unless the task explicitly allows it.",
            "Prefer saving to a new versioned .blend file during experimentation; keep the last known-good file untouched.",
            "Report what changed, which files were created, and which checks were performed.",
        ),
        ("Confirm the backup exists and is readable.", "Reopen the saved project in Blender when possible.", "Compare expected outputs against the task specification."),
        "https://docs.blender.org/manual/en/latest/files/index.html",
    ),
    KnowledgeEntry(
        "troubleshooting",
        "Common Blender failure triage",
        ("error", "traceback", "crash", "missing object", "pink texture", "black render", "ошибка", "сбой", "розовая текстура", "чёрный рендер"),
        (
            "For a Python exception, start with the first traceback line inside the task script and the final exception type/message.",
            "Missing object: inspect object name, active scene/collection, and whether the operation deleted or moved it.",
            "Pink/missing texture: inspect image paths, packed resources, shader links, and whether the asset exists on disk.",
            "Black/empty render: verify active camera, lights, object visibility, world settings, render engine, and output path.",
            "If the cause is uncertain, preserve the project and logs and escalate instead of making speculative destructive edits.",
        ),
        ("Save a copy before repair.", "Record Blender version and exact traceback.", "Reproduce with a minimal scene.", "Validate with a preview render."),
        "https://docs.blender.org/manual/en/latest/troubleshooting/index.html",
    ),
)


def search_knowledge(query: str, limit: int = 5) -> list[dict[str, object]]:
    """Return relevant curated entries using simple keyword matching; no code execution."""
    if not isinstance(query, str):
        return []
    query = query.strip().lower()[:1000]
    if not query:
        return []
    try:
        limit = max(1, min(int(limit), 10))
    except (TypeError, ValueError):
        limit = 5
    tokens = {token for token in query.replace("_", " ").replace("-", " ").split() if len(token) > 1}
    scored: list[tuple[int, KnowledgeEntry]] = []
    for entry in _ENTRIES:
        searchable = " ".join((entry.id, entry.title, *entry.tags, *entry.guidance)).lower()
        score = sum(2 if token in entry.tags or token == entry.id else 1 for token in tokens if token in searchable)
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [
        {
            "id": entry.id,
            "title": entry.title,
            "guidance": list(entry.guidance),
            "verify": list(entry.verify),
            "docs_url": entry.docs_url,
            "score": score,
        }
        for score, entry in scored[:limit]
    ]


def list_topics() -> list[dict[str, str]]:
    """Return stable topic IDs and titles for the local agent's index."""
    return [{"id": entry.id, "title": entry.title} for entry in _ENTRIES]
