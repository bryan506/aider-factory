#!/usr/bin/env python3
"""Unit tests for Phase 3: factory_launcher.py and clean_lancedb.py."""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Resolve package paths
_test_dir = os.path.dirname(os.path.abspath(__file__))
_pkg_dir = os.path.abspath(os.path.join(_test_dir, "../.."))
_python_dir = os.path.join(_pkg_dir, "python")
if _python_dir not in sys.path:
    sys.path.insert(0, _python_dir)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)


# ---------------------------------------------------------------------------
# factory_launcher.py unit tests
# ---------------------------------------------------------------------------

class TestResolveConfig(unittest.TestCase):
    """U3a-1 through U3a-5: _resolve_config() path resolution."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_u3a1_explicit_yml_in_argv(self):
        """U3a-1: _resolve_config finds explicit .yml in argv."""
        from factory_launcher import _resolve_config
        cfg = os.path.join(self.tmpdir, "my_config.yml")
        Path(cfg).touch()
        result = _resolve_config(["my_config.yml"])
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith("my_config.yml"))

    def test_u3a2_skips_dash_prefixed_args(self):
        """U3a-2: _resolve_config skips -s, --session, etc."""
        from factory_launcher import _resolve_config
        cfg = os.path.join(self.tmpdir, "real.yml")
        Path(cfg).touch()
        result = _resolve_config(["--session", "foo", "real.yml"])
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith("real.yml"))

    def test_u3a3_fallback_aider_factory_env_yml(self):
        """U3a-3: _resolve_config falls back to .aider_factory/.env.yml."""
        from factory_launcher import _resolve_config
        af_dir = os.path.join(self.tmpdir, ".aider_factory")
        os.makedirs(af_dir)
        Path(os.path.join(af_dir, ".env.yml")).touch()
        result = _resolve_config([])
        self.assertIsNotNone(result)
        self.assertIn(".aider_factory", result)
        self.assertTrue(result.endswith(".env.yml"))

    def test_u3a4_fallback_root_env_yml(self):
        """U3a-4: _resolve_config falls back to .env.yml in cwd."""
        from factory_launcher import _resolve_config
        Path(os.path.join(self.tmpdir, ".env.yml")).touch()
        result = _resolve_config([])
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith(".env.yml"))

    def test_u3a5_returns_none_when_no_config(self):
        """U3a-5: _resolve_config returns None when nothing found."""
        from factory_launcher import _resolve_config
        result = _resolve_config([])
        self.assertIsNone(result)


class TestDeriveLogPath(unittest.TestCase):
    """U3a-6 through U3a-8: _derive_log_path() log file derivation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_u3a6_creates_logs_dir_and_correct_stem(self):
        """U3a-6: _derive_log_path creates logs/ dir and uses config stem."""
        from factory_launcher import _derive_log_path
        result = _derive_log_path("/some/path/my_pipeline.yml")
        logs_dir = os.path.join(self.tmpdir, ".aider_factory", "logs")
        self.assertTrue(os.path.isdir(logs_dir))
        self.assertIn("my_pipeline_run_", result)
        self.assertTrue(result.endswith(".log"))

    def test_u3a7_strips_leading_dot_from_stem(self):
        """U3a-7: _derive_log_path strips leading dot from .env.yml."""
        from factory_launcher import _derive_log_path
        result = _derive_log_path("/path/.env.yml")
        basename = os.path.basename(result)
        self.assertTrue(basename.startswith("env_run_"))

    def test_u3a8_uses_env_stem_when_config_none(self):
        """U3a-8: _derive_log_path uses 'env' stem when config is None."""
        from factory_launcher import _derive_log_path
        result = _derive_log_path(None)
        basename = os.path.basename(result)
        self.assertTrue(basename.startswith("env_run_"))


class TestLauncherMain(unittest.TestCase):
    """U3a-9 through U3a-14: main() behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)
        # Create minimal structure
        af_dir = os.path.join(self.tmpdir, ".aider_factory")
        os.makedirs(os.path.join(af_dir, "logs"), exist_ok=True)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_u3a9_force_color_in_env(self):
        """U3a-9: main() sets FORCE_COLOR=1 in subprocess env."""
        from factory_launcher import main
        with patch("factory_launcher.subprocess.Popen") as mock_popen, \
             patch("factory_launcher.subprocess.run"), \
             patch("factory_launcher.sys.argv", ["launcher"]), \
             patch("factory_launcher.os.path.isfile", return_value=True), \
             patch("factory_launcher.sys.exit"):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.wait.return_value = 0
            mock_stdout = MagicMock()
            mock_stdout.read.return_value = b""
            mock_proc.stdout = mock_stdout
            mock_popen.return_value = mock_proc

            main()

            call_kwargs = mock_popen.call_args
            env = call_kwargs[1].get("env") or call_kwargs.kwargs.get("env", {})
            self.assertEqual(env.get("FORCE_COLOR"), "1")

    def test_u3a10_preserves_exit_code(self):
        """U3a-10: main() preserves subprocess exit code via sys.exit."""
        from factory_launcher import main
        with patch("factory_launcher.subprocess.Popen") as mock_popen, \
             patch("factory_launcher.subprocess.run"), \
             patch("factory_launcher.sys.argv", ["launcher"]), \
             patch("factory_launcher.os.path.isfile", return_value=True), \
             patch("factory_launcher.sys.exit") as mock_exit:
            mock_proc = MagicMock()
            mock_proc.returncode = 42
            mock_proc.wait.return_value = 42
            mock_stdout = MagicMock()
            mock_stdout.read.return_value = b""
            mock_proc.stdout = mock_stdout
            mock_popen.return_value = mock_proc

            main()

            mock_exit.assert_called_with(42)

    def test_u3a11_runs_aggregate_costs(self):
        """U3a-11: main() runs aggregate_costs.py after workflow."""
        from factory_launcher import main
        with patch("factory_launcher.subprocess.Popen") as mock_popen, \
             patch("factory_launcher.subprocess.run") as mock_run, \
             patch("factory_launcher.sys.argv", ["launcher"]), \
             patch("factory_launcher.os.path.isfile", return_value=True), \
             patch("factory_launcher.sys.exit"):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.wait.return_value = 0
            mock_stdout = MagicMock()
            mock_stdout.read.return_value = b""
            mock_proc.stdout = mock_stdout
            mock_popen.return_value = mock_proc

            main()

            # subprocess.run should be called for aggregate_costs
            self.assertTrue(mock_run.called)
            agg_call = mock_run.call_args
            agg_cmd = agg_call[0][0]
            self.assertTrue(any("aggregate_costs" in str(a) for a in agg_cmd))

    def test_u3a13_help_exits_zero(self):
        """U3a-13: main() --help exits 0 with usage text."""
        from factory_launcher import main
        with patch("factory_launcher.sys.argv", ["launcher", "--help"]), \
             patch("factory_launcher.sys.exit") as mock_exit:
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                main()
            mock_exit.assert_called_with(0)
            output = captured.getvalue()
            self.assertIn("aider-launcher", output)


# ---------------------------------------------------------------------------
# clean_lancedb.py unit tests
# ---------------------------------------------------------------------------

class TestEmptyDir(unittest.TestCase):
    """U3b-1 through U3b-4: _empty_dir() behavior."""

    def test_u3b1_removes_contents_preserves_parent(self):
        """U3b-1: _empty_dir removes files and subdirs, preserves parent."""
        from clean_lancedb import _empty_dir
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files and subdirs
            Path(os.path.join(tmpdir, "file1.txt")).write_text("hello")
            Path(os.path.join(tmpdir, "file2.log")).write_text("world")
            sub = os.path.join(tmpdir, "subdir")
            os.makedirs(sub)
            Path(os.path.join(sub, "nested.txt")).write_text("nested")

            count = _empty_dir(tmpdir, "test")
            self.assertEqual(count, 3)  # file1, file2, subdir
            self.assertTrue(os.path.isdir(tmpdir))  # parent preserved
            self.assertEqual(os.listdir(tmpdir), [])  # empty

    def test_u3b2_returns_zero_for_nonexistent(self):
        """U3b-2: _empty_dir returns 0 for non-existent directory."""
        from clean_lancedb import _empty_dir
        result = _empty_dir("/nonexistent/path/xyz", "test")
        self.assertEqual(result, 0)

    def test_u3b3_returns_zero_for_empty_dir(self):
        """U3b-3: _empty_dir returns 0 for empty directory."""
        from clean_lancedb import _empty_dir
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _empty_dir(tmpdir, "test")
            self.assertEqual(result, 0)

    def test_u3b4_returns_zero_for_none_path(self):
        """U3b-4: _empty_dir returns 0 for None path."""
        from clean_lancedb import _empty_dir
        result = _empty_dir(None, "test")
        self.assertEqual(result, 0)
        result2 = _empty_dir("", "test")
        self.assertEqual(result2, 0)


class TestCleanLancedbMain(unittest.TestCase):
    """U3b-5 through U3b-11: main() behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.collection = "test_collection"
        # Build the expected directory structure
        self.af_dir = os.path.join(self.tmpdir, ".aider_factory")
        self.context_dir = os.path.join(
            self.af_dir, "markdown", "lanceDB", self.collection
        )
        os.makedirs(self.context_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_u3b5_removes_images_directory(self):
        """U3b-5: main() removes images/ directory completely."""
        from clean_lancedb import main
        img_dir = os.path.join(self.context_dir, "images")
        os.makedirs(img_dir)
        Path(os.path.join(img_dir, "page_001.png")).write_text("fake png")
        Path(os.path.join(img_dir, "page_002.png")).write_text("fake png")

        with patch("sys.argv", ["clean_lancedb", self.collection, "--project-dir", self.tmpdir]):
            main()

        self.assertFalse(os.path.exists(img_dir))

    def test_u3b6_empties_validations_and_debates(self):
        """U3b-6: main() empties validations/ and debates/ directories."""
        from clean_lancedb import main
        val_dir = os.path.join(self.af_dir, "logs", "validations")
        deb_dir = os.path.join(self.af_dir, "logs", "debates")
        os.makedirs(val_dir, exist_ok=True)
        os.makedirs(deb_dir, exist_ok=True)
        Path(os.path.join(val_dir, "report.md")).write_text("report")
        Path(os.path.join(val_dir, "ledger.json")).write_text("{}")
        Path(os.path.join(deb_dir, "transcript.md")).write_text("debate")

        with patch("sys.argv", ["clean_lancedb", self.collection, "--project-dir", self.tmpdir]):
            main()

        self.assertTrue(os.path.isdir(val_dir))  # dir preserved
        self.assertEqual(os.listdir(val_dir), [])  # contents removed
        self.assertTrue(os.path.isdir(deb_dir))
        self.assertEqual(os.listdir(deb_dir), [])

    def test_u3b7_preserves_lancedb_tables_and_sources(self):
        """U3b-7: main() preserves LanceDB tables and source files."""
        from clean_lancedb import main
        # Create LanceDB dir and source files that must NOT be deleted
        lance_dir = os.path.join(self.context_dir, "lancedb")
        os.makedirs(lance_dir, exist_ok=True)
        Path(os.path.join(lance_dir, "table.lance")).write_text("lance data")
        Path(os.path.join(self.context_dir, "paper.pdf")).write_bytes(b"fake pdf")
        Path(os.path.join(self.context_dir, "notes.md")).write_text("# Notes")
        # Also create images to be cleaned
        img_dir = os.path.join(self.context_dir, "images")
        os.makedirs(img_dir)
        Path(os.path.join(img_dir, "page.png")).write_text("img")

        with patch("sys.argv", ["clean_lancedb", self.collection, "--project-dir", self.tmpdir]):
            main()

        # Images cleaned
        self.assertFalse(os.path.exists(img_dir))
        # LanceDB and sources preserved
        self.assertTrue(os.path.isfile(os.path.join(lance_dir, "table.lance")))
        self.assertTrue(os.path.isfile(os.path.join(self.context_dir, "paper.pdf")))
        self.assertTrue(os.path.isfile(os.path.join(self.context_dir, "notes.md")))

    def test_u3b8_exits_1_on_missing_collection(self):
        """U3b-8: main() exits 1 on missing collection directory."""
        from clean_lancedb import main
        with patch("sys.argv", ["clean_lancedb", "nonexistent_collection", "--project-dir", self.tmpdir]):
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 1)

    def test_u3b9_exits_1_on_empty_collection_name(self):
        """U3b-9: main() exits 1 on whitespace-only collection name."""
        from clean_lancedb import main
        # Create a collection dir named "" (empty after strip) — should fail validation
        with patch("sys.argv", ["clean_lancedb", "   ", "--project-dir", self.tmpdir]):
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 1)

    def test_u3b10_help_exits_zero(self):
        """U3b-10: main() --help exits 0."""
        from clean_lancedb import main
        with patch("sys.argv", ["clean_lancedb", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 0)

    def test_u3b11_project_dir_flag(self):
        """U3b-11: main() --project-dir overrides cwd."""
        from clean_lancedb import main
        # Create images in the project-dir collection
        img_dir = os.path.join(self.context_dir, "images")
        os.makedirs(img_dir)
        Path(os.path.join(img_dir, "page.png")).write_text("img")

        # Run from a DIFFERENT cwd
        with tempfile.TemporaryDirectory() as other_cwd:
            orig_cwd = os.getcwd()
            os.chdir(other_cwd)
            try:
                with patch("sys.argv", ["clean_lancedb", self.collection, "--project-dir", self.tmpdir]):
                    main()
            finally:
                os.chdir(orig_cwd)

        self.assertFalse(os.path.exists(img_dir))


# ---------------------------------------------------------------------------
# pyproject.toml metadata tests
# ---------------------------------------------------------------------------

class TestPyprojectMetadata(unittest.TestCase):
    """U3c-1 through U3c-4: pyproject.toml entry points and classifiers."""

    @classmethod
    def setUpClass(cls):
        # Find pyproject.toml from the repo root
        # _test_dir = src/aider_factory/tests/aider_factory_tests/ -> 4 levels up = repo root
        search = os.path.abspath(os.path.join(_test_dir, "../../../.."))
        cls.pyproject_path = os.path.join(search, "pyproject.toml")
        if not os.path.isfile(cls.pyproject_path):
            # Try one more level up in case of nested layouts
            search2 = os.path.abspath(os.path.join(search, ".."))
            cls.pyproject_path = os.path.join(search2, "pyproject.toml")

    def _read_pyproject(self):
        self.assertTrue(
            os.path.isfile(self.pyproject_path),
            f"pyproject.toml not found at {self.pyproject_path}",
        )
        with open(self.pyproject_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_u3c1_entry_point_aider_launcher(self):
        """U3c-1: pyproject.toml has aider-launcher entry point."""
        content = self._read_pyproject()
        self.assertIn("aider-launcher", content)
        self.assertIn("factory_launcher:main", content)

    def test_u3c2_entry_point_aider_clean_lancedb(self):
        """U3c-2: pyproject.toml has aider-clean-lancedb entry point."""
        content = self._read_pyproject()
        self.assertIn("aider-clean-lancedb", content)
        self.assertIn("clean_lancedb:main", content)

    def test_u3c3_classifier_windows(self):
        """U3c-3: pyproject.toml has Windows OS classifier."""
        content = self._read_pyproject()
        self.assertIn("Operating System :: Microsoft :: Windows", content)

    def test_u3c4_classifier_macos(self):
        """U3c-4: pyproject.toml has MacOS classifier."""
        content = self._read_pyproject()
        self.assertIn("Operating System :: MacOS", content)


if __name__ == "__main__":
    unittest.main()
