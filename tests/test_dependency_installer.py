import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_agent.dependency_installer import install_local_agent_requirements


class DependencyInstallerTests(unittest.TestCase):
    def test_installs_only_fixed_requirements_path_without_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements-local-agent.txt").write_text("Pillow\n", encoding="utf-8")
            with patch("local_agent.dependency_installer.subprocess.run") as run:
                run.return_value.returncode = 0
                result = install_local_agent_requirements(root, __import__("sys").executable)
            self.assertEqual(result["status"], "completed")
            args, kwargs = run.call_args
            self.assertEqual(args[0][1:4], ["-m", "pip", "install"])
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["timeout"], 900)

    def test_rejects_missing_and_linked_requirement_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = install_local_agent_requirements(root, __import__("sys").executable)
            self.assertEqual(missing["reason"], "requirements_file_missing")
            target = root / "target.txt"
            target.write_text("Pillow\n", encoding="utf-8")
            link = root / "requirements-local-agent.txt"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            linked = install_local_agent_requirements(root, __import__("sys").executable)
            self.assertEqual(linked["reason"], "requirements_file_must_not_be_linked")


if __name__ == "__main__":
    unittest.main()
