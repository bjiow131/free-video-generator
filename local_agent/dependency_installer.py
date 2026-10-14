"""Install only the repository's fixed local-agent requirements file."""
from __future__ import annotations

from importlib import metadata
from pathlib import Path
import subprocess


def install_local_agent_requirements(repo_root: str | Path, python_executable: str | Path) -> dict:
    root = Path(repo_root).resolve(strict=True)
    requirements = root / "requirements-local-agent.txt"
    if requirements.is_symlink() or getattr(requirements, "is_junction", lambda: False)():
        return {"status": "rejected", "reason": "requirements_file_must_not_be_linked"}
    try:
        resolved = requirements.resolve(strict=True)
    except OSError:
        return {"status": "blocked", "reason": "requirements_file_missing"}
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return {"status": "rejected", "reason": "requirements_file_outside_repository"}
    executable = Path(python_executable).resolve(strict=True)
    if not executable.is_file():
        return {"status": "blocked", "reason": "python_executable_missing"}
    try:
        result = subprocess.run(
            [str(executable), "-m", "pip", "install", "-r", str(resolved)],
            cwd=str(root), capture_output=True, text=True, timeout=900, check=False, shell=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "dependency_install_timeout"}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}
    if result.returncode:
        return {"status": "failed", "reason": "pip_install_failed", "return_code": result.returncode}
    installed = {}
    for package, distribution in (("numpy", "numpy"), ("Pillow", "Pillow"), ("scipy", "scipy")):
        try:
            installed[package] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            installed[package] = None
    complete = all(installed.values())
    return {"status": "completed" if complete else "failed",
            "reason": None if complete else "required_analysis_dependency_missing",
            "installed_analysis_packages": installed}
