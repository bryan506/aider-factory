
#!/usr/bin/env python3
# test_e2e_helper.py — Zero-Mock Physical Smoke Test for aider-helper CLI.

import os
import subprocess
import sys
import tempfile

script_dir = os.path.dirname(os.path.abspath(__file__))
pkg_dir = os.path.abspath(os.path.join(script_dir, "../../.."))
src_dir = os.path.abspath(os.path.join(pkg_dir, ".."))
repo_root = os.path.abspath(os.path.join(src_dir, ".."))

import unittest

class TestE2EHelper(unittest.TestCase):
    def test_e2e_helper_smoke(self):
        print("==================================================")
        print("Starting Zero-Mock E2E Smoke Test (aider-helper)...")
        print("==================================================")

        env = os.environ.copy()
        python_path = os.pathsep.join([
            repo_root, src_dir, pkg_dir, os.path.join(pkg_dir, "python")
        ])
        env["PYTHONPATH"] = python_path

        # 1. Test CLI Help Invariant via Real Subprocess
        res_help = subprocess.run(
            [sys.executable, "-c", "import cli; cli.helper_cli()", "--help"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_help.returncode, 0, f"aider-helper --help failed: {res_help.stderr}")
        self.assertTrue("aider-helper" in res_help.stdout or "usage:" in res_help.stdout.lower())
        print("  ✅ Physical CLI Help Invariant PASS")

        # 2. Test Standalone --clear via Real Subprocess
        with tempfile.TemporaryDirectory() as tmp_dir:
            sess_dir = os.path.join(tmp_dir, ".aider_factory")
            os.makedirs(sess_dir, exist_ok=True)
            sess_file = os.path.join(sess_dir, ".helper_session.json")
            with open(sess_file, "w", encoding="utf-8") as f:
                f.write("[]")

            res_clear = subprocess.run(
                [sys.executable, "-c", "import cli; cli.helper_cli()", "query", "--clear"],
                cwd=tmp_dir,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_clear.returncode, 0, f"--clear failed: {res_clear.stderr}")
            self.assertFalse(os.path.exists(sess_file), "Session file must be deleted on --clear")
            print("  ✅ Physical Standalone --clear PASS")

        # 3. Test Terminal --clear via Real Subprocess
        with tempfile.TemporaryDirectory() as tmp_dir:
            sess_dir = os.path.join(tmp_dir, ".aider_factory")
            os.makedirs(sess_dir, exist_ok=True)
            term_sess_file = os.path.join(sess_dir, ".helper_terminal_session.json")
            with open(term_sess_file, "w", encoding="utf-8") as f:
                f.write("[]")

            res_term_clear = subprocess.run(
                [sys.executable, "-c", "import cli; cli.helper_cli()", "query", "-t", "--clear"],
                cwd=tmp_dir,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_term_clear.returncode, 0)
            self.assertFalse(os.path.exists(term_sess_file), "Terminal session file must be deleted on -t --clear")
            print("  ✅ Physical Terminal --clear PASS")

        # 4. Test Missing File Error Code via Real Subprocess
        res_missing = subprocess.run(
            [sys.executable, "-c", "import cli; cli.helper_cli()", "query", "test", "-f", "non_existent_9999.yml"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_missing.returncode, 1, "Missing file should exit with return code 1")
        print("  ✅ Physical Missing File Graceful Exit PASS")

        # 5. Test bootstrap scaffold via Real Subprocess
        with tempfile.TemporaryDirectory() as tmp_boot:
            open(os.path.join(tmp_boot, "pytest.ini"), "w").close()
            open(os.path.join(tmp_boot, "pyproject.toml"), "w").close()

            res_boot = subprocess.run(
                [sys.executable, "-c", "import cli; cli.helper_cli()", "bootstrap"],
                cwd=tmp_boot,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_boot.returncode, 0, f"bootstrap failed: {res_boot.stderr}")
            af_dir = os.path.join(tmp_boot, ".aider_factory")
            self.assertTrue(os.path.isdir(af_dir), "bootstrap must create .aider_factory/")
            yaml_files = [f for f in os.listdir(af_dir) if f.startswith(".env_") and f.endswith(".yml")]
            self.assertGreaterEqual(len(yaml_files), 1, f"Expected .env_*.yml in .aider_factory/, got: {yaml_files}")
            with open(os.path.join(af_dir, yaml_files[0]), "r") as f:
                content = f.read()
            self.assertIn("test_runner:", content, "Generated YAML must contain test_runner key")
            self.assertIn("pytest", content, "Pytest framework must be detected from pytest.ini")
            self.assertIn("working_directory:", content, "Generated YAML must set working_directory")
            print("  \u2705 Physical bootstrap scaffold PASS")

        # 6. Test bootstrap --repo flag via Real Subprocess
        with tempfile.TemporaryDirectory() as tmp_repo_target:
            with tempfile.TemporaryDirectory() as tmp_cwd:
                res_repo = subprocess.run(
                    [sys.executable, "-c", "import cli; cli.helper_cli()",
                     "bootstrap", "--repo", tmp_repo_target],
                    cwd=tmp_cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(res_repo.returncode, 0, f"bootstrap --repo failed: {res_repo.stderr}")
                af_target = os.path.join(tmp_repo_target, ".aider_factory")
                self.assertTrue(os.path.isdir(af_target), "--repo must scaffold in target, not cwd")
                print("  \u2705 Physical bootstrap --repo flag PASS")

        # 7. Test bootstrap --repo with nonexistent directory (must create, not crash)
        with tempfile.TemporaryDirectory() as tmp_parent:
            nonexistent_target = os.path.join(tmp_parent, "does_not_exist_yet")
            res_create = subprocess.run(
                [sys.executable, "-c", "import cli; cli.helper_cli()",
                 "bootstrap", "--repo", nonexistent_target],
                cwd=tmp_parent,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_create.returncode, 0, f"--repo nonexistent must not crash: {res_create.stderr}")
            self.assertTrue(os.path.isdir(os.path.join(nonexistent_target, ".aider_factory")),
                "--repo must create target dir and scaffold inside it")
            print("  \u2705 Physical bootstrap --repo nonexistent dir PASS")

        print("\n\U0001f389 Zero-Mock E2E Smoke Test (aider-helper) Completed Successfully!")

if __name__ == "__main__":
    unittest.main()
