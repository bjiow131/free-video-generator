"""Export Blender animation to MP4 presets for common social platforms."""
from __future__ import annotations
import json, subprocess, tempfile
from pathlib import Path
from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "TikTok": {"resolution": [1080, 1920], "fps": 30, "aspect_ratio": "9:16"},
    "YouTube": {"resolution": [1920, 1080], "fps": 30, "aspect_ratio": "16:9"},
    "YouTube Shorts": {"resolution": [1080, 1920], "fps": 30, "aspect_ratio": "9:16"},
    "Instagram Reels": {"resolution": [1080, 1920], "fps": 30, "aspect_ratio": "9:16"},
}
class VideoExportError(RuntimeError):
    """Video export validation or rendering error."""

_SCRIPT = r'''
import bpy, json, os, sys
args=sys.argv[sys.argv.index("--")+1:]
cfg=json.load(open(args[0],encoding="utf-8"))
scene=bpy.context.scene
if scene.frame_end <= scene.frame_start or not any(o.animation_data and o.animation_data.action for o in bpy.data.objects):
    raise RuntimeError("В проекте не найдена анимация с ключевыми кадрами.")
w,h=cfg["resolution"]
scene.render.resolution_x=w; scene.render.resolution_y=h; scene.render.resolution_percentage=100
scene.render.fps=cfg["fps"]; scene.render.image_settings.file_format="FFMPEG"
scene.render.ffmpeg.format="MPEG4"; scene.render.ffmpeg.codec="H264"
scene.render.ffmpeg.constant_rate_factor="HIGH"; scene.render.ffmpeg.ffmpeg_preset="GOOD"
scene.render.image_settings.color_mode="RGB"; scene.render.filepath=cfg["output_path"]
scene.render.use_file_extension=True; scene.render.use_overwrite=False
scene.frame_set(scene.frame_start)
bpy.ops.render.render(animation=True)
'''

def export_animation_to_mp4(blend_path: str | Path, output_path: str | Path, preset: str,
                            blender_executable: str | Path, timeout_seconds: int = 7200) -> dict[str, Any]:
    if preset not in PRESETS:
        raise VideoExportError("Неизвестный пресет экспорта.")
    blend, out, blender = (Path(x).expanduser().resolve() for x in (blend_path, output_path, blender_executable))
    if not blend.is_file() or blend.suffix.lower() != ".blend":
        raise VideoExportError("Выберите существующий проект Blender (.blend).")
    if not blender.is_file():
        raise VideoExportError("Исполняемый файл Blender не найден.")
    if out.suffix.lower() != ".mp4":
        raise VideoExportError("Для видео выберите расширение .mp4.")
    if out == blend or out.exists():
        raise VideoExportError("Файл назначения уже существует или совпадает с проектом. Выберите другое имя.")
    out.parent.mkdir(parents=True, exist_ok=True)
    log = out.with_name(out.stem + "_export.log")
    cfg = {"output_path": str(out.with_suffix("")), **PRESETS[preset]}
    with tempfile.TemporaryDirectory(prefix=".blender-export-", dir=str(out.parent)) as td:
        script, config = Path(td)/"export.py", Path(td)/"config.json"
        script.write_text(_SCRIPT, encoding="utf-8")
        config.write_text(json.dumps(cfg), encoding="utf-8")
        try:
            with log.open("wb") as stream:
                run = subprocess.run([str(blender), "--background", "--disable-autoexec", str(blend),
                    "--python", str(script), "--", str(config)], cwd=str(out.parent),
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=max(30, min(int(timeout_seconds), 14400)), check=False)
        except subprocess.TimeoutExpired as exc:
            raise VideoExportError("Рендер превысил лимит времени. Лог: " + str(log)) from exc
        except OSError as exc:
            raise VideoExportError("Не удалось запустить Blender.") from exc
    rendered = out if out.is_file() else out.with_suffix(".mp4")
    if run.returncode != 0 or not rendered.is_file() or rendered.stat().st_size < 1024:
        tail = log.read_text(encoding="utf-8", errors="replace")[-2000:] if log.exists() else ""
        raise VideoExportError("Не удалось создать MP4. " + tail)
    return {"status": "completed", "preset": preset, "output_path": str(rendered),
            "blend_path": str(blend), "resolution": cfg["resolution"], "fps": cfg["fps"], "log_path": str(log)}
