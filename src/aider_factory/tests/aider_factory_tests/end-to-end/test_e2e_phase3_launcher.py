#!/usr/bin/env python3
"""E2E tests for Phase 3: factory_launcher.py and clean_lancedb.py.

These tests execute the real scripts as subprocesses in temporary directory
sandboxes. No mocking of the system under test.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


_test_dir = os.path.dirname(os.path.abspath(__file__))
_pkg_dir = os.path.abspath(os.path.join(_test_dir, "../../.."))
_python_dir = os.path.join(_pkg_dir, "python")


class TestE2EFactoryLauncher(unittest.TestCase):
    """E3a-1 through E3a-4: factory_launcher.py end-to-end."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)
        # Create minimal workspace structure
        af_dir = os.path.join(self.tmpdir, ".aider_factory")
        os.makedirs(os.path.join(af_dir, "logs"), exist_ok=True)

        # Create a fake run_workflow.py that prints markers and exits
        self.fake_workflow = os.path.join(self.tmpdir, "fake_workflow.py")
        Path(self.fake_workflow).write_text(textwrap.dedent("""\
            import sys
            print("LAUNCHER_TEE_MARKER_STDOUT_12345")
            sys.stderr.write("LAUNCHER_TEE_MARKER_STDERR_67890\\n")
            sys.exit(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
        """))

        # Create a fake aggregate_costs.py that prints a marker
        self.fake_agg = os.path.join(self.tmpdir, "fake_aggregate_costs.py")
        Path(self.fake_agg).write_text(textwrap.dedent("""\
            import sys
            print(f"AGGREGATE_COSTS_CALLED_WITH: {sys.argv[1] if len(sys.argv) > 1 else 'none'}")
        """))

        # Create a patched launcher that uses our fakes
        self.launcher_script = os.path.join(self.tmpdir, "test_launcher.py")
        launcher_src = Path(os.path.join(_python_dir, "factory_launcher.py")).read_text(encoding="utf-8").replace("\r\n", "\n")
        # Patch the workflow and aggregate script paths
        fake_wf = str(self.fake_workflow).replace("\\", "/")
        fake_ag = str(self.fake_agg).replace("\\", "/")
        patched = launcher_src.replace(
            'os.path.join(\n        os.path.dirname(os.path.abspath(__file__)), "run_workflow.py"\n    )',
            f'"{fake_wf}"',
        ).replace(
            'os.path.join(\n        os.path.dirname(os.path.abspath(__file__)), "aggregate_costs.py"\n    )',
            f'"{fake_ag}"',
        )
        Path(self.launcher_script).write_text(patched, encoding="utf-8")

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_launcher(self, extra_args=None, timeout=30):
        cmd = [sys.executable, self.launcher_script] + (extra_args or [])
        return subprocess.run(
            cmd,
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def test_e3a1_tee_output_in_terminal_and_log(self):
        """E3a-1: Launcher tees subprocess output to both terminal and log file."""
        result = self._run_launcher(extra_args=["0"])

        # Stdout must contain the marker (tee'd from subprocess)
        self.assertIn("LAUNCHER_TEE_MARKER_STDOUT_12345", result.stdout)

        # Find the log file
        logs_dir = os.path.join(self.tmpdir, ".aider_factory", "logs")
        log_files = [f for f in os.listdir(logs_dir) if f.endswith(".log")]
        self.assertTrue(len(log_files) > 0, "Log file must be created")

        log_content = Path(os.path.join(logs_dir, log_files[0])).read_text()
        self.assertIn("LAUNCHER_TEE_MARKER_STDOUT_12345", log_content)
        # stderr is merged via stderr=STDOUT, so it should also appear
        self.assertIn("LAUNCHER_TEE_MARKER_STDERR_67890", log_content)

    def test_e3a2_preserves_nonzero_exit_code(self):
        """E3a-2: Launcher preserves non-zero exit code from child process."""
        result = self._run_launcher(extra_args=["7"])
        self.assertEqual(result.returncode, 7)

    def test_e3a3_creates_log_file(self):
        """E3a-3: Launcher creates log file in .aider_factory/logs/."""
        self._run_launcher(extra_args=["0"])
        logs_dir = os.path.join(self.tmpdir, ".aider_factory", "logs")
        log_files = [f for f in os.listdir(logs_dir) if f.endswith(".log")]
        self.assertTrue(len(log_files) > 0)
        # Log file should have content
        log_path = os.path.join(logs_dir, log_files[0])
        self.assertGreater(os.path.getsize(log_path), 0)

    def test_e3a4_runs_cost_aggregation(self):
        """E3a-4: Launcher runs cost aggregation on log file."""
        result = self._run_launcher(extra_args=["0"])
        self.assertIn("AGGREGATE_COSTS_CALLED_WITH:", result.stdout)
        # The argument should be the log file path
        self.assertIn(".log", result.stdout)


class TestE2ECleanLancedb(unittest.TestCase):
    """E3b-1 through E3b-3: clean_lancedb.py end-to-end."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.collection = "e2e_test_collection"
        self.af_dir = os.path.join(self.tmpdir, ".aider_factory")
        self.context_dir = os.path.join(
            self.af_dir, "markdown", "lanceDB", self.collection
        )
        os.makedirs(self.context_dir, exist_ok=True)
        self.clean_script = os.path.join(_python_dir, "clean_lancedb.py")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_clean(self, args, timeout=15):
        cmd = [sys.executable, self.clean_script] + args
        return subprocess.run(
            cmd,
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def test_e3b1_full_cleanup_lifecycle(self):
        """E3b-1: Full cleanup: images removed, logs emptied, sources preserved."""
        # Create images
        img_dir = os.path.join(self.context_dir, "images")
        os.makedirs(img_dir)
        Path(os.path.join(img_dir, "page_001.png")).write_bytes(b"fake png 1")
        Path(os.path.join(img_dir, "page_002.png")).write_bytes(b"fake png 2")

        # Create validation and debate logs
        val_dir = os.path.join(self.af_dir, "logs", "validations")
        deb_dir = os.path.join(self.af_dir, "logs", "debates")
        os.makedirs(val_dir, exist_ok=True)
        os.makedirs(deb_dir, exist_ok=True)
        Path(os.path.join(val_dir, "report.md")).write_text("validation report")
        Path(os.path.join(val_dir, "ledger.json")).write_text('{"turns": []}')
        Path(os.path.join(deb_dir, "transcript.md")).write_text("debate transcript")

        # Create source files that must be preserved
        lance_dir = os.path.join(self.context_dir, "lancedb")
        os.makedirs(lance_dir, exist_ok=True)
        Path(os.path.join(lance_dir, "vectors.lance")).write_text("lance vectors")
        Path(os.path.join(self.context_dir, "paper.pdf")).write_bytes(b"PDF content")
        Path(os.path.join(self.context_dir, "notes.md")).write_text("# Research Notes")

        result = self._run_clean([self.collection, "--project-dir", self.tmpdir])
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

        # Images removed
        self.assertFalse(os.path.exists(img_dir))

        # Validation and debate logs emptied but dirs preserved
        self.assertTrue(os.path.isdir(val_dir))
        self.assertEqual(os.listdir(val_dir), [])
        self.assertTrue(os.path.isdir(deb_dir))
        self.assertEqual(os.listdir(deb_dir), [])

        # Sources preserved
        self.assertTrue(os.path.isfile(os.path.join(lance_dir, "vectors.lance")))
        self.assertTrue(os.path.isfile(os.path.join(self.context_dir, "paper.pdf")))
        self.assertTrue(os.path.isfile(os.path.join(self.context_dir, "notes.md")))

        # Output contains completion message
        self.assertIn("Cleanup complete", result.stdout)

    def test_e3b2_missing_collection_exits_1(self):
        """E3b-2: Missing collection exits 1 with error message."""
        result = self._run_clean(["nonexistent_xyz", "--project-dir", self.tmpdir])
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not exist", result.stderr)

    def test_e3b3_help_exits_zero(self):
        """E3b-3: --help exits 0 with usage information."""
        result = self._run_clean(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("collection", result.stdout)


if __name__ == "__main__":
    unittest.main()
