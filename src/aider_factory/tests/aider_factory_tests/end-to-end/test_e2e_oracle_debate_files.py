#!/usr/bin/env python3
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


class TestE2EOracleDebateFiles(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        subprocess.run(["git", "init"], cwd=self.temp_dir, capture_output=True, check=False)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=self.temp_dir, capture_output=True, check=False)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.temp_dir, capture_output=True, check=False)

        self.pkg_python_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../python"))
        self.oracle_script = os.path.join(self.pkg_python_dir, "oracle_agent.py")

        # Fake aider binary to intercept architect ask turns
        self.bin_dir = os.path.join(self.temp_dir, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        self.fake_aider = os.path.join(self.bin_dir, "aider.bat" if sys.platform == "win32" else "aider")
        self.prompt_capture = os.path.join(self.temp_dir, "captured_prompt.txt")

        if sys.platform == "win32":
            with open(self.fake_aider, "w", encoding="utf-8") as f:
                f.write(f"@echo off\necho PROPOSAL: fake aider resolution\nexit /b 0\n")
        else:
            with open(self.fake_aider, "w", encoding="utf-8") as f:
                f.write(
                    f"#!/bin/sh\n"
                    f"for arg in \"$@\"; do\n"
                    f"  if [ \"$prev\" = \"--message-file\" ] && [ -f \"$arg\" ]; then\n"
                    f"    cat \"$arg\" > \"{self.prompt_capture}\"\n"
                    f"  fi\n"
                    f"  prev=\"$arg\"\n"
                    f"done\n"
                    f"echo 'PROPOSAL: fake aider resolution'\n"
                    f"exit 0\n"
                )
            os.chmod(self.fake_aider, os.stat(self.fake_aider).st_mode | stat.S_IEXEC)

        self.env = {
            **os.environ,
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "PYTHONPATH": f"{self.pkg_python_dir}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "ORACLE_AGENT_MODEL": "openai/fake-oracle",
            "ORACLE_ARCHITECT_MODEL": "openai/fake-architect",
        }

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_e2e_cli_missing_oracle_file_fast_failure(self):
        """Zero-mock E2E: Missing --oracle-file exits with code 1 and emits error message to stderr."""
        cmd = [sys.executable, self.oracle_script, "--debate", "code", "--oracle-file", "non_existent_rubric.md", "Query"]
        res = subprocess.run(cmd, cwd=self.temp_dir, env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("Oracle instruction file not found: non_existent_rubric.md", res.stderr)

    def test_e2e_cli_missing_architect_file_fast_failure(self):
        """Zero-mock E2E: Missing --architect-file exits with code 1 and emits error message to stderr."""
        cmd = [sys.executable, self.oracle_script, "--debate", "code", "--architect-file", "non_existent_spec.md", "Query"]
        res = subprocess.run(cmd, cwd=self.temp_dir, env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("Architect instruction file not found: non_existent_spec.md", res.stderr)

    def test_e2e_cli_single_mode_file_backward_compatibility(self):
        """Zero-mock E2E: In standalone single-agent mode, --file combines with positional question."""
        prompt_txt = os.path.join(self.temp_dir, "standalone_prompt.txt")
        with open(prompt_txt, "w", encoding="utf-8") as f:
            f.write("STANDALONE_FILE_BODY")

        cmd = [sys.executable, self.oracle_script, "--file", prompt_txt, "--no-rag", "PositionalHeader"]
        res = subprocess.run(cmd, cwd=self.temp_dir, env=self.env, capture_output=True, text=True)
        self.assertNotIn("Oracle instruction file not found", res.stderr)


if __name__ == "__main__":
    unittest.main()
