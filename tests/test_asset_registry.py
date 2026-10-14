from __future__ import annotations
import json
from pathlib import Path
import pytest
from local_agent.asset_registry import AssetRegistryError, read_asset_registry, scan_project_assets
def test_scans_supported_files_without_opening_them(tmp_path:Path):
    project=tmp_path/"mia"; (project/"assets").mkdir(parents=True)
    (project/"assets"/"Mia_reference_model.blend").write_bytes(b"placeholder")
    (project/"assets"/"snail.png").write_bytes(b"placeholder")
    (project/"assets"/"notes.py").write_text("print('not an asset')",encoding="utf-8")
    result=scan_project_assets(tmp_path,"mia")
    assert result["asset_count"]==2 and result["uploaded"] is False
    registry=json.loads((project/"asset_registry.json").read_text(encoding="utf-8"))
    assert {x["asset_id"] for x in registry["assets"]}=={"Mia_reference_model","snail"}
    assert read_asset_registry(project,"mia")["snail"]["path"]=="assets/snail.png"
def test_duplicate_asset_ids_are_excluded(tmp_path:Path):
    assets=tmp_path/"mia"/"assets"; (assets/"characters").mkdir(parents=True); (assets/"props").mkdir()
    (assets/"characters"/"Mia.blend").write_bytes(b"a"); (assets/"props"/"Mia.fbx").write_bytes(b"b")
    scan_project_assets(tmp_path,"mia")
    assert json.loads((tmp_path/"mia"/"asset_registry.json").read_text(encoding="utf-8"))["asset_count"]==0
def test_rejects_unsafe_or_missing_project(tmp_path:Path):
    with pytest.raises(AssetRegistryError): scan_project_assets(tmp_path,"../outside")
    with pytest.raises(AssetRegistryError): scan_project_assets(tmp_path,"mia")
def test_registry_ignores_missing_files_after_scan(tmp_path:Path):
    assets=tmp_path/"mia"/"assets"; assets.mkdir(parents=True); target=assets/"snail.glb"; target.write_bytes(b"placeholder")
    scan_project_assets(tmp_path,"mia"); target.unlink()
    assert read_asset_registry(tmp_path/"mia","mia")=={}
def test_rejects_project_symlink(tmp_path:Path):
    outside=tmp_path.parent/(tmp_path.name+"_outside"); outside.mkdir()
    try:
        (tmp_path/"mia").symlink_to(outside,target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform")
    with pytest.raises(AssetRegistryError,match="symlink"): scan_project_assets(tmp_path,"mia")
