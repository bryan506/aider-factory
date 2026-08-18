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

    def test_build_repomap_ignore_content_source_mode(self):
        content = cli._build_repomap_ignore_content(self.temp_dir, mode="source")
        self.assertIn(".aider_factory/", content)
        self.assertIn("src/aider_factory/tests/**", content)
        self.assertNotIn("src/aider_factory/python/**", content)

    def test_build_repomap_ignore_content_tests_mode(self):
        content = cli._build_repomap_ignore_content(self.temp_dir, mode="tests")
        self.assertIn(".aider_factory/", content)
        self.assertIn("src/aider_factory/python/**", content)
        self.assertNotIn("src/aider_factory/tests/**", content)

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
