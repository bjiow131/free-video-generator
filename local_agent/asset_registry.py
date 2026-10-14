"""Local-only, non-executing index of approved project assets."""
from __future__ import annotations
import json, os, re
from pathlib import Path
from typing import Any
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
_ALLOWED_EXTENSIONS = {".blend",".obj",".fbx",".glb",".gltf",".stl",".abc",".usd",".usdz",".png",".jpg",".jpeg",".webp",".tif",".tiff",".wav",".mp3",".ogg",".flac"}
_MAX_ASSETS = 5000
class AssetRegistryError(ValueError):
    """An asset inventory could not be safely created or read."""
def scan_project_assets(workspace: str | Path, project_name: str) -> dict[str, Any]:
    """Index supported regular files under project/assets; never opens or executes assets."""
    if not isinstance(project_name,str) or not _PROJECT_RE.fullmatch(project_name): raise AssetRegistryError("Invalid project name.")
    root=Path(workspace).expanduser().resolve(); project=root/project_name
    if project.is_symlink() or getattr(project,"is_junction",lambda:False)(): raise AssetRegistryError("Project directory must not be a symlink or junction.")
    project=project.resolve()
    if not project.is_relative_to(root) or not project.is_dir(): raise AssetRegistryError("Project directory is missing or outside the configured workspace.")
    assets_root=project/"assets"
    if assets_root.is_symlink() or getattr(assets_root,"is_junction",lambda:False)(): raise AssetRegistryError("Assets directory must not be a symlink or junction.")
    assets_root.mkdir(parents=True,exist_ok=True); assets_root=assets_root.resolve()
    if not assets_root.is_relative_to(project): raise AssetRegistryError("Assets directory resolves outside the project.")
    entries=[]; seen_ids=set()
    for folder,dirs,files in os.walk(assets_root,followlinks=False):
        base=Path(folder)
        dirs[:]=sorted(d for d in dirs if not (base/d).is_symlink() and not getattr(base/d,"is_junction",lambda:False)())
        for filename in sorted(files):
            path=base/filename
            if path.is_symlink() or getattr(path,"is_junction",lambda:False)() or path.suffix.lower() not in _ALLOWED_EXTENSIONS or not path.is_file(): continue
            resolved=path.resolve()
            if not resolved.is_relative_to(assets_root): continue
            asset_id=path.stem
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}",asset_id): continue
            if asset_id in seen_ids:
                for entry in entries:
                    if entry["asset_id"]==asset_id: entry["ambiguous"]=True
                entries.append({"asset_id":asset_id,"path":resolved.relative_to(project).as_posix(),"extension":path.suffix.lower(),"ambiguous":True})
            else:
                seen_ids.add(asset_id); entries.append({"asset_id":asset_id,"path":resolved.relative_to(project).as_posix(),"extension":path.suffix.lower(),"ambiguous":False})
            if len(entries)>_MAX_ASSETS: raise AssetRegistryError(f"Project contains more than {_MAX_ASSETS} supported asset files.")
    entries=[e for e in entries if not e["ambiguous"]]
    registry={"schema_version":1,"project_name":project_name,"asset_count":len(entries),"assets":entries,"note":"Names and paths only. Files are not loaded, executed, uploaded, or sent to a remote service."}
    destination=project/"asset_registry.json"
    if destination.is_symlink() or getattr(destination,"is_junction",lambda:False)(): raise AssetRegistryError("Registry destination must not be a symlink or junction.")
    temp=project/".asset_registry.json.tmp"
    try:
        with temp.open("x",encoding="utf-8",newline="\n") as stream: json.dump(registry,stream,ensure_ascii=False,indent=2); stream.write("\n")
        os.replace(temp,destination)
    except OSError as exc: raise AssetRegistryError(f"Could not write asset registry ({type(exc).__name__}).") from exc
    finally:
        try: temp.unlink(missing_ok=True)
        except OSError: pass
    return {"status":"completed","project_name":project_name,"asset_count":len(entries),"registry_path":str(destination),"uploaded":False,"asset_files_opened":False}
def read_asset_registry(project_dir: str | Path, project_name: str) -> dict[str, dict[str, Any]]:
    """Read a generated registry and verify every indexed path remains inside assets."""
    project=Path(project_dir).expanduser().resolve(); registry_path=project/"asset_registry.json"
    if registry_path.is_symlink() or not registry_path.is_file(): return {}
    try: data=json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError): return {}
    if not isinstance(data,dict) or data.get("schema_version")!=1 or data.get("project_name")!=project_name or not isinstance(data.get("assets"),list): return {}
    assets_root=(project/"assets").resolve(); result={}
    for entry in data["assets"]:
        if not isinstance(entry,dict) or entry.get("ambiguous") is True: continue
        asset_id,relative=entry.get("asset_id"),entry.get("path")
        if not isinstance(asset_id,str) or not isinstance(relative,str): continue
        relative_path=Path(relative)
        if relative_path.is_absolute() or "\\\\" in relative or any(part in {"", ".", ".."} for part in relative_path.parts): continue
        raw_candidate=project/relative_path
        if not raw_candidate.is_relative_to(assets_root): continue
        current=raw_candidate
        unsafe_component=False
        while current != assets_root:
            if current.is_symlink() or getattr(current,"is_junction",lambda:False)():
                unsafe_component=True
                break
            current=current.parent
        if unsafe_component: continue
        candidate=raw_candidate.resolve()
        if not candidate.is_relative_to(assets_root) or not candidate.is_file() or candidate.suffix.lower() not in _ALLOWED_EXTENSIONS: continue
        if asset_id in result: result.pop(asset_id,None); continue
        result[asset_id]={"asset_id":asset_id,"path":relative,"extension":candidate.suffix.lower()}
    return result
