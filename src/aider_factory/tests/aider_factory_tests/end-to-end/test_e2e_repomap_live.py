import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

CLI_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../cli.py")
)


class TestE2ERepoMapLive(unittest.TestCase):
    """Zero-Mock Live E2E Smoke Tests for Repo Map generation (--repo-map, --repo-map-tests, --repo-map-all, --global)."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Clear session environment variables
        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
                os.environ.pop(k, None)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _get_subprocess_env(self, extra_env=None):
        env = dict(os.environ)
        # Sandbox home directory to isolate global registry
        env["HOME"] = self.test_dir
        env["OPENAI_API_KEY"] = "sk-dummy"
        local_bin = os.path.expanduser("~/.local/bin")
        if os.path.exists(local_bin):
            env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"
        if extra_env:
            env.update(extra_env)
        return env

    def _setup_git_repo(self, repo_dir):
        """Create a real Git repository with source, test, doc, and temp files."""
        os.makedirs(repo_dir, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "tester@ai-factory.test"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "AI Factory Tester"], cwd=repo_dir, check=True, capture_output=True)

        # 1. Source files
        src_py = os.path.join(repo_dir, "src", "aider_factory", "python")
        os.makedirs(src_py, exist_ok=True)
        with open(os.path.join(src_py, "core_engine.py"), "w", encoding="utf-8") as f:
            f.write("class CoreEngine:\n    def calculate_alpha(self, data):\n        return data * 2\n")

        with open(os.path.join(repo_dir, "src", "aider_factory", "cli.py"), "w", encoding="utf-8") as f:
            f.write("def main_entrypoint():\n    print('Running core CLI')\n")

        r_dir = os.path.join(repo_dir, "R")
        os.makedirs(r_dir, exist_ok=True)
        with open(os.path.join(r_dir, "strategy.R"), "w", encoding="utf-8") as f:
            f.write("run_strategy <- function(prices) {\n  return(prices + 1.5)\n}\n")

        # 2. Test files
        test_py = os.path.join(repo_dir, "src", "aider_factory", "tests")
        os.makedirs(test_py, exist_ok=True)
        with open(os.path.join(test_py, "test_core_engine.py"), "w", encoding="utf-8") as f:
            f.write("def test_calculate_alpha():\n    assert True\n")

        root_tests = os.path.join(repo_dir, "tests")
        os.makedirs(root_tests, exist_ok=True)
        with open(os.path.join(root_tests, "test_integration.py"), "w", encoding="utf-8") as f:
            f.write("def test_e2e_integration():\n    assert 1 == 1\n")

        # 3. Excluded Docs and Temp files
        docs_dir = os.path.join(repo_dir, "docs")
        os.makedirs(docs_dir, exist_ok=True)
        with open(os.path.join(docs_dir, "architecture_overview.md"), "w", encoding="utf-8") as f:
            f.write("# Architecture Overview\n")

        temp_dir = os.path.join(repo_dir, "temp")
        os.makedirs(temp_dir, exist_ok=True)
        with open(os.path.join(temp_dir, "scratchpad.txt"), "w", encoding="utf-8") as f:
            f.write("temporary file\n")

        # Commit everything so Aider's AST repo-map generator indexes it
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial test commit"], cwd=repo_dir, check=True, capture_output=True)

    def test_live_repo_map_source_mode(self):
        """1. Verify `aider-factory --repo-map` generates static_repo_map.md with source code only."""
        repo_dir = os.path.join(self.test_dir, "project_source_test")
        self._setup_git_repo(repo_dir)
        env = self._get_subprocess_env()

        res = subprocess.run(
            [sys.executable, CLI_PATH, "--repo-map"],
            cwd=repo_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"CLI execution failed: {res.stderr}")
        self.assertIn("static_repo_map.md", res.stdout)

        source_map_path = os.path.join(repo_dir, ".aider_factory", "static_repo_map.md")
        self.assertTrue(os.path.exists(source_map_path), "static_repo_map.md must be generated on disk")

        with open(source_map_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Must include source files/symbols
        self.assertIn("core_engine.py", content)
        self.assertIn("CoreEngine", content)

        # Must NOT include test files or excluded docs
        self.assertNotIn("test_core_engine.py", content)
        self.assertNotIn("test_integration.py", content)
        self.assertNotIn("architecture_overview.md", content)

        # Ephemeral files must be deleted
        self.assertFalse(os.path.exists(os.path.join(repo_dir, ".aider_factory", ".aiderignore_source")))

        # Root .aiderignore must exist and match baseline
        root_ignore = os.path.join(repo_dir, ".aiderignore")
        self.assertTrue(os.path.exists(root_ignore))
        with open(root_ignore, "r", encoding="utf-8") as f:
            self.assertIn(".aider_factory/", f.read())

    def test_live_repo_map_tests_mode(self):
        """2. Verify `aider-factory --repo-map-tests` generates static_repo_map_tests.md with test suites only."""
        repo_dir = os.path.join(self.test_dir, "project_tests_test")
        self._setup_git_repo(repo_dir)
        env = self._get_subprocess_env()

        res = subprocess.run(
            [sys.executable, CLI_PATH, "--repo-map-tests"],
            cwd=repo_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"CLI execution failed: {res.stderr}")
        self.assertIn("static_repo_map_tests.md", res.stdout)

        test_map_path = os.path.join(repo_dir, ".aider_factory", "static_repo_map_tests.md")
        self.assertTrue(os.path.exists(test_map_path), "static_repo_map_tests.md must be generated on disk")

        with open(test_map_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Must include test files/symbols
        self.assertTrue("test_core_engine.py" in content or "test_integration.py" in content)

        # Must NOT include core source code or docs
        self.assertNotIn("src/aider_factory/python/", content)
        self.assertNotIn("strategy.R", content)
        self.assertNotIn("architecture_overview.md", content)

        # Ephemeral files must be deleted
        self.assertFalse(os.path.exists(os.path.join(repo_dir, ".aider_factory", ".aiderignore_tests")))

    def test_live_repo_map_all_and_token_override(self):
        """3. Verify `aider-factory --repo-map-all --map-tokens 2048` generates both maps in one pass."""
        repo_dir = os.path.join(self.test_dir, "project_all_test")
        self._setup_git_repo(repo_dir)
        env = self._get_subprocess_env()

        res = subprocess.run(
            [sys.executable, CLI_PATH, "--repo-map-all", "--map-tokens", "2048"],
            cwd=repo_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"CLI execution failed: {res.stderr}")

        source_map = os.path.join(repo_dir, ".aider_factory", "static_repo_map.md")
        test_map = os.path.join(repo_dir, ".aider_factory", "static_repo_map_tests.md")

        self.assertTrue(os.path.exists(source_map), "static_repo_map.md must exist")
        self.assertTrue(os.path.exists(test_map), "static_repo_map_tests.md must exist")

    def test_live_repo_map_global_multi_workspace(self):
        """4. Verify `aider-factory --repo-map-all --global` regenerates repo maps across all registered workspaces."""
        repo_a = os.path.join(self.test_dir, "workspace_alpha")
        repo_b = os.path.join(self.test_dir, "workspace_beta")
        self._setup_git_repo(repo_a)
        self._setup_git_repo(repo_b)
        env = self._get_subprocess_env()

        # Initialize and register both workspaces via lightweight status probe
        subprocess.run([sys.executable, CLI_PATH, "--status"], cwd=repo_a, env=env, capture_output=True)
        subprocess.run([sys.executable, CLI_PATH, "--status"], cwd=repo_b, env=env, capture_output=True)

        # Run global repo map generation from workspace A
        res_global = subprocess.run(
            [sys.executable, CLI_PATH, "--repo-map-all", "--global"],
            cwd=repo_a,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_global.returncode, 0, f"Global CLI execution failed: {res_global.stderr}")
        self.assertIn("workspace_alpha", res_global.stdout)
        self.assertIn("workspace_beta", res_global.stdout)

        # Both workspaces must have physical maps generated on disk
        self.assertTrue(os.path.exists(os.path.join(repo_a, ".aider_factory", "static_repo_map.md")))
        self.assertTrue(os.path.exists(os.path.join(repo_a, ".aider_factory", "static_repo_map_tests.md")))
        self.assertTrue(os.path.exists(os.path.join(repo_b, ".aider_factory", "static_repo_map.md")))
        self.assertTrue(os.path.exists(os.path.join(repo_b, ".aider_factory", "static_repo_map_tests.md")))


if __name__ == "__main__":
    unittest.main()
