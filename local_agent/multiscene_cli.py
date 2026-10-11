"""Run a validated multi-segment timeline in a local Blender project.

This is a constrained, opt-in CLI. No arbitrary script or network input is run.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from local_agent.blender_locator import find_blender_executable
from local_agent.multiscene_timeline import Segment, compile_timeline


BLENDER_SCRIPT = r'''
import bpy, json, sys
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

config = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
bpy.ops.wm.open_mainfile(filepath=config["source"])
scene = bpy.context.scene
camera = scene.camera
if camera is None:
    raise RuntimeError("Source scene has no active camera")
name = config["object_name"]
obj = bpy.data.objects.get(name)
if obj is None:
    raise RuntimeError("Required animated object not found: " + name)
camera.animation_data_clear()
obj.animation_data_clear()
# Track the subject continuously, including between keyframes.
# This keeps its origin centered but cannot prevent occlusion by other geometry.
for constraint in list(camera.constraints):
    if constraint.name == "Multiscene subject tracking":
        camera.constraints.remove(constraint)
tracking = camera.constraints.new(type="TRACK_TO")
tracking.name = "Multiscene subject tracking"
tracking.target = obj
tracking.track_axis = "TRACK_NEGATIVE_Z"
tracking.up_axis = "UP_Y"
# Keep a stable, user-configurable composition without changing the subject mesh.
# Lens adjustment alone cannot guarantee visibility when geometry occludes the subject.
camera.data.lens = config["camera_lens_mm"]
base_cam = camera.location.copy()
base_obj = obj.location.copy()
scene.frame_start = 1
scene.frame_end = config["total_frames"]
scene.render.fps = config["fps"]
scene.render.resolution_x = 360
scene.render.resolution_y = 640
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = config["frame_prefix"]
camera.location = base_cam
obj.location = base_obj
camera.keyframe_insert(data_path="location", frame=1)
obj.keyframe_insert(data_path="location", frame=1)
for segment in config["segments"]:
    frame = segment["end_frame"]
    camera.location = base_cam.copy()
    camera.location.x += segment["camera_x"]
    obj.location = base_obj.copy()
    obj.location.x += segment["object_x"]
    camera.keyframe_insert(data_path="location", frame=frame)
    obj.keyframe_insert(data_path="location", frame=frame)
# Bake per-frame framing corrections after tracking constraints are evaluated.
# Object bounds are projected into normalized camera coordinates.
# If the subject does not fit, widen the lens within safe limits.
def visibility_blocker(eye, evaluated_subject, depsgraph):
    """Check sampled evaluated mesh surface and projected silhouette for occlusion.

    Bounding-box corners alone do not represent the surface of rounded meshes.
    The returned name is diagnostic; a clear result is not a pixel-level proof.
    """
    matrix = evaluated_subject.matrix_world
    center = matrix.translation.copy()
    points = [center]
    if evaluated_subject.type == "MESH":
        mesh = evaluated_subject.to_mesh()
        try:
            vertices = mesh.vertices
            if vertices:
                # Sample up to 96 deterministic surface vertices per evaluation.
                stride = max(1, len(vertices) // 96)
                points.extend(matrix @ vertices[i].co for i in range(0, len(vertices), stride))
        finally:
            evaluated_subject.to_mesh_clear()
    else:
        corners = [matrix @ Vector(corner) for corner in evaluated_subject.bound_box]
        points.extend(center.lerp(corner, 0.75) for corner in corners)
    for point in points:
        direction = point - eye
        distance = direction.length
        if distance <= 1e-5:
            return "camera overlaps subject"
        hit, _, _, _, blocker, _ = scene.ray_cast(
            depsgraph, eye, direction.normalized(),
            distance=max(0.0, distance - 1e-3))
        if hit and blocker is not None and blocker.original != obj:
            return blocker.name
    return None

scene.view_layers.update()
margin = 0.08
min_lens = 18.0
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    camera.data.lens = config["camera_lens_mm"]
    scene.view_layers.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    world_corners = [evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box]
    # Include evaluated mesh origin for very small/degenerate bounds.
    world_corners.append(evaluated.matrix_world.translation.copy())
    for _ in range(28):
        scene.view_layers.update()
        coords = [world_to_camera_view(scene, camera, corner) for corner in world_corners]
        fits = all(margin <= p.x <= 1 - margin and
                   margin <= p.y <= 1 - margin and p.z > 0 for p in coords)
        if fits:
            break
        if camera.data.lens <= min_lens:
            raise RuntimeError("Subject cannot fit inside camera frame at frame %d" % frame)
        camera.data.lens = max(min_lens, camera.data.lens * 0.90)
    camera.data.keyframe_insert(data_path="lens", frame=frame)
    # Detect foreground occlusion that camera projection alone cannot catch.
    # This is a conservative geometric check, not an image-based visual test.
    scene.view_layers.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    camera_eval = camera.evaluated_get(depsgraph)
    eye = camera_eval.matrix_world.translation.copy()
    subject_center = evaluated.matrix_world.translation.copy()
    ray = subject_center - eye
    distance = ray.length
    if distance <= 1e-5:
        raise RuntimeError("Camera overlaps subject at frame %d" % frame)
    blocker_name = visibility_blocker(eye, evaluated, depsgraph)
    if blocker_name is not None:
        # Try bounded lateral/elevated alternatives, retaining TRACK_TO.
        # Use the preceding corrected position to reduce camera jumps.
        original_eye = camera.location.copy()
        chosen = None
        for side, rise in (
            (0.0, 0.6), (0.7, 0.0), (-0.7, 0.0),
            (1.4, 0.4), (-1.4, 0.4), (0.0, 1.5),
            (2.4, 0.8), (-2.4, 0.8), (0.0, 2.8),
        ):
            camera.location = original_eye + Vector((side, 0.0, rise))
            scene.view_layers.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()
            eye2 = camera.evaluated_get(depsgraph).matrix_world.translation.copy()
            direction = subject_center - eye2
            length = direction.length
            if length <= 1e-5:
                continue
            if visibility_blocker(eye2, evaluated, depsgraph) is not None:
                continue
            projected = [world_to_camera_view(scene, camera, corner)
                         for corner in world_corners]
            if all(margin <= p.x <= 1 - margin and
                   margin <= p.y <= 1 - margin and p.z > 0
                   for p in projected):
                chosen = camera.location.copy()
                break
        if chosen is None:
            raise RuntimeError(
                "Subject occluded at frame %d by %s; no safe camera position found" %
                (frame, blocker_name))
        camera.location = chosen
    # Keyframe the corrected path; validate every frame again after baking.
    camera.keyframe_insert(data_path="location", frame=frame)
# Smooth the baked path conservatively: accept each local average only if
# the target remains inside the frame and the sight line stays unobstructed.
# Rejected candidates retain their previously validated camera position.
positions = {}
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    positions[frame] = camera.location.copy()
for _pass in range(2):
    revised = {f: pos.copy() for f, pos in positions.items()}
    for frame in range(scene.frame_start + 1, scene.frame_end):
        candidate = (positions[frame - 1] + 2 * positions[frame] +
                     positions[frame + 1]) / 4
        scene.frame_set(frame)
        camera.location = candidate
        scene.view_layers.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        subject = obj.evaluated_get(depsgraph)
        eye = camera.evaluated_get(depsgraph).matrix_world.translation.copy()
        center = subject.matrix_world.translation.copy()
        direction = center - eye
        if direction.length <= 1e-5:
            continue
        if visibility_blocker(eye, subject, depsgraph) is not None:
            continue
        corners = [subject.matrix_world @ Vector(corner)
                   for corner in subject.bound_box]
        projected = [world_to_camera_view(scene, camera, point)
                     for point in corners]
        if all(margin <= p.x <= 1 - margin and
               margin <= p.y <= 1 - margin and p.z > 0
               for p in projected):
            revised[frame] = candidate.copy()
    positions = revised
# Remove camera location curves before baking the accepted per-frame path.
# Otherwise earlier segment keys can distort the smoothed motion.
if camera.animation_data and camera.animation_data.action:
    action = camera.animation_data.action
    if hasattr(action, "fcurves"):
        for curve in list(action.fcurves):
            if curve.data_path == "location":
                action.fcurves.remove(curve)
for frame, position in positions.items():
    scene.frame_set(frame)
    camera.location = position
    camera.keyframe_insert(data_path="location", frame=frame)
# Second pass catches new occlusions introduced by keyframe interpolation.
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    scene.view_layers.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eye = camera.evaluated_get(depsgraph).matrix_world.translation.copy()
    center = obj.evaluated_get(depsgraph).matrix_world.translation.copy()
    direction = center - eye
    if direction.length <= 1e-5:
        raise RuntimeError("Camera overlaps subject at frame %d" % frame)
    subject = obj.evaluated_get(depsgraph)
    corners = [subject.matrix_world @ Vector(corner) for corner in subject.bound_box]
    projected = [world_to_camera_view(scene, camera, point) for point in corners]
    if not all(margin <= p.x <= 1 - margin and
               margin <= p.y <= 1 - margin and p.z > 0 for p in projected):
        raise RuntimeError("Camera framing invalid after baking at frame %d" % frame)
    blocker_name = visibility_blocker(eye, subject, depsgraph)
    if blocker_name is not None:
        raise RuntimeError("Camera path still occluded at frame %d by %s" %
                           (frame, blocker_name))
# Preserve the frame-1 camera settings in the saved file.
scene.frame_set(scene.frame_start)
bpy.ops.wm.save_as_mainfile(filepath=config["blend_output"])
bpy.ops.render.render(animation=True)
print("MULTISCENE_RENDER_COMPLETED")
'''


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a fixed local multi-scene Blender timeline")
    parser.add_argument("--source", required=True, help="Existing .blend scene")
    parser.add_argument("--output", required=True, help="New output directory")
    parser.add_argument("--object", default="Animation_Test_Object")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--camera-lens-mm", type=float, default=60.0,
                        help="Camera focal length in millimeters (18-100)")
    parser.add_argument("--blender")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    if not source.is_file() or source.suffix.lower() != ".blend":
        parser.error("--source must be an existing .blend file")
    if output.exists():
        parser.error("--output must be a new directory (no overwriting)")
    if not 18.0 <= args.camera_lens_mm <= 100.0:
        parser.error("--camera-lens-mm must be between 18 and 100")
    if not args.object or len(args.object) > 100:
        parser.error("invalid object name")
    blender = Path(args.blender).resolve() if args.blender else find_blender_executable()
    if blender is None or not blender.is_file():
        parser.error("Blender executable not found")
    timeline = compile_timeline([
        Segment("establish", 2, camera_dx=0.5),
        Segment("object_moves", 2, object_dx=1.5),
        Segment("follow", 2, camera_dx=0.3, object_dx=1),
    ], fps=args.fps)
    output.mkdir(parents=True)
    frames = output / "frames"
    frames.mkdir()
    config = {
        "source": str(source), "object_name": args.object,
        "camera_lens_mm": args.camera_lens_mm,
        "fps": args.fps, "total_frames": timeline[-1].end_frame,
        "segments": [vars(s) for s in timeline],
        "frame_prefix": str(frames / "frame_"),
        "blend_output": str(output / "multiscene.blend"),
    }
    with tempfile.TemporaryDirectory(prefix=".timeline-", dir=output) as temp:
        script = Path(temp) / "render.py"
        manifest = Path(temp) / "config.json"
        script.write_text(BLENDER_SCRIPT, encoding="utf-8")
        manifest.write_text(json.dumps(config), encoding="utf-8")
        subprocess.run([str(blender), "-b", "--disable-autoexec", "--python-exit-code", "1",
                        "--python", str(script), "--", str(manifest)], check=True, timeout=1800)
    subprocess.run([args.ffmpeg, "-nostdin", "-framerate", str(args.fps),
                    "-start_number", "1", "-i", str(frames / "frame_%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y",
                    str(output / "multiscene.mp4")], check=True, timeout=300)
    if not (output / "multiscene.mp4").is_file():
        raise RuntimeError("MP4 output is missing")
    print(json.dumps({"status": "completed", "video": str(output / "multiscene.mp4"),
                      "blend": config["blend_output"], "frames": timeline[-1].end_frame}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
