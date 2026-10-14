"""Strict, non-executable task protocol for the future local control channel.

Security boundary: remote messages are data, never shell commands. This module
validates task envelopes only; it intentionally does not execute tasks.
"""
from __future__ import annotations
from local_agent.path_names import path_identifier_pattern

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import json
import re

from local_agent.patch_validation import PatchValidationError, validate_patch_paths

PROTOCOL_VERSION = 1
ALLOWED_OPERATIONS = frozenset({"status", "doctor", "preflight", "test", "trusted_update_diagnostics", "logs", "start", "stop", "backup", "apply_patch", "blender_forest_preview", "save_story_plan", "compile_story_plan", "scan_project_assets", "blender_knowledge_search", "blender_preflight", "blender_mia_blockout", "blender_open_mia_project", "blender_inspect_mia_project", "blender_mia_skeleton", "blender_mia_spring_rig_transfer", "blender_source_review", "blender_mia_source_adapt", "blender_mia_source_recover", "blender_mia_source_neutral", "blender_mia_source_details", "blender_mia_source_polish", "sync_approved_assets", "export_mia_scene_review", "octava_advice", "mia_model_review", "mia_astra_review", "mia_astra_pass_one", "mia_identity_pass_two", "mia_hair_identity_pass_three", "mia_3d_reconstruction_preflight", "mia_astra_autoloop_100", "mia_astra_autoloop_100_v2", "mia_astra_single_maxfix", "mia_2p5d_prototype"})
TASK_ID_RE = path_identifier_pattern(80, dots=True)
BLENDER_PROJECT_RE = path_identifier_pattern(48)


class ProtocolError(ValueError):
    """Raised when a task envelope is malformed or requests unsafe behavior."""


@dataclass(frozen=True)
class TaskEnvelope:
    protocol_version: int
    task_id: str
    operation: str
    created_at: str
    expires_at: str
    requires_local_approval: bool
    arguments: dict[str, Any]


def parse_task(raw: str, *, max_bytes: int = 65_536) -> TaskEnvelope:
    """Parse a bounded JSON task and reject unknown fields/operations."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > max_bytes:
        raise ProtocolError("Task payload is missing or exceeds the size limit.")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ProtocolError("Task payload must be valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Task envelope must be a JSON object.")

    required = {
        "protocol_version", "task_id", "operation", "created_at",
        "expires_at", "requires_local_approval", "arguments",
    }
    if set(value) != required:
        raise ProtocolError("Task envelope fields do not match protocol version 1.")
    if isinstance(value["protocol_version"], bool) or not isinstance(value["protocol_version"], int) or value["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolError("Unsupported protocol version.")
    if not isinstance(value["task_id"], str) or not TASK_ID_RE.fullmatch(value["task_id"]):
        raise ProtocolError("Invalid task_id.")
    if not isinstance(value["operation"], str) or value["operation"] not in ALLOWED_OPERATIONS:
        raise ProtocolError("Operation is not allowlisted.")
    if not isinstance(value["created_at"], str) or not isinstance(value["expires_at"], str):
        raise ProtocolError("Task timestamps must be strings.")
    try:
        created_at = datetime.fromisoformat(value["created_at"].replace("Z", "+00:00"))
        expires_at = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolError("Task timestamps must use ISO 8601 format.") from exc
    if created_at.tzinfo is None or expires_at.tzinfo is None:
        raise ProtocolError("Task timestamps must include a timezone.")
    if expires_at <= created_at:
        raise ProtocolError("Task expiry must be later than task creation.")
    if (expires_at - created_at).total_seconds() > 86_400:
        raise ProtocolError("Task lifetime may not exceed 24 hours.")
    if not isinstance(value["requires_local_approval"], bool):
        raise ProtocolError("requires_local_approval must be a boolean.")
    if value["requires_local_approval"] is False:
        raise ProtocolError("Task must require local approval; remote approval is disabled.")
    if not isinstance(value["arguments"], dict):
        raise ProtocolError("arguments must be a JSON object.")
    if value["operation"] in {"status", "doctor", "preflight", "test", "trusted_update_diagnostics", "logs", "start", "stop", "backup"} and value["arguments"]:
        raise ProtocolError("This operation does not accept arguments.")
    if len(json.dumps(value["arguments"], ensure_ascii=False).encode("utf-8")) > 49_152:
        raise ProtocolError("Task arguments exceed the size limit.")

    if value["operation"] == "preflight" and value["arguments"]:
        raise ProtocolError("preflight does not accept arguments.")
    if value["operation"] == "apply_patch":
        patch = value["arguments"].get("patch")
        if set(value["arguments"]) != {"patch"} or not isinstance(patch, str):
            raise ProtocolError("apply_patch requires exactly one string field named patch.")
        if len(patch.encode("utf-8")) > 40_000 or not patch.startswith("diff --git "):
            raise ProtocolError("Patch is missing a git diff header or exceeds the size limit.")
        try:
            validate_patch_paths(patch)
        except PatchValidationError as exc:
            raise ProtocolError(str(exc)) from exc

    if value["operation"] == "blender_forest_preview":
        args = value["arguments"]
        allowed_args = {"project_name", "render", "preview", "cycles"}
        if set(args) - allowed_args or "project_name" not in args:
            raise ProtocolError("blender_forest_preview accepts project_name and optional render/preview/cycles booleans only.")
        if not isinstance(args["project_name"], str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("Blender project_name must use 1-49 letters, digits, underscores, or hyphens.")
        for flag in ("render", "preview", "cycles"):
            if flag in args and not isinstance(args[flag], bool):
                raise ProtocolError(f"Blender argument {flag} must be a boolean.")

    if value["operation"] == "blender_preflight":
        if value["arguments"]:
            raise ProtocolError("blender_preflight does not accept arguments.")
    if value["operation"] == "blender_inspect_mia_project":
        args = value["arguments"]
        if set(args) != {"project_name"} or not isinstance(args.get("project_name"), str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("blender_inspect_mia_project requires only a safe project_name.")
    if value["operation"] == "blender_open_mia_project":
        args = value["arguments"]
        if set(args) != {"project_name"} or not isinstance(args.get("project_name"), str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("blender_open_mia_project requires only a safe project_name.")
    if value["operation"] == "blender_mia_blockout":
        args = value["arguments"]
        allowed = {"project_name", "duration_seconds", "overwrite", "allow_full_render"}
        if set(args) - allowed or not isinstance(args.get("project_name"), str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("blender_mia_blockout requires a safe project_name and fixed render options.")
        duration = args.get("duration_seconds", 5)
        if type(duration) is not int or duration not in (5, 60):
            raise ProtocolError("Duration must be 5 or 60 seconds.")
        for flag in ("overwrite", "allow_full_render"):
            if flag in args and type(args[flag]) is not bool:
                raise ProtocolError("Render flags must be booleans.")
        if args.get("overwrite", False) and args["project_name"] != "S01E01_SC01_RELEASE":
            raise ProtocolError("Overwrite is restricted to the fixed Episode 1 release.")
        if duration == 60 and (args["project_name"] != "S01E01_SC01_RELEASE" or not args.get("allow_full_render", False)):
            raise ProtocolError("60-second release requires explicit full render permission.")
        if duration == 5 and args.get("allow_full_render", False):
            raise ProtocolError("Full render permission is only valid for 60 seconds.")
    if value["operation"] == "export_mia_scene_review":
        args = value["arguments"]
        if set(args) != {"project_name"} or args.get("project_name") != "S01E01_SC01_DRAFT":
            raise ProtocolError("export_mia_scene_review accepts only the fixed Episode 1 draft project.")

    if value["operation"] in {"blender_mia_source_neutral","blender_mia_source_details"}:
        args=value["arguments"]
        if (set(args)!={"source_project","project_name"} or any(not isinstance(args.get(k),str)
                or not BLENDER_PROJECT_RE.fullmatch(args[k]) for k in ("source_project","project_name"))
                or args["source_project"]==args["project_name"]):
            raise ProtocolError("Neutral copy accepts two distinct safe project names.")
    if value["operation"] == "blender_mia_source_polish":
        args=value["arguments"]
        required={"source_project","project_name"}
        allowed=required|{"profile"}
        if (not required.issubset(args) or set(args)-allowed
                or any(not isinstance(args.get(k),str) or not BLENDER_PROJECT_RE.fullmatch(args[k])
                       for k in ("source_project","project_name"))
                or args["source_project"]==args["project_name"]
                or args.get("profile","face") not in {"face","head_jacket","face_and_fit","eyes","proportions","reference_fit"}):
            raise ProtocolError("Mia polish accepts safe project names and one fixed profile name.")
    if value["operation"] == "blender_mia_source_recover":
        args=value["arguments"]
        if (set(args)!={"project_name","source_task_id"} or not isinstance(args.get("project_name"),str)
                or not BLENDER_PROJECT_RE.fullmatch(args["project_name"])
                or not isinstance(args.get("source_task_id"),str) or not TASK_ID_RE.fullmatch(args["source_task_id"])):
            raise ProtocolError("Source recovery accepts a safe project and original immutable task ID.")
    if value["operation"] == "blender_mia_source_adapt":
        args = value["arguments"]
        if (set(args) != {"project_name"} or not isinstance(args.get("project_name"), str)
                or not BLENDER_PROJECT_RE.fullmatch(args["project_name"])):
            raise ProtocolError("Source adaptation accepts only a safe project_name.")
    if value["operation"] == "blender_source_review":
        args = value["arguments"]
        if (set(args) != {"asset", "project_name"}
                or not isinstance(args.get("asset"), str)
                or args.get("asset") not in {"spring", "tiby_female"}
                or not isinstance(args.get("project_name"), str)
                or not BLENDER_PROJECT_RE.fullmatch(args["project_name"])):
            raise ProtocolError("Source review accepts a fixed asset and safe project_name only.")
    if value["operation"] == "blender_mia_spring_rig_transfer":
        args = value["arguments"]
        if set(args) != {"project_name"} or not isinstance(args.get("project_name"), str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("blender_mia_spring_rig_transfer requires only a safe project_name.")
    if value["operation"] == "blender_mia_skeleton":
        args = value["arguments"]
        if set(args) != {"project_name"} or not isinstance(args.get("project_name"), str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("blender_mia_skeleton requires only a safe project_name.")
    if value["operation"] == "blender_knowledge_search":
        args = value["arguments"]
        if set(args) - {"query", "limit"} or not isinstance(args.get("query"), str):
            raise ProtocolError("blender_knowledge_search requires a query string and optional limit.")
        if not args["query"].strip() or len(args["query"]) > 1000:
            raise ProtocolError("Blender knowledge query must contain 1-1000 characters.")
        limit = args.get("limit", 5)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
            raise ProtocolError("Blender knowledge limit must be an integer from 1 to 10.")
    if value["operation"] == "scan_project_assets":
        args = value["arguments"]
        if set(args) != {"project_name"} or not isinstance(args.get("project_name"), str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("scan_project_assets requires only a safe project_name.")
    if value["operation"] == "compile_story_plan":
        args = value["arguments"]
        if set(args) != {"project_name"} or not isinstance(args.get("project_name"), str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("compile_story_plan requires only a safe project_name.")
    if value["operation"] == "save_story_plan":
        args = value["arguments"]
        if set(args) != {"story_plan"} or not isinstance(args["story_plan"], dict):
            raise ProtocolError("save_story_plan requires exactly one object field named story_plan.")
        if len(json.dumps(args["story_plan"], ensure_ascii=False).encode("utf-8")) > 48_000:
            raise ProtocolError("Story plan exceeds the 48 KB limit.")
        plan = args["story_plan"]
        if isinstance(plan.get("schema_version"), bool) or not isinstance(plan.get("schema_version"), int) or plan.get("schema_version") != 1:
            raise ProtocolError("Unsupported story plan schema_version.")
        project_name = plan.get("project_name")
        if not isinstance(project_name, str) or not BLENDER_PROJECT_RE.fullmatch(project_name):
            raise ProtocolError("Story plan project_name must use 1-48 letters, digits, underscores, or hyphens.")
    if value["operation"] == "mia_2p5d_prototype" and value["arguments"] != {}:
        raise ProtocolError("2.5D Mia prototype takes no remote paths, scripts, or arguments.")
    if value["operation"] == "mia_astra_single_maxfix" and value["arguments"] != {}:
        raise ProtocolError("Single-pass Mia Astra correction accepts no remote arguments or scripts.")
    if value["operation"] == "mia_astra_autoloop_100_v2" and value["arguments"] != {}:
        raise ProtocolError("Mia 100-cycle V2 accepts no arbitrary scripts, paths or arguments.")
    if value["operation"] == "mia_astra_autoloop_100" and value["arguments"] != {}:
        raise ProtocolError("Autonomous 100-cycle Mia task takes no remote arguments or scripts.")
    if value["operation"] == "mia_3d_reconstruction_preflight" and value["arguments"] != {}:
        raise ProtocolError("3D reconstruction preflight accepts no arguments or code.")
    if value["operation"] == "mia_hair_identity_pass_three" and value["arguments"] != {}:
        raise ProtocolError("Hair pass 3 cannot receive arbitrary paths, code or arguments.")
    if value["operation"] == "mia_identity_pass_two" and value["arguments"] != {}:
        raise ProtocolError("mia_identity_pass_two accepts no arbitrary paths, scripts or arguments.")
    if value["operation"] == "mia_astra_pass_one" and value["arguments"] != {}:
        raise ProtocolError("mia_astra_pass_one accepts no parameters, code, paths or media.")
    if value["operation"] == "mia_astra_review":
        args = value["arguments"]
        if (set(args) != {"project_name"} or not isinstance(args.get("project_name"), str)
                or not BLENDER_PROJECT_RE.fullmatch(args["project_name"])):
            raise ProtocolError("mia_astra_review requires only a safe project_name.")
    if value["operation"] == "mia_model_review" and value["arguments"] != {}:
        raise ProtocolError("mia_model_review accepts no parameters, code, paths or media.")
    if value["operation"] == "octava_advice":
        args = value["arguments"]
        tier = args.get("tier", "default")
        if type(tier) is not str or tier not in ("default", "simple", "complex"):
            raise ProtocolError("octava_advice tier must be default, simple, or complex.")
        fields = set(args) - {"tier"}
        prompt = args.get("prompt")
        project_id = args.get("project_id")
        if fields == {"prompt"}:
            if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 1600:
                raise ProtocolError("octava_advice requires a 1-1600 character prompt.")
        elif fields == {"prompt", "project_id"}:
            if (not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 1600
                    or not isinstance(project_id, str) or not BLENDER_PROJECT_RE.fullmatch(project_id)):
                raise ProtocolError("octava_advice requires a safe project_id and 1-1600 character prompt.")
        elif fields == {"project_id", "resume_pending"}:
            if (not isinstance(project_id, str) or not BLENDER_PROJECT_RE.fullmatch(project_id)
                    or args.get("resume_pending") is not True):
                raise ProtocolError("Invalid octava_advice project resume request.")
        else:
            raise ProtocolError("octava_advice accepts prompt, optional project_id, or project resume.")

    # The initial protocol allows no free-form command, script, URL, or executable path.
    forbidden_keys = {"command", "cmd", "shell", "script", "executable", "url", "powershell"}
    if any(str(key).lower() in forbidden_keys for key in value["arguments"]):
        raise ProtocolError("Free-form command and executable fields are prohibited.")

    return TaskEnvelope(
        protocol_version=value["protocol_version"],
        task_id=value["task_id"],
        operation=value["operation"],
        created_at=value["created_at"],
        expires_at=value["expires_at"],
        requires_local_approval=value["requires_local_approval"],
        arguments=value["arguments"],
    )
