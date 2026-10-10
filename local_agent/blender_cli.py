"""Command-line entry point for the local Blender bridge."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from local_agent.blender_bridge import BlenderBridge, BlenderBridgeError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a constrained local Blender task; no cloud rendering is used."
    )
    parser.add_argument("--blender", default=os.environ.get("BLENDER_EXECUTABLE"),
                        help="Full path to blender.exe (or set BLENDER_EXECUTABLE).")
    parser.add_argument("--workspace", default=os.environ.get("LOCAL_AGENT_WORKSPACE", ""),
                        help="Allowed output workspace (or set LOCAL_AGENT_WORKSPACE).")
    parser.add_argument("--task", choices=("forest-preview",), default="forest-preview")
    parser.add_argument("--project", default="mia_forest",
                        help="Project folder name; letters, digits, underscores, hyphens only.")
    parser.add_argument("--no-render", action="store_true",
                        help="Create and save the .blend file without rendering a PNG.")
    parser.add_argument("--full-preview", action="store_true",
                        help="Render preview at full 720x1280 resolution instead of 50%%.")
    parser.add_argument("--cycles", action="store_true",
                        help="Use Cycles instead of the default Eevee engine.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Explicitly allow replacing this task's known output files.")
    args = parser.parse_args()

    if not args.blender:
        parser.error("Provide --blender or set BLENDER_EXECUTABLE.")
    if not args.workspace:
        parser.error("Provide --workspace or set LOCAL_AGENT_WORKSPACE.")
    try:
        bridge = BlenderBridge(args.blender, args.workspace)
        result = bridge.run_task(
            args.task.replace("-", "_"),
            project_name=args.project,
            render=not args.no_render,
            preview=not args.full_preview,
            cycles=args.cycles,
            overwrite=args.overwrite,
        )
    except BlenderBridgeError as exc:
        print(f"Blender task failed: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
