import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aider_factory.cli import _ensure_git_repo
from aider_factory.python.run_workflow import _expand_file_list


class TestWorkflowHardening(unittest.TestCase):
    def test_expand_file_list_scalar_string(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "single_file.py"
            f.write_text("print('hello')", encoding="utf-8")

            res = _expand_file_list("single_file.py", td)
            self.assertEqual(res, ["single_file.py"])

            res_none = _expand_file_list("nonexistent.py", td)
            self.assertEqual(res_none, ["nonexistent.py"])

    def test_expand_file_list_empty_and_list(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(_expand_file_list([], td), [])
            self.assertEqual(_expand_file_list(None, td), [])
            self.assertEqual(
                _expand_file_list(["a.py", "b.py"], td), ["a.py", "b.py"]
            )

    def test_ensure_git_repo_initializes_new_repo(self):
        with tempfile.TemporaryDirectory() as td:
            file_a = Path(td) / "file_a.py"
            file_a.write_text("x = 1\n", encoding="utf-8")
            _ensure_git_repo(td)

            self.assertTrue(os.path.isdir(os.path.join(td, ".git")))
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=td,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertIn("A  file_a.py", status.stdout)

    def test_ensure_git_repo_preserves_existing_staging(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(
                ["git", "init"], cwd=td, capture_output=True, check=False
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=td,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=td,
                capture_output=True,
                check=False,
            )

            init_f = Path(td) / "init.txt"
            init_f.write_text("init\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "init.txt"],
                cwd=td,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=td,
                capture_output=True,
                check=False,
            )

            untracked = Path(td) / "untracked.py"
            untracked.write_text("pass\n", encoding="utf-8")

            _ensure_git_repo(td)

            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=td,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertIn("?? untracked.py", status.stdout)
            self.assertNotIn("A  untracked.py", status.stdout)

    def test_working_directory_fallback_on_invalid_path(self):
        with tempfile.TemporaryDirectory() as td:
            af_dir = Path(td) / ".aider_factory"
            af_dir.mkdir(parents=True, exist_ok=True)
            dummy_py = Path(td) / "dummy.py"
            dummy_py.write_text("x = 1\n", encoding="utf-8")

            env_yml = af_dir / ".env.yml"
            env_yml.write_text(
                """name: "Test Invalid Workdir"
working_directory: "/path/to/nonexistent/directory/that/does/not/exist"
phases:
  - name: "P1"
    enabled: false
""",
                encoding="utf-8",
            )

            res = subprocess.run(
                [sys.executable, "-m", "aider_factory.python.run_workflow"],
                cwd=td,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, f"Failed with: {res.stderr}")


if __name__ == "__main__":
    unittest.main()
