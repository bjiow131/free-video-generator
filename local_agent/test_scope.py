"""Explicit Blender AI Agent test scope.

This monorepo still contains a separate legacy cloud-video web application.
Do not run the repository-wide pytest suite as an agent diagnostic or as a
pre-merge check for a locally approved Blender-agent patch.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SECURITY_TESTS = (
    "tests/test_github_queue.py",
    "tests/test_repair_channel.py",
    "tests/test_poller.py",
    "tests/test_control_protocol.py",
    "tests/test_patch_validation.py",
    "tests/test_repair_replay.py",
    "tests/test_local_agent_control_protocol.py",
    "tests/test_poller_delivery_state.py",
    "tests/test_mailbox_idle_alerts.py",
    "tests/test_telegram_notification_switch.py",
    "tests/test_octava_studio_http.py",
    "tests/test_result_outbox.py",
    "tests/test_mailbox_policy.py",
    "tests/test_unattended_poller.py",
    "tests/test_trusted_updates.py",
    "tests/test_telegram_supervisor_commands.py",
    "tests/test_octava_credentials.py",
    "tests/test_octava_mailbox.py",
    "tests/test_octava_release_routing.py",
    "tests/test_octava_trusted_delivery.py",
)

BLENDER_TESTS = (
    "tests/test_dialogue_cues.py",
    "tests/test_blender_dialogue.py",
    "tests/test_blender_bridge.py",
    "tests/test_blender_locator.py",
    "tests/test_local_project_runner.py",
    "tests/test_checkpoint_schema.py",
    "tests/test_ffmpeg_media.py",
    "tests/test_local_agent_attachments.py",
    "tests/test_story_plan.py",
    "tests/test_scene_compiler.py",
    "tests/test_asset_registry.py",
    "tests/test_preflight.py",
    "tests/test_notifications.py",
    "tests/test_blender_knowledge.py",
    "tests/test_blender_open_project.py",
    "tests/test_blender_preview_validation.py",
    "tests/test_blender_rigging.py",
    "tests/test_blender_workflow.py",
    "tests/test_error_knowledge.py",
    "tests/test_local_agent_core.py",
    "tests/test_local_agent_examples.py",
    "tests/test_manifest_security.py",
    "tests/test_blender_agent_scope.py",
    "tests/test_studio.py",
    "tests/test_studio_approved_mia_reference.py",
    "tests/test_studio_assembly.py",
    "tests/test_studio_jobs_cancellation.py",
    "tests/test_studio_live_blender.py",
    "tests/test_prompt_pipeline.py",
    "tests/test_multiscene_timeline.py",
    "tests/test_camera_path_planner.py",
    "tests/test_camera_quality.py",
    "tests/test_github_asset_sync.py",
    "tests/test_github_asset_sync_resume.py",
    "tests/test_asset_sync_protocol.py",
    "tests/test_dropbox_review.py",
    "tests/test_mia_3d_reconstruction_preflight.py",
    "tests/test_mia_astra_pass1.py",
    "tests/test_mia_astra_vision.py",
    "tests/test_mia_autoloop_100.py",
    "tests/test_mia_autoloop_v2.py",
    "tests/test_mia_hair_identity_pass3.py",
    "tests/test_mia_identity_shape_pass2.py",
    "tests/test_mia_model_review_delivery.py",
)


TEST_SUITES = {
    "security": SECURITY_TESTS,
    "blender": BLENDER_TESTS,
    "all": SECURITY_TESTS + BLENDER_TESTS,
}


def test_command(suite: str = "all", *, python: str | None = None, root: Path = PROJECT_ROOT) -> list[str]:
    """Build an allowlisted pytest invocation, with no implicit test discovery."""
    if suite not in TEST_SUITES:
        raise ValueError(f"Unknown Blender agent test suite: {suite}")
    selected = TEST_SUITES[suite]
    missing = [name for name in selected if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Blender agent test files are missing: {', '.join(missing)}")
    return [python or sys.executable, "-m", "pytest", "-q", *selected]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Blender agent tests without the legacy web/API suite")
    parser.add_argument("suite", choices=tuple(TEST_SUITES), nargs="?", default="all")
    args = parser.parse_args(argv)
    try:
        command = test_command(args.suite)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False, shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
