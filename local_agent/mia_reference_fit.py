"""Measured, non-destructive reference fitting primitives for Mia.

This module deliberately has no Blender or SciPy import at module load time so
the schema, scoring, and quality gates can be tested on a regular Python.
Blender integration is expected to use a copy of the source .blend file.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
from typing import Callable, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,99}$")


class ReferenceFitError(ValueError):
    """A reference map or fit request is incomplete or invalid."""


@dataclass(frozen=True)
class Landmark:
    name: str
    object_name: str
    vertex_index: int
    target: tuple[float, float]
    confidence: float = 1.0
    visible: bool = True


@dataclass(frozen=True)
class View:
    name: str
    camera_name: str
    landmarks: tuple[Landmark, ...]


@dataclass(frozen=True)
class Parameter:
    """One bounded, named shape-key control on a candidate copy."""
    name: str
    object_name: str
    key_name: str
    initial: float
    lower: float
    upper: float
    regularization: float = 0.0


@dataclass(frozen=True)
class ReferenceMap:
    reference_sha256: str
    views: tuple[View, ...]
    parameters: tuple[Parameter, ...]


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def parse_reference_map(value: object, *, expected_sha256: str | None = None) -> ReferenceMap:
    """Validate a hand-measured map; invisible/occluded landmarks are excluded."""
    if not isinstance(value, Mapping) or isinstance(value.get("schema_version"), bool) or value.get("schema_version") != SCHEMA_VERSION:
        raise ReferenceFitError("reference_map_schema_version_must_be_1")
    if value.get("coordinate_convention") != "camera_frame_bottom_left_normalized":
        raise ReferenceFitError("coordinate_convention_must_be_camera_frame_bottom_left_normalized")
    digest = value.get("reference_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ReferenceFitError("reference_sha256_must_be_lowercase_sha256")
    if expected_sha256 is not None and digest != expected_sha256:
        raise ReferenceFitError("reference_sha256_does_not_match_approved_reference")
    raw_views = value.get("views")
    if not isinstance(raw_views, list) or len(raw_views) < 2:
        raise ReferenceFitError("at_least_two_fixed_views_required")
    views: list[View] = []
    names: set[str] = set()
    for raw_view in raw_views:
        if not isinstance(raw_view, Mapping):
            raise ReferenceFitError("view_must_be_an_object")
        name, camera = raw_view.get("name"), raw_view.get("camera_name")
        if not isinstance(name, str) or not SAFE_NAME_RE.fullmatch(name) or name in names:
            raise ReferenceFitError("view_names_must_be_safe_and_unique")
        if not isinstance(camera, str) or not SAFE_NAME_RE.fullmatch(camera):
            raise ReferenceFitError("fixed_camera_name_required")
        names.add(name)
        raw_landmarks = raw_view.get("landmarks")
        if not isinstance(raw_landmarks, list):
            raise ReferenceFitError("view_landmarks_must_be_a_list")
        landmarks: list[Landmark] = []
        seen: set[str] = set()
        for raw in raw_landmarks:
            if not isinstance(raw, Mapping):
                raise ReferenceFitError("landmark_must_be_an_object")
            lm_name, obj_name = raw.get("name"), raw.get("object_name")
            if not isinstance(lm_name, str) or not SAFE_NAME_RE.fullmatch(lm_name) or lm_name in seen:
                raise ReferenceFitError("landmark_names_must_be_safe_and_unique_per_view")
            if not isinstance(obj_name, str) or not SAFE_NAME_RE.fullmatch(obj_name):
                raise ReferenceFitError("landmark_object_name_required")
            idx = raw.get("vertex_index")
            if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0:
                raise ReferenceFitError("landmark_vertex_index_must_be_nonnegative_integer")
            xy = raw.get("target")
            if not isinstance(xy, list) or len(xy) != 2 or not all(_finite_number(x) for x in xy):
                raise ReferenceFitError("landmark_target_must_be_finite_normalized_xy")
            if not all(0.0 <= float(x) <= 1.0 for x in xy):
                raise ReferenceFitError("landmark_target_must_be_in_normalized_camera_frame")
            confidence = raw.get("confidence", 1.0)
            visible = raw.get("visible", True)
            if not _finite_number(confidence) or not 0.0 <= float(confidence) <= 1.0:
                raise ReferenceFitError("landmark_confidence_must_be_between_zero_and_one")
            if not isinstance(visible, bool):
                raise ReferenceFitError("landmark_visible_must_be_boolean")
            seen.add(lm_name)
            landmarks.append(Landmark(lm_name, obj_name, idx, (float(xy[0]), float(xy[1])), float(confidence), visible))
        if not any(p.visible and p.confidence > 0 for p in landmarks):
            raise ReferenceFitError("each_view_needs_at_least_one_visible_landmark")
        views.append(View(name, camera, tuple(landmarks)))
    raw_parameters = value.get("parameters", [])
    if not isinstance(raw_parameters, list):
        raise ReferenceFitError("parameters_must_be_a_list")
    parameters: list[Parameter] = []
    pnames: set[str] = set()
    for raw in raw_parameters:
        if not isinstance(raw, Mapping):
            raise ReferenceFitError("parameter_must_be_an_object")
        name, obj_name, key_name = (raw.get(k) for k in ("name", "object_name", "key_name"))
        if any(not isinstance(x, str) or not SAFE_NAME_RE.fullmatch(x) for x in (name, obj_name, key_name)) or name in pnames:
            raise ReferenceFitError("parameter_names_and_shape_key_addresses_must_be_safe")
        initial, lower, upper = (raw.get(k) for k in ("initial", "lower", "upper"))
        reg = raw.get("regularization", 0.0)
        if not all(_finite_number(x) for x in (initial, lower, upper, reg)):
            raise ReferenceFitError("parameter_bounds_and_regularization_must_be_finite")
        if lower > initial or initial > upper or lower == upper or reg < 0:
            raise ReferenceFitError("parameter_bounds_or_regularization_invalid")
        pnames.add(name)
        parameters.append(Parameter(name, obj_name, key_name, float(initial), float(lower), float(upper), float(reg)))
    return ReferenceMap(digest, tuple(views), tuple(parameters))


def normalized_residuals(reference: ReferenceMap, projected: Mapping[tuple[str, str], Sequence[float]], *, parameter_values: Mapping[str, float] | None = None) -> list[float]:
    """Return confidence-weighted residuals across all fixed views."""
    residuals: list[float] = []
    for view in reference.views:
        for lm in view.landmarks:
            if not lm.visible or lm.confidence <= 0:
                continue
            key = (view.name, lm.name)
            if key not in projected:
                raise ReferenceFitError(f"missing_projection:{view.name}:{lm.name}")
            xy = projected[key]
            if len(xy) != 2 or not all(_finite_number(x) for x in xy):
                raise ReferenceFitError(f"invalid_projection:{view.name}:{lm.name}")
            weight = math.sqrt(lm.confidence / 2.0)
            residuals.extend(((float(xy[0]) - lm.target[0]) * weight, (float(xy[1]) - lm.target[1]) * weight))
    if parameter_values is not None:
        for p in reference.parameters:
            if p.regularization:
                if p.name not in parameter_values or not _finite_number(parameter_values[p.name]):
                    raise ReferenceFitError(f"missing_or_invalid_parameter_value:{p.name}")
                residuals.append((float(parameter_values[p.name]) - p.initial) * p.regularization)
    return residuals


def rms_pixel_error(residuals: Iterable[float], frame_width: int, frame_height: int) -> float:
    """RMS of normalized x/y residuals converted to pixels."""
    if frame_width <= 0 or frame_height <= 0:
        raise ReferenceFitError("frame_dimensions_must_be_positive")
    values = list(residuals)
    if not values:
        raise ReferenceFitError("no_visible_residuals")
    if len(values) % 2:
        raise ReferenceFitError("residuals_must_be_xy_pairs")
    pixels = [v * (frame_width if i % 2 == 0 else frame_height) for i, v in enumerate(values)]
    return math.sqrt(sum(v * v for v in pixels) / len(pixels))


def optimize_bounded(initial: Sequence[float], lower: Sequence[float], upper: Sequence[float], residual_fn: Callable[[Sequence[float]], Sequence[float]]) -> dict:
    """Run bounded robust least squares if SciPy is available; else fail clearly."""
    try:
        from scipy.optimize import least_squares
    except ImportError:
        return {"status": "blocked", "reason": "scipy_not_available_in_optimizer_python"}
    if not (len(initial) == len(lower) == len(upper)):
        raise ReferenceFitError("optimizer_vectors_must_have_equal_length")
    if not initial:
        return {"status": "blocked", "reason": "no_parameterized_shape_keys"}
    result = least_squares(lambda x: residual_fn(x), initial, bounds=(lower, upper), loss="soft_l1", f_scale=0.01)
    return {
        "status": "completed" if result.success else "not_converged",
        "parameters": [float(v) for v in result.x],
        "initial_cost": float(result.cost) if result.success else None,
        "evaluations": int(result.nfev),
        "message": str(result.message)[:300],
    }


def quality_gate(before: float, after: float, per_view_before: Mapping[str, float], per_view_after: Mapping[str, float], *, min_relative_gain: float = 0.01, max_view_regression: float = 0.02) -> dict:
    """Accept only all-view improvements; reject a gain paid for by a worse view."""
    if not (_finite_number(before) and _finite_number(after)) or before < 0 or after < 0:
        raise ReferenceFitError("quality_gate_errors_must_be_nonnegative_finite")
    if set(per_view_before) != set(per_view_after) or not per_view_before:
        raise ReferenceFitError("quality_gate_view_sets_must_match_and_be_nonempty")
    regressions = {}
    for name, prior in per_view_before.items():
        current = per_view_after[name]
        if not (_finite_number(prior) and _finite_number(current)) or prior < 0 or current < 0:
            raise ReferenceFitError("per_view_errors_must_be_nonnegative_finite")
        allowance = max(1e-9, float(prior) * max_view_regression)
        if current > prior + allowance:
            regressions[name] = {"before": float(prior), "after": float(current)}
    gain = 0.0 if before == 0 else (before - after) / before
    passed = not regressions and after < before and gain >= min_relative_gain
    return {"status": "accept" if passed else "reject", "before": float(before), "after": float(after), "relative_gain": gain, "regressed_views": regressions}


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_SAFE_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.(?:blend|json)$")
_SAFE_TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


_BLENDER_FIT_SCRIPT = r'''import bpy, json, os, sys, hashlib, math
from bpy_extras.object_utils import world_to_camera_view
args = sys.argv[sys.argv.index("--") + 1:]
source_path, map_path, output_path, report_path, approved_sha = args
def fail(reason, **extra):
    with open(report_path, "w", encoding="utf-8") as f: json.dump({"status":"blocked","reason":reason, **extra},f)
def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
with open(map_path,"r",encoding="utf-8") as f: spec=json.load(f)
if spec.get("schema_version")!=1 or spec.get("reference_sha256")!=approved_sha or len(spec.get("views",[]))<2:
    fail("reference_map_or_approved_sha_mismatch"); raise SystemExit(0)
if not spec.get("parameters"):
    fail("no_parameterized_shape_keys"); raise SystemExit(0)
if os.path.exists(output_path) or os.path.exists(report_path):
    fail("output_exists_no_overwrite"); raise SystemExit(0)
bpy.ops.wm.open_mainfile(filepath=source_path,load_ui=False)
scene=bpy.context.scene; original_camera=scene.camera; source_sha=digest(source_path)
actions_before=sorted((a.name,len(getattr(a,"fcurves",[]))) for a in bpy.data.actions)
drivers_before={o.name:len(o.animation_data.drivers) for o in bpy.data.objects if o.animation_data}
params=[]
for p in spec["parameters"]:
    obj=bpy.data.objects.get(p["object_name"])
    if obj is None or obj.type!="MESH" or obj.data.shape_keys is None:
        fail("shape_key_object_missing",parameter=p.get("name")); raise SystemExit(0)
    key=obj.data.shape_keys.key_blocks.get(p["key_name"])
    if key is None:
        fail("shape_key_missing",parameter=p.get("name")); raise SystemExit(0)
    ad=obj.data.shape_keys.animation_data
    if ad and (ad.drivers or ad.action):
        fail("shape_key_datablock_has_animation_or_drivers",parameter=p.get("name")); raise SystemExit(0)
    initial=float(p["initial"])
    if abs(float(key.value)-initial)>1e-5:
        fail("shape_key_initial_value_mismatch",parameter=p.get("name")); raise SystemExit(0)
    params.append((p,obj,key,initial))
for v in spec["views"]:
    cam=bpy.data.objects.get(v.get("camera_name"))
    if cam is None or cam.type!="CAMERA": fail("fixed_camera_missing",view=v.get("name")); raise SystemExit(0)
    for lm in v["landmarks"]:
        if not lm.get("visible",True) or float(lm.get("confidence",1))<=0: continue
        obj=bpy.data.objects.get(lm.get("object_name")); idx=lm.get("vertex_index")
        if obj is None or obj.type!="MESH" or not isinstance(idx,int) or idx<0 or idx>=len(obj.data.vertices):
            fail("landmark_mesh_or_vertex_missing",view=v.get("name"),landmark=lm.get("name")); raise SystemExit(0)
def measure(values):
    for (_,_,key,_),value in zip(params,values): key.value=float(value)
    bpy.context.view_layer.update(); deps=bpy.context.evaluated_depsgraph_get()
    residual=[]; view_errors={}
    for v in spec["views"]:
        cam=bpy.data.objects[v["camera_name"]]; scene.camera=cam; errors=[]
        for lm in v["landmarks"]:
            confidence=float(lm.get("confidence",1))
            if not lm.get("visible",True) or confidence<=0: continue
            obj=bpy.data.objects[lm["object_name"]]; evaluated=obj.evaluated_get(deps); mesh=evaluated.to_mesh()
            try: point=evaluated.matrix_world @ mesh.vertices[int(lm["vertex_index"])].co; uv=world_to_camera_view(scene,cam,point)
            finally: evaluated.to_mesh_clear()
            dx=float(uv.x)-float(lm["target"][0]); dy=float(uv.y)-float(lm["target"][1])
            if not math.isfinite(dx) or not math.isfinite(dy): raise ValueError("nonfinite_projection")
            w=math.sqrt(confidence/2); residual.extend((dx*w,dy*w))
            errors.append(math.sqrt((dx*scene.render.resolution_x)**2+(dy*scene.render.resolution_y)**2))
        view_errors[v["name"]]=math.sqrt(sum(x*x for x in errors)/len(errors)) if errors else None
    for i,(p,_,_,initial) in enumerate(params):
        reg=float(p.get("regularization",0))
        if reg: residual.append((float(values[i])-initial)*reg)
    return residual,view_errors
initial=[entry[3] for entry in params]
before_res,before_views=measure(initial)
try: from scipy.optimize import least_squares
except ImportError:
    scene.camera=original_camera; fail("scipy_not_available_in_blender_python"); raise SystemExit(0)
lower=[float(p[0]["lower"]) for p in params]; upper=[float(p[0]["upper"]) for p in params]
if any(lo>=hi or val<lo or val>hi for lo,hi,val in zip(lower,upper,initial)):
    scene.camera=original_camera; fail("invalid_parameter_bounds"); raise SystemExit(0)
opt=least_squares(lambda x:measure(x)[0],initial,bounds=(lower,upper),loss="soft_l1",f_scale=.01,max_nfev=80)
after_res,after_views=measure(opt.x)
def rms(xs): return math.sqrt(sum(x*x for x in xs)/len(xs)) if xs else float("inf")
before,after=rms(before_res),rms(after_res); regressions={}
for name,prior in before_views.items():
    now=after_views.get(name)
    if now is None or now>prior+max(1e-6,prior*.02): regressions[name]={"before":prior,"after":now}
gain=0 if before==0 else (before-after)/before
accepted=bool(opt.success and not regressions and after<before and gain>=.01)
for (_,_,key,_),value in zip(params,opt.x if accepted else initial): key.value=float(value)
scene.camera=original_camera; bpy.context.view_layer.update()
actions_after=sorted((a.name,len(getattr(a,"fcurves",[]))) for a in bpy.data.actions)
drivers_after={o.name:len(o.animation_data.drivers) for o in bpy.data.objects if o.animation_data}
if actions_before!=actions_after or drivers_before!=drivers_after:
    fail("animation_or_driver_inventory_changed_unexpectedly"); raise SystemExit(0)
if accepted: bpy.ops.wm.save_as_mainfile(filepath=output_path)
report={"status":"completed" if accepted else "rejected","stage":"projection_optimizer","reason":None if accepted else "quality_gate_rejected","source_sha256":source_sha,"source_sha256_after":digest(source_path),"output_path":output_path if accepted else None,"reference_sha256":approved_sha,"optimized_parameters":[{"name":p[0]["name"],"initial":initial[i],"value":float(opt.x[i]) if accepted else initial[i]} for i,p in enumerate(params)],"optimizer":{"success":bool(opt.success),"evaluations":int(opt.nfev)},"quality_gate":{"status":"accept" if accepted else "reject","before_rms":before,"after_rms":after,"relative_gain":gain,"before_by_view_pixels":before_views,"after_by_view_pixels":after_views,"regressed_views":regressions},"animation_data_preserved":True,"full_render_performed":False}
with open(report_path,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False)
'''


def run_reference_fit(project_name: str, source_blend: str, reference_map_file: str, approved_reference_sha256: str, task_id: str) -> dict:
    """Optimize the original scene in memory and save only an accepted new candidate."""
    if not isinstance(project_name,str) or not _SAFE_PROJECT_RE.fullmatch(project_name):
        return {"status":"rejected","reason":"invalid_project_name"}
    if not isinstance(source_blend,str) or not _SAFE_FILE_RE.fullmatch(source_blend) or not source_blend.lower().endswith(".blend"):
        return {"status":"rejected","reason":"invalid_source_blend_filename"}
    if not isinstance(reference_map_file,str) or not _SAFE_FILE_RE.fullmatch(reference_map_file) or not reference_map_file.lower().endswith(".json"):
        return {"status":"rejected","reason":"invalid_reference_map_filename"}
    if not isinstance(approved_reference_sha256,str) or not SHA256_RE.fullmatch(approved_reference_sha256):
        return {"status":"rejected","reason":"invalid_approved_reference_sha256"}
    if not isinstance(task_id,str) or not _SAFE_TASK_RE.fullmatch(task_id):
        return {"status":"rejected","reason":"invalid_task_id"}
    executable=os.environ.get("BLENDER_EXECUTABLE","").strip(); workspace_value=os.environ.get("LOCAL_AGENT_WORKSPACE","").strip()
    if not executable or not workspace_value:
        return {"status":"blocked","reason":"set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    blender=Path(executable).expanduser().resolve(); workspace=Path(workspace_value).expanduser().resolve()
    if not blender.is_file(): return {"status":"blocked","reason":"blender_executable_not_found"}
    project=(workspace/project_name).resolve()
    if not project.is_relative_to(workspace) or project==workspace or project.is_symlink():
        return {"status":"rejected","reason":"project_outside_workspace_or_linked"}
    source=project/source_blend; reference=project/reference_map_file
    suffix=hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]
    output=project/f"mia_reference_fit_candidate_{suffix}.blend"; report=project/f"mia_reference_fit_result_{suffix}.json"
    if any(p.is_symlink() or getattr(p,"is_junction",lambda:False)() for p in (source,reference,output,report)):
        return {"status":"rejected","reason":"input_or_output_path_must_not_be_linked"}
    if not source.is_file() or source.stat().st_size==0: return {"status":"blocked","reason":"source_blend_not_found"}
    if not reference.is_file() or reference.stat().st_size==0: return {"status":"blocked","reason":"reference_map_not_found"}
    if output.exists() or report.exists(): return {"status":"blocked","reason":"reference_fit_output_exists_no_overwrite"}
    try:
        reference_data=json.loads(reference.read_text(encoding="utf-8"))
        parse_reference_map(reference_data,expected_sha256=approved_reference_sha256)
    except (OSError,ValueError,UnicodeError) as exc:
        return {"status":"rejected","reason":f"invalid_reference_map:{type(exc).__name__}"}
    source_sha=sha256_file(str(source))
    try:
        with tempfile.TemporaryDirectory(prefix=".mia-reference-fit-",dir=project) as temp:
            script=Path(temp)/"reference_fit.py"; script.write_text(_BLENDER_FIT_SCRIPT,encoding="utf-8")
            proc=subprocess.run([str(blender),"--disable-autoexec","--background","--factory-startup","--python",str(script),"--",str(source),str(reference),str(output),str(report),approved_reference_sha256],cwd=str(project),capture_output=True,text=True,timeout=600,check=False,shell=False)
    except subprocess.TimeoutExpired: return {"status":"timeout","reason":"projection_optimizer_timeout"}
    except OSError as exc: return {"status":"error","error_type":type(exc).__name__}
    if proc.returncode!=0 or not report.is_file() or report.stat().st_size==0:
        return {"status":"failed","reason":"blender_reference_fit_failed","return_code":proc.returncode,"stderr_tail":(proc.stderr or "")[-2000:]}
    try: result=json.loads(report.read_text(encoding="utf-8"))
    except (OSError,ValueError): return {"status":"failed","reason":"reference_fit_report_unreadable"}
    if sha256_file(str(source))!=source_sha or result.get("source_sha256_after")!=source_sha:
        return {"status":"failed","reason":"source_blend_changed_during_reference_fit"}
    if result.get("status")=="completed":
        if not output.is_file() or output.stat().st_size==0 or result.get("animation_data_preserved") is not True:
            return {"status":"failed","reason":"candidate_output_or_animation_gate_failed"}
        result["candidate_path"]=str(output)
    result["task_id"] = task_id
    return result
