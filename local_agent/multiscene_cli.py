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
    parser.add_argument("--blender")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    if not source.is_file() or source.suffix.lower() != ".blend":
        parser.error("--source must be an existing .blend file")
    if output.exists():
        parser.error("--output must be a new directory (no overwriting)")
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
