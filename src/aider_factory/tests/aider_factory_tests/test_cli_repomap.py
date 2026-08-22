import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import os
import sys

# Ensure src/ and src/aider_factory/ are in sys.path
pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
src_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
for p in [pkg_root, src_root]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from aider_factory import cli
except ImportError:
    import cli


class TestCLIRepoMap(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)

    def test_read_user_aiderignore_parsing(self):
        ignore_path = os.path.join(self.temp_dir, ".aiderignore")
        with open(ignore_path, "w", encoding="utf-8") as f:
            f.write("# Comment line\n.aider_factory/\n\ncustom_assets/\n*.customdata\n")
        rules = cli._read_user_aiderignore(self.temp_dir)
        self.assertIn(".aider_factory/", rules)
        self.assertIn("custom_assets/", rules)
        self.assertIn("*.customdata", rules)
        self.assertNotIn("# Comment line", rules)

    def test_is_test_path_polyglot_and_domain_false_positives(self):
        # --- POSITIVE TEST CASES (Must be TRUE) ---
        positive_cases = [
            # Python
            "tests/test_core.py",
            "app/tests/test_service.py",
            "app/service_test.py",
            "app/test-service.py",
            "conftest.py",
            "tests.py",
            "e2e/test_checkout.py",
            "benchmarks/bench_eval.py",
            # TypeScript / JavaScript / React
            "components/Button/Button.test.tsx",
            "components/Button/Button.spec.ts",
            "src/__tests__/utils.ts",
            "lib/api.spec.js",
            "lib/setupTests.ts",
            "e2e/cypress/login.spec.js",
            # Go
            "pkg/server/router_test.go",
            "pkg/auth/testdata/mock_token.go",
            # Rust
            "crates/engine/tests/integration.rs",
            "crates/engine/benches/alloc_bench.rs",
            "src/tests.rs",
            "src/tests_engine.rs",
            # Java / Kotlin / Scala / C# / PHP
            "src/test/java/com/app/UserServiceTest.java",
            "src/test/kotlin/OrderTestCase.kt",
            "specs/UserSpec.scala",
            "tests/Feature/AuthTest.php",
            "Controllers/AccountTests.cs",
            # R
            "tests/testthat/test-alpha.R",
            "tests/testthat/test_alpha.R",
            # Ruby
            "spec/models/user_spec.rb",
            "test/test_helper.rb",
            # C / C++
            "tests/math_unittest.cc",
            "src/parser_test.cpp",
        ]
        for p in positive_cases:
            self.assertTrue(cli._is_test_path(p), f"Expected TRUE for test path: {p}")

        # --- TRICKY DOMAIN CASES (Must be FALSE - NO FALSE POSITIVES) ---
        negative_cases = [
            # Python domain words containing 'test'
            "app/domain/contest.py",
            "app/domain/contest_service.py",
            "app/domain/attestation.py",
            "app/domain/fastest_route.py",
            "app/domain/latest_data.py",
            "app/domain/protest_tracker.py",
            "app/domain/testament.py",
            "app/domain/detest.py",
            # TypeScript / JavaScript domain words
            "components/Contest/ContestCard.tsx",
            "lib/latest.ts",
            "lib/attestation.ts",
            "services/fastestQuery.js",
            "services/specification.ts",
            # Go domain packages & files
            "pkg/contest/contest.go",
            "pkg/attestation/verify.go",
            "pkg/protest/event.go",
            # Rust crates & modules
            "crates/contest/src/lib.rs",
            "crates/engine/src/attestation.rs",
            "crates/engine/src/fastest_sort.rs",
            # Java / Scala / C# domain classes
            "src/main/java/com/app/ContestService.java",
            "src/main/java/com/app/LatestPrices.java",
            "src/main/java/com/app/AttestationHandler.java",
            # R domain files
            "R/contest_analysis.R",
            "R/spectral_density.R",
            # C / C++ domain files
            "src/contest_engine.cpp",
            "include/attestation.h",
        ]
        for p in negative_cases:
            self.assertFalse(cli._is_test_path(p), f"Expected FALSE for domain path: {p}")

    def test_build_repomap_ignore_content_source_mode(self):
        ignore_path = os.path.join(self.temp_dir, ".aiderignore")
        with open(ignore_path, "w", encoding="utf-8") as f:
            f.write("custom_folder/\n*.custombin\n")

        files = [
            "app/models.py",
            "app/models_test.py",
            "components/Widget.tsx",
            "components/Widget.test.tsx",
        ]
        content = cli._build_repomap_ignore_content(self.temp_dir, mode="source", all_files=files)
        # Inherits user rules
        self.assertIn("custom_folder/", content)
        self.assertIn("*.custombin", content)
        self.assertIn(".aider_factory/", content)
        # Excludes test files
        self.assertIn("app/models_test.py", content)
        self.assertIn("components/Widget.test.tsx", content)
        # Keeps source files
        self.assertNotIn("app/models.py", content)
        self.assertNotIn("components/Widget.tsx", content)

    def test_build_repomap_ignore_content_tests_mode(self):
        ignore_path = os.path.join(self.temp_dir, ".aiderignore")
        with open(ignore_path, "w", encoding="utf-8") as f:
            f.write("custom_folder/\n*.custombin\n")

        files = [
            "app/models.py",
            "app/models_test.py",
            "components/Widget.tsx",
            "components/Widget.test.tsx",
        ]
        content = cli._build_repomap_ignore_content(self.temp_dir, mode="tests", all_files=files)
        # Inherits user rules
        self.assertIn("custom_folder/", content)
        self.assertIn("*.custombin", content)
        self.assertIn(".aider_factory/", content)
        # Excludes source files
        self.assertIn("app/models.py", content)
        self.assertIn("components/Widget.tsx", content)
        # Keeps test files
        self.assertNotIn("app/models_test.py", content)
        self.assertNotIn("components/Widget.test.tsx", content)

    def test_ensure_baseline_aiderignore(self):
        ignore_path = os.path.join(self.temp_dir, ".aiderignore")
        cli._ensure_baseline_aiderignore(self.temp_dir)
        self.assertTrue(os.path.exists(ignore_path))
        with open(ignore_path, "r", encoding="utf-8") as f:
            data = f.read()
        self.assertEqual(data, cli.BASELINE_AIDERIGNORE)

    @patch("cli.subprocess.run")
    @patch("cli.ensure_aider_installed")
    def test_generate_repo_maps_execution_and_cleanup(self, mock_ensure_aider, mock_run):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "Fake Repo Map Output\nLine 2"
        mock_res.stderr = ""
        mock_run.return_value = mock_res

        cli._generate_repo_maps(self.temp_dir, map_tokens=2048, target="all", is_global=False)

        source_map = os.path.join(self.temp_dir, ".aider_factory", "static_repo_map.md")
        tests_map = os.path.join(self.temp_dir, ".aider_factory", "static_repo_map_tests.md")
        self.assertTrue(os.path.exists(source_map))
        self.assertTrue(os.path.exists(tests_map))

        with open(source_map, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "Fake Repo Map Output\nLine 2")

        # Ephemeral ignore files must be removed
        ephemeral_source = os.path.join(self.temp_dir, ".aider_factory", ".aiderignore_source")
        ephemeral_tests = os.path.join(self.temp_dir, ".aider_factory", ".aiderignore_tests")
        self.assertFalse(os.path.exists(ephemeral_source))
        self.assertFalse(os.path.exists(ephemeral_tests))

        # Root .aiderignore must match baseline
        root_ignore = os.path.join(self.temp_dir, ".aiderignore")
        self.assertTrue(os.path.exists(root_ignore))
        with open(root_ignore, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), cli.BASELINE_AIDERIGNORE)


if __name__ == "__main__":
    unittest.main()
