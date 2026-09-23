import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from aider_factory.python.apply_agent import run_apply


class TestE2EApplyAgent(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.old_env = dict(os.environ)

        # 1. Initialize real Git repo
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "AI Factory Test"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@aifactory.local"], cwd=self.test_dir, check=True)

        # 2. Create initial target file and commit
        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        self.target_file = os.path.join(self.test_dir, "src", "math_ops.py")
        with open(self.target_file, "w", encoding="utf-8") as f:
            f.write("def divide(a, b):\n    return a / b\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        # 3. Create mock aider binary in PATH
        self.bin_dir = os.path.join(self.test_dir, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        fake_py = os.path.join(self.bin_dir, "fake_aider.py")
        fake_script = """import sys, subprocess
from pathlib import Path
for arg in sys.argv:
    if arg.endswith(".py") and not arg.startswith("-"):
        with open(arg, "a", encoding="utf-8") as f:
            f.write("\\n# Patched by fake aider\\n")
        subprocess.run(["git", "add", arg], check=True)
        subprocess.run(["git", "commit", "-m", "aider: applied edit"], check=True)
sys.exit(0)
"""
        with open(fake_py, "w", encoding="utf-8") as f:
            f.write(fake_script)

        if sys.platform == "win32":
            with open(os.path.join(self.bin_dir, "aider.cmd"), "w", encoding="utf-8") as f:
                f.write(f'@"{sys.executable}" "%~dp0fake_aider.py" %*\n@exit /b %errorlevel%\n')
        else:
            aider_sh = os.path.join(self.bin_dir, "aider")
            with open(aider_sh, "w", encoding="utf-8") as f:
                f.write(f'#!/bin/sh\n"{sys.executable}" "{fake_py}" "$@"\n')
            os.chmod(aider_sh, 0o755)

        os.environ["PATH"] = f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_live_apply_from_session_history_with_git_diff(self):
        af_dir = os.path.join(self.test_dir, ".aider_factory")
        sess_dir = os.path.join(af_dir, "sessions", "live_session")
        os.makedirs(sess_dir, exist_ok=True)

        history_file = os.path.join(sess_dir, ".aider.chat.history.md")
        with open(history_file, "w", encoding="utf-8") as f:
            f.write("""
#### /ask Add division by zero protection
<think>Checking divide function...</think>
Update divide function to check b == 0.

> Tokens: 500 sent, 50 received. Cost: $0.001 message, $0.001 session.
""")

        os.environ["AI_FACTORY_SESSION"] = "live_session"
        success = run_apply(["src/math_ops.py"], cwd=self.test_dir)
        self.assertTrue(success)

        # Check physical file modification
        with open(self.target_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# Patched by fake aider", content)

        # Verify active_spec was generated
        active_spec = os.path.join(af_dir, "temp", "active_spec.md")
        self.assertTrue(os.path.isfile(active_spec))
        with open(active_spec, "r", encoding="utf-8") as f:
            spec_body = f.read()
        self.assertIn("Update divide function to check b == 0.", spec_body)

    def test_live_apply_with_explicit_spec_file(self):
        spec_path = os.path.join(self.test_dir, "explicit_spec.md")
        with open(spec_path, "w", encoding="utf-8") as f:
            f.write("# Explicit Spec Directives\nAdd logging to divide function.")

        success = run_apply(["src/math_ops.py"], spec_file=spec_path, cwd=self.test_dir, no_diff=True)
        self.assertTrue(success)

        # Check physical file modification
        with open(self.target_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# Patched by fake aider", content)


if __name__ == "__main__":
    unittest.main()
