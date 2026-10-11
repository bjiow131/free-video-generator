"""Regression coverage for both remote patch channels and isolated test commits."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_agent.patch_validation import PatchValidationError, validate_patch_paths
from local_agent.control_protocol import ProtocolError, parse_task


def _task(patch: str) -> str:
    now = datetime.now(timezone.utc)
    return json.dumps({
        "protocol_version": 1, "task_id": "patch-verify-01",
        "operation": "apply_patch",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "requires_local_approval": True,
        "arguments": {"patch": patch},
    })


def test_plain_text_patch_and_direct_mailbox_task_accepted():
    patch = (
        "diff --git a/tests/test_extra.py b/tests/test_extra.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/tests/test_extra.py\n"
        "@@ -0,0 +1 @@\n"
        "+def test_ok(): assert True\n"
    )
    validate_patch_paths(patch)
    assert parse_task(_task(patch)).operation == "apply_patch"


@pytest.mark.parametrize("patch", [
    "diff --git a/tests/../escape.py b/tests/../escape.py\n",
    "diff --git a/tests/.GIT/config b/tests/.GIT/config\n",
    "diff --git a/tests/sub/.gitattributes b/tests/sub/.gitattributes\n",
    "diff --git a/tests/CON.py b/tests/CON.py\n",
    "diff --git a/tests/COM1.txt b/tests/COM1.txt\n",
    "diff --git a/tests/anything. b/tests/anything.\n",
    "diff --git a/.github/workflows/unsafe.yml b/.github/workflows/unsafe.yml\n",
    "diff --git a/tests/a.py b/tests/b.py\n",
    "diff --git a/tests/a.py b/tests/a.py\nrename from tests/a.py\n",
    "diff --git a/tests/a.py b/tests/a.py\nnew file mode 100755\n",
    "diff --git a/tests/a.py b/tests/a.py\nnew file mode 120000\n",
    "diff --git a/tests/a.py b/tests/a.py\nold mode 100644\nnew mode 100755\n",
    "diff --git a/tests/a.py b/tests/a.py\nGIT binary patch\n",
    "diff --git a/tests/a.py b/tests/a.py\n--- a/tests/a.py\n+++ b/docs/other.py\n",
    "diff --git a/tests/a.py b/tests/a.py\n--- a/tests/a.py\n+++ b/unknown/file.py\n",
    "diff --git a/tests/a.py b/tests/a.py\n--- a/tests/a.py\n+++ b/tests/a.py\n@@ -1 +1 @@\n+\x1b[31munsafe\n",
])
def test_unsafe_patches_rejected_by_both_entry_points(patch):
    with pytest.raises(PatchValidationError):
        validate_patch_paths(patch)
    with pytest.raises(ProtocolError):
        parse_task(_task(patch))


def test_plain_hunk_content_is_not_interpreted_as_file_header():
    patch = (
        "diff --git a/tests/extra.py b/tests/extra.py\n"
        "--- a/tests/extra.py\n"
        "+++ b/tests/extra.py\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "++++ b/unknown/file.py\n"
    )
    validate_patch_paths(patch)


@pytest.mark.parametrize("test_modifies_index", [False, True])
def test_patch_tests_cannot_silently_change_committed_content(tmp_path, monkeypatch, test_modifies_index):
    from local_agent import poller

    root = tmp_path / "source"
    root.mkdir()

    def git(*args, cwd=None):
        return subprocess.run(
            ["git", *args], cwd=cwd or root, check=True,
            capture_output=True, text=True, shell=False,
        )

    git("init", "-b", "main")
    git("config", "user.name", "Patch Test")
    git("config", "user.email", "patch-test@example.invalid")
    (root / "tests").mkdir()
    (root / "tests" / "file.txt").write_text("base\n", encoding="utf-8")
    git("add", "tests/file.txt")
    git("commit", "-m", "base")
    base_commit = git("rev-parse", "HEAD").stdout.strip()

    patch = (
        "diff --git a/tests/file.txt b/tests/file.txt\n"
        "--- a/tests/file.txt\n"
        "+++ b/tests/file.txt\n"
        "@@ -1 +1 @@\n"
        "-base\n"
        "+approved\n"
    )
    monkeypatch.setattr(poller, "ROOT", root)
    original_run = subprocess.run

    def fake_run(args, **kwargs):
        if args[:3] == [sys.executable, "-m", "pytest"]:
            worktree = Path(kwargs["cwd"])
            (worktree / "tests" / "file.txt").write_text("unapproved\n", encoding="utf-8")
            if test_modifies_index:
                original_run(["git", "add", "--", "tests/file.txt"], cwd=worktree, check=True)
            return SimpleNamespace(returncode=0, stdout="tests pass", stderr="")
        return original_run(args, **kwargs)

    monkeypatch.setattr(poller.subprocess, "run", fake_run)
    result = poller._apply_patch(patch, "reject-test-side-effects", expected_base_sha=base_commit)

    assert result["status"] == "failed_rolled_back", result
    assert result["reason"] == "post_patch_tests_modified_worktree_or_index"
    assert result["rollback_verified"] is True
    assert git("rev-parse", "HEAD").stdout.strip() == base_commit
    assert (root / "tests" / "file.txt").read_text(encoding="utf-8") == "base\n"
