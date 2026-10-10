"""Interactive, local-only menu for the bounded Blender Work Agent.

This is an orchestration layer for already-implemented, typed capabilities. It
never accepts or executes user-provided Python, shell commands, or remote tasks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from local_agent.asset_registry import scan_project_assets
from local_agent.blender_bridge import BlenderBridge, BlenderBridgeError
from local_agent.blender_knowledge import list_topics, search_knowledge
from local_agent.blender_rigging import create_mia_skeleton
from local_agent.blender_workflow import (
    BlenderWorkflowError,
    create_mia_blockout,
    discover_blender,
    inspect_mia_project,
    open_mia_project,
)
from local_agent.scene_compiler import StoryCompileError, compile_project_story
from local_agent.story_plan import StoryPlanError, save_story_plan

_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")


def _workspace() -> Path:
    value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not value:
        raise RuntimeError("LOCAL_AGENT_WORKSPACE is not configured.")
    root = Path(value).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _project_name() -> str:
    value = input("Project folder name (letters/digits/_/-; default mia_forest): ").strip()
    if not value:
        value = "mia_forest"
    if not _PROJECT_RE.fullmatch(value):
        raise ValueError("Invalid project name. Use 1-48 letters, digits, underscores, or hyphens.")
    return value


def _confirm(action: str) -> bool:
    return input(f"Confirm: {action}? [y/N] ").strip().lower() == "y"


def _print_result(result: Any) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def run_menu_choice(choice: str) -> dict[str, Any] | None:
    """Dispatch one allowlisted menu choice; return None for exit/unknown choices."""
    if choice == "0":
        return {"status": "exit"}
    if choice == "1":
        print(json.dumps(discover_blender(), ensure_ascii=False, indent=2))
        if not _confirm("create a new forest scene and render a preview"):
            return {"status": "cancelled"}
        project = _project_name()
        blender = os.environ.get("BLENDER_EXECUTABLE", "").strip()
        if not blender:
            raise RuntimeError("BLENDER_EXECUTABLE is not configured.")
        bridge = BlenderBridge(blender, _workspace())
        return bridge.run_task("forest_preview", project_name=project)

    if choice == "2":
        if not _confirm("create the editable Mia + yellow scooter + snail blockout"):
            return {"status": "cancelled"}
        project = _project_name()
        return create_mia_blockout(project_name=project, overwrite=False)

    if choice == "3":
        if not _confirm("create a separate experimental skeleton file from an existing Mia blockout"):
            return {"status": "cancelled"}
        project = _project_name()
        return create_mia_skeleton(project)

    if choice == "4":
        project = _project_name()
        if not _confirm(f"open the existing Mia blockout for project {project} in Blender GUI"):
            return {"status": "cancelled"}
        return open_mia_project(project)

    if choice == "5":
        project = _project_name()
        if not _confirm(f"inspect the Mia blockout for project {project} without changing the .blend"):
            return {"status": "cancelled"}
        return inspect_mia_project(project)

    if choice == "6":
        project = _project_name()
        if not _confirm(f"index supported files under {project}/assets (names and paths only)"):
            return {"status": "cancelled"}
        return scan_project_assets(_workspace(), project)

    if choice == "7":
        path_text = input("Path to a JSON story-plan file: ").strip().strip('"')
        if not path_text:
            raise ValueError("A JSON file path is required.")
        source = Path(path_text).expanduser()
        if source.is_symlink() or not source.is_file():
            raise ValueError("Story-plan source must be a regular file, not a symlink.")
        if source.stat().st_size > 48_000:
            raise ValueError("Story-plan JSON exceeds the 48 KB safety limit.")
        data = json.loads(source.read_text(encoding="utf-8-sig"))
        if not _confirm("validate and save this story plan into the local workspace"):
            return {"status": "cancelled"}
        return save_story_plan(_workspace(), data)

    if choice == "8":
        project = _project_name()
        if not _confirm(f"compile and validate the saved story plan for {project} (planning only)"):
            return {"status": "cancelled"}
        return compile_project_story(_workspace(), project)

    if choice == "9":
        print("Available knowledge topics:")
        _print_result(list_topics())
        query = input("Search Blender guidance (Russian or English): ").strip()
        if not query:
            return {"status": "cancelled"}
        return search_knowledge(query)

    return {"status": "invalid_choice", "choice": choice}


def main() -> int:
    menu = (
        ("1", "Create forest scene + PNG preview (visible Blender GUI)"),
        ("2", "Create Mia blockout + scooter + snail"),
        ("3", "Create experimental Mia skeleton (requires blockout)"),
        ("4", "Open an existing Mia blockout in Blender"),
        ("5", "Inspect a Mia blockout (read-only structural report)"),
        ("6", "Index local assets in a project's assets folder"),
        ("7", "Validate and save a story-plan JSON file"),
        ("8", "Compile a saved story plan (planning only, no animation execution)"),
        ("9", "Search built-in Blender knowledge"),
        ("0", "Exit"),
    )
    while True:
        print("\n" + "=" * 58)
        print("BLENDER WORK AGENT — LOCAL ONLY")
        print("No remote queue • no browser control • no arbitrary code execution")
        print("=" * 58)
        for key, label in menu:
            print(f" {key}. {label}")
        choice = input("Select an operation: ").strip()
        try:
            result = run_menu_choice(choice)
            if result is None:
                print("Unknown menu choice.")
                continue
            _print_result(result)
            if choice == "0":
                return 0
        except (
            OSError, ValueError, RuntimeError, json.JSONDecodeError,
            BlenderBridgeError, BlenderWorkflowError, StoryPlanError, StoryCompileError,
        ) as exc:
            print(f"Operation failed safely: {type(exc).__name__}: {exc}")
        input("\nPress Enter to return to the menu...")


if __name__ == "__main__":
    raise SystemExit(main())
