"""Blender-side *test-fixture* executor; invoked only by the local bounded job runner.

No Python code from a user prompt is executed. User's 2D references are not loaded
as meshes. The fixture is deliberately unmistakable and is not a character rig.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def main():
    import bpy
    from mathutils import Vector

    if "--" not in sys.argv:
        raise RuntimeError("Missing manifest")
    manifest = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("actor_kind") != "procedural_test_fixture":
        raise RuntimeError("This executor is limited to an explicitly selected test fixture")
    if manifest.get("readiness") != "ready_fixture" or manifest.get("missing_requirements"):
        raise RuntimeError("The scene is not ready")
    fps, duration = manifest["fps"], manifest["duration"]
    if type(fps) is not int or not 1 <= fps <= 60 or type(duration) is not int or not 1 <= duration <= 120:
        raise RuntimeError("Invalid duration/fps")
    if manifest.get("resolution") not in ("360x640", "640x360", "512x512", "720x1280", "1280x720"):
        raise RuntimeError("Invalid resolution")
    actions = manifest.get("actions")
    if not isinstance(actions, list) or not actions or len(actions) > 20 or any(a not in ("walk", "turn", "wave", "speak", "idle") for a in actions):
        raise RuntimeError("Unsupported actions")
    if manifest.get("camera") not in ("follow", "push_in", "hold"):
        raise RuntimeError("Unsupported camera")
    output = Path(sys.argv[sys.argv.index("--") + 2])
    if not output.is_dir():
        raise RuntimeError("Output folder missing")
    frame_dir = output / "frames"
    frame_dir.mkdir(exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    total = fps * duration
    scene.frame_start, scene.frame_end, scene.render.fps = 1, total, fps
    scene.render.resolution_x, scene.render.resolution_y = map(int, manifest["resolution"].split("x"))
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(frame_dir / "frame_")
    # Workbench is intentionally low-cost; the test fixture uses material colors.
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Studio Camera QA World")
    scene.world.color = (0.08, 0.11, 0.16)

    def material(name, rgba):
        m = bpy.data.materials.new(name)
        m.diffuse_color = rgba
        return m

    cyan = material("Studio demo cyan", (0.10, 0.78, 0.85, 1.0))
    orange = material("Studio demo orange", (0.98, 0.42, 0.13, 1.0))
    floor = material("Studio demo floor", (0.13, 0.17, 0.22, 1.0))
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -0.16))
    ground = bpy.context.object
    ground.name = "STUDIO_FIXTURE_FLOOR"
    ground.dimensions = (200, 200, 0.3)
    ground.data.materials.append(floor)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    root = bpy.data.objects.new("STUDIO_TEST_ACTOR_NOT_MIA", None)
    bpy.context.collection.objects.link(root)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, location=(0, 0, 1.2))
    body = bpy.context.object
    body.name = "TEST_ACTOR_BODY"
    body.scale = (0.46, 0.35, 0.64)
    body.data.materials.append(cyan)
    body.parent = root
    body.matrix_parent_inverse = root.matrix_world.inverted()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, location=(0, -0.36, 1.24))
    mouth = bpy.context.object
    mouth.name = "TEST_ACTOR_MOUTH"
    mouth.scale = (0.14, 0.05, 0.06)
    mouth.data.materials.append(orange)
    mouth.parent = root
    mouth.matrix_parent_inverse = root.matrix_world.inverted()
    bpy.ops.mesh.primitive_cube_add(size=0.28, location=(0.55, 0, 1.4))
    arm = bpy.context.object
    arm.name = "TEST_ACTOR_WAVE_ARM"
    arm.data.materials.append(orange)
    arm.parent = root
    arm.matrix_parent_inverse = root.matrix_world.inverted()

    bpy.ops.object.camera_add(location=(0, -6.2, 2.5))
    camera = bpy.context.object
    scene.camera = camera
    camera.data.type = "PERSP"
    camera.data.lens = 42
    def aim(target):
        camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()

    root.location = (0, 0, 0)
    root.keyframe_insert(data_path="location", frame=1)
    root.keyframe_insert(data_path="rotation_euler", frame=1)
    mouth.scale.z = 0.06
    mouth.keyframe_insert(data_path="scale", frame=1)
    arm.rotation_euler = (0, 0, 0)
    arm.keyframe_insert(data_path="rotation_euler", frame=1)
    camera.keyframe_insert(data_path="location", frame=1)
    n = len(actions)
    # Sequential action windows. Scene heading and position stay continuous.
    x, yaw = 0.0, 0.0
    for index, action in enumerate(actions):
        begin = 1 + (index * (total - 1)) // n
        end = 1 + ((index + 1) * (total - 1)) // n
        root.location.x = x
        root.rotation_euler.z = yaw
        root.keyframe_insert(data_path="location", frame=begin)
        root.keyframe_insert(data_path="rotation_euler", frame=begin)
        if action == "walk":
            x += 2.0
            root.location.x = x
            root.keyframe_insert(data_path="location", frame=end)
        elif action == "turn":
            yaw += math.pi / 2
            root.rotation_euler.z = yaw
            root.keyframe_insert(data_path="rotation_euler", frame=end)
        elif action == "wave":
            arm.rotation_euler.y = 0.7
            arm.keyframe_insert(data_path="rotation_euler", frame=begin)
            for frame in range(begin + 1, end, max(1, fps // 3)):
                arm.rotation_euler.y *= -1
                arm.keyframe_insert(data_path="rotation_euler", frame=frame)
            arm.rotation_euler.y = 0
            arm.keyframe_insert(data_path="rotation_euler", frame=end)
        elif action == "speak":
            for frame in range(begin, end, max(1, fps // 4)):
                mouth.scale.z = 0.20 if ((frame - begin) // max(1, fps // 4)) % 2 == 0 else 0.06
                mouth.keyframe_insert(data_path="scale", frame=frame)
            mouth.scale.z = 0.06
            mouth.keyframe_insert(data_path="scale", frame=end)
        # A real turn and the camera are baked independently.
        root.keyframe_insert(data_path="location", frame=end)
        root.keyframe_insert(data_path="rotation_euler", frame=end)

    # Key camera at all action boundaries to avoid jump cuts.
    for frame in sorted({1, total} | {1 + i * (total - 1) // n for i in range(n + 1)}):
        scene.frame_set(frame)
        pos = root.matrix_world.translation
        if manifest["camera"] == "follow":
            camera.location.x = pos.x
        elif manifest["camera"] == "push_in":
            camera.location.y = -6.2 + (frame / total) * 1.2
        aim((pos.x, pos.y, 1.1))
        camera.keyframe_insert(data_path="location", frame=frame)
        camera.keyframe_insert(data_path="rotation_euler", frame=frame)

    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "scene.blend"))
    bpy.ops.render.render(animation=True)
    print("STUDIO_SCENE_FRAMES_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
