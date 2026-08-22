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

    def test_live_repo_map_complex_polyglot_monorepo_matrix(self):
        """5. Comprehensive 25+ file polyglot monorepo smoke test verifying edge cases, false-positive domain words, co-located tests, and custom ignores."""
        repo_dir = os.path.join(self.test_dir, "project_complex_monorepo")
        os.makedirs(repo_dir, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "tester@ai-factory.test"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "AI Factory Tester"], cwd=repo_dir, check=True, capture_output=True)

        # 1. Custom user .aiderignore with bespoke exclusions
        with open(os.path.join(repo_dir, ".aiderignore"), "w", encoding="utf-8") as f:
            f.write("# User custom exclusions\n.aider_factory/\ncustom_media/\nlegacy_vendor/\n*.customdata\n")

        # 2. Python Domain vs Test files (including tricky domain words like contest.py and attestation.py)
        app_domain = os.path.join(repo_dir, "app", "domain")
        os.makedirs(app_domain, exist_ok=True)
        with open(os.path.join(app_domain, "contest.py"), "w", encoding="utf-8") as f:
            f.write("class ContestEngine:\n    def compute_scores(self): return 100\n")
        with open(os.path.join(app_domain, "attestation.py"), "w", encoding="utf-8") as f:
            f.write("class AttestationService:\n    def verify_sig(self): return True\n")
        with open(os.path.join(app_domain, "test_contest.py"), "w", encoding="utf-8") as f:
            f.write("def test_contest(): assert True\n")

        pytest_root = os.path.join(repo_dir, "tests", "e2e")
        os.makedirs(pytest_root, exist_ok=True)
        with open(os.path.join(pytest_root, "test_checkout.py"), "w", encoding="utf-8") as f:
            f.write("def test_e2e_checkout(): assert 1 == 1\n")
        with open(os.path.join(repo_dir, "conftest.py"), "w", encoding="utf-8") as f:
            f.write("# Pytest fixtures\ndef pytest_configure(): pass\n")

        # 3. TypeScript / React co-located components vs tricky latest.ts
        components_dir = os.path.join(repo_dir, "frontend", "components", "Button")
        os.makedirs(components_dir, exist_ok=True)
        with open(os.path.join(components_dir, "Button.tsx"), "w", encoding="utf-8") as f:
            f.write("export function Button() { return <button>Press</button>; }\n")
        with open(os.path.join(components_dir, "Button.test.tsx"), "w", encoding="utf-8") as f:
            f.write("test('Button click', () => { expect(1).toBe(1); });\n")

        ts_lib = os.path.join(repo_dir, "frontend", "lib")
        os.makedirs(ts_lib, exist_ok=True)
        with open(os.path.join(ts_lib, "latest.ts"), "w", encoding="utf-8") as f:
            f.write("export const getLatestTimestamp = () => Date.now();\n")
        with open(os.path.join(ts_lib, "latest.spec.ts"), "w", encoding="utf-8") as f:
            f.write("test('latest timestamp', () => { expect(true).toBe(true); });\n")

        # 4. Go packages vs tricky protest.go
        pkg_protest = os.path.join(repo_dir, "pkg", "protest")
        os.makedirs(pkg_protest, exist_ok=True)
        with open(os.path.join(pkg_protest, "protest.go"), "w", encoding="utf-8") as f:
            f.write("package protest\nfunc RecordProtest() int { return 1 }\n")
        with open(os.path.join(pkg_protest, "protest_test.go"), "w", encoding="utf-8") as f:
            f.write("package protest\nimport \"testing\"\nfunc TestProtest(t *testing.T) {}\n")

        pkg_testdata = os.path.join(repo_dir, "pkg", "auth", "testdata")
        os.makedirs(pkg_testdata, exist_ok=True)
        with open(os.path.join(pkg_testdata, "mock_token.go"), "w", encoding="utf-8") as f:
            f.write("package testdata\nconst MockToken = \"xyz\"\n")

        # 5. Rust crates with benchmarks and integration tests
        crates_src = os.path.join(repo_dir, "crates", "engine", "src")
        crates_tests = os.path.join(repo_dir, "crates", "engine", "tests")
        crates_benches = os.path.join(repo_dir, "crates", "engine", "benches")
        os.makedirs(crates_src, exist_ok=True)
        os.makedirs(crates_tests, exist_ok=True)
        os.makedirs(crates_benches, exist_ok=True)
        with open(os.path.join(crates_src, "lib.rs"), "w", encoding="utf-8") as f:
            f.write("pub fn run_fastest_sort() -> i32 { 42 }\n")
        with open(os.path.join(crates_tests, "integration_flow.rs"), "w", encoding="utf-8") as f:
            f.write("#[test]\nfn test_integration() { assert!(true); }\n")
        with open(os.path.join(crates_benches, "alloc_bench.rs"), "w", encoding="utf-8") as f:
            f.write("fn benchmark_alloc() {}\n")

        # 6. Java domain vs CamelCase Test classes
        java_main = os.path.join(repo_dir, "src", "main", "java", "com", "app")
        java_test = os.path.join(repo_dir, "src", "test", "java", "com", "app")
        os.makedirs(java_main, exist_ok=True)
        os.makedirs(java_test, exist_ok=True)
        with open(os.path.join(java_main, "ContestManager.java"), "w", encoding="utf-8") as f:
            f.write("package com.app; public class ContestManager {}\n")
        with open(os.path.join(java_test, "ContestManagerTest.java"), "w", encoding="utf-8") as f:
            f.write("package com.app; public class ContestManagerTest {}\n")

        # 7. R strategy vs testthat
        r_dir = os.path.join(repo_dir, "R")
        r_test_dir = os.path.join(repo_dir, "tests", "testthat")
        os.makedirs(r_dir, exist_ok=True)
        os.makedirs(r_test_dir, exist_ok=True)
        with open(os.path.join(r_dir, "contest_stats.R"), "w", encoding="utf-8") as f:
            f.write("compute_contest_stats <- function(x) { x + 1 }\n")
        with open(os.path.join(r_test_dir, "test-contest.R"), "w", encoding="utf-8") as f:
            f.write("test_that('contest stats work', { expect_equal(1, 1) })\n")

        # 8. User-ignored assets
        media_dir = os.path.join(repo_dir, "custom_media")
        vendor_dir = os.path.join(repo_dir, "legacy_vendor")
        os.makedirs(media_dir, exist_ok=True)
        os.makedirs(vendor_dir, exist_ok=True)
        with open(os.path.join(media_dir, "hero_banner.png"), "w", encoding="utf-8") as f:
            f.write("fake-png-binary\n")
        with open(os.path.join(vendor_dir, "old_lib.py"), "w", encoding="utf-8") as f:
            f.write("def old_func(): pass\n")
        with open(os.path.join(repo_dir, "prices.customdata"), "w", encoding="utf-8") as f:
            f.write("100.5,101.2\n")

        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Complex polyglot monorepo commit"], cwd=repo_dir, check=True, capture_output=True)

        env = self._get_subprocess_env()

        res = subprocess.run(
            [sys.executable, CLI_PATH, "--repo-map-all"],
            cwd=repo_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"CLI execution failed: {res.stderr}")

        source_map_path = os.path.join(repo_dir, ".aider_factory", "static_repo_map.md")
        test_map_path = os.path.join(repo_dir, ".aider_factory", "static_repo_map_tests.md")

        with open(source_map_path, "r", encoding="utf-8") as f:
            source_content = f.read()

        with open(test_map_path, "r", encoding="utf-8") as f:
            test_content = f.read()

        # ==========================================================
        # VERIFICATION 1: Source Map Must Contain All Core & Domain Code
        # ==========================================================
        # Python
        self.assertIn("contest.py", source_content, "contest.py MUST NOT be false-positive excluded")
        self.assertIn("attestation.py", source_content, "attestation.py MUST NOT be false-positive excluded")
        # TypeScript / React
        self.assertIn("Button.tsx", source_content)
        self.assertIn("latest.ts", source_content, "latest.ts MUST NOT be false-positive excluded")
        # Go
        self.assertIn("protest.go", source_content, "protest.go MUST NOT be false-positive excluded")
        # Rust
        self.assertIn("lib.rs", source_content)
        # Java
        self.assertIn("ContestManager.java", source_content)
        # R
        self.assertIn("contest_stats.R", source_content)

        # ==========================================================
        # VERIFICATION 2: Source Map Must Exclude ALL Test Code & User Ignored Assets
        # ==========================================================
        self.assertNotIn("test_contest.py", source_content)
        self.assertNotIn("test_checkout.py", source_content)
        self.assertNotIn("conftest.py", source_content)
        self.assertNotIn("Button.test.tsx", source_content)
        self.assertNotIn("latest.spec.ts", source_content)
        self.assertNotIn("protest_test.go", source_content)
        self.assertNotIn("mock_token.go", source_content)
        self.assertNotIn("integration_flow.rs", source_content)
        self.assertNotIn("alloc_bench.rs", source_content)
        self.assertNotIn("ContestManagerTest.java", source_content)
        self.assertNotIn("test-contest.R", source_content)
        self.assertNotIn("hero_banner.png", source_content)
        self.assertNotIn("old_lib.py", source_content)
        self.assertNotIn("prices.customdata", source_content)

        # ==========================================================
        # VERIFICATION 3: Test Map Must Contain ALL Test & Benchmark Code
        # ==========================================================
        self.assertIn("test_contest.py", test_content)
        self.assertIn("test_checkout.py", test_content)
        self.assertIn("conftest.py", test_content)
        self.assertIn("Button.test.tsx", test_content)
        self.assertIn("latest.spec.ts", test_content)
        self.assertIn("protest_test.go", test_content)
        self.assertIn("mock_token.go", test_content)
        self.assertIn("integration_flow.rs", test_content)
        self.assertIn("alloc_bench.rs", test_content)
        self.assertIn("ContestManagerTest.java", test_content)
        self.assertIn("test-contest.R", test_content)

        # ==========================================================
        # VERIFICATION 4: Test Map Must Exclude ALL Main Source & User Ignored Assets
        # ==========================================================
        self.assertNotIn("app/domain/contest.py", test_content)
        self.assertNotIn("app/domain/attestation.py", test_content)
        self.assertNotIn("frontend/components/Button/Button.tsx", test_content)
        self.assertNotIn("frontend/lib/latest.ts", test_content)
        self.assertNotIn("pkg/protest/protest.go", test_content)
        self.assertNotIn("crates/engine/src/lib.rs", test_content)
        self.assertNotIn("src/main/java/com/app/ContestManager.java", test_content)
        self.assertNotIn("R/contest_stats.R", test_content)
        self.assertNotIn("old_lib.py", test_content)
        self.assertNotIn("hero_banner.png", test_content)
        self.assertNotIn("prices.customdata", test_content)

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
