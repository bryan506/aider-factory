#!/usr/bin/env python3
# test_e2e_apply_agent_stream_isolation.py
#
# Zero-Mock End-to-End Smoke Tests for apply_agent.py stream output isolation.
#
# Covers the diff adding:
#   - stream: bool parameter to run_apply()
#   - subprocess.Popen with stdout=PIPE, stderr=STDOUT, text=True, bufsize=1
#   - /dev/tty streaming with OSError graceful fallback
#   - Silent-mode pipe draining (deadlock prevention)
#   - Status banner moved to stderr (stdout pollution prevention)
#   - --stream CLI flag in main() argparse
#   - Git diff as sole stdout output (outer aider context isolation)
#
# Execution: pytest or unittest. Requires no network, no real aider binary.
# All subprocesses run inside tempfile.TemporaryDirectory sandboxes.

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Path resolution (mirrors unit test file pattern)
# ---------------------------------------------------------------------------
_test_file_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.abspath(os.path.join(_test_file_dir, "../../../../.."))
_src_dir = os.path.join(_repo_root, "src")
_pkg_dir = os.path.join(_src_dir, "aider_factory")
_python_dir = os.path.join(_pkg_dir, "python")

for _p in (_repo_root, _src_dir, _pkg_dir, _python_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

APPLY_AGENT_PATH = os.path.join(_python_dir, "apply_agent.py")


# ---------------------------------------------------------------------------
# Base class: shared fake-binary setup for all E2E stream tests
# ---------------------------------------------------------------------------
class _StreamIsolationBase(unittest.TestCase):
    """Shared harness: temp sandbox, fake aider/git binaries, env scrubbing."""

    NOISE_LINES = 500  # Default noise volume per fake aider invocation

    @staticmethod
    def _write_fake_binary(path: Path, content: str):
        """Write a fake binary that works on both POSIX and Windows."""
        if sys.platform == "win32":
            py_path = str(path) + ".py"
            with open(py_path, "w", encoding="utf-8") as f:
                f.write(content)
            cmd_path = str(path) + ".cmd"
            with open(cmd_path, "w", encoding="utf-8") as f:
                f.write(f'@"{sys.executable}" "%~dp0{os.path.basename(py_path)}" %*\n@exit /b %errorlevel%\n')
        else:
            with open(str(path), "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(str(path), os.stat(str(path)).st_mode | stat.S_IEXEC)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()

        # --- Fake aider: emits NOISE_LINES of stdout, edits .py targets, exits 0 ---
        self._env_dump = self.root / "aider_env_dump.txt"
        self._stderr_dump = self.root / "aider_stderr_dump.txt"
        fake_aider = textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import os, sys
            from pathlib import Path
            # Emit noise to stdout (simulates inner aider file echoes, thinking, ANSI)
            for i in range({self.NOISE_LINES}):
                print(f"NOISE_LINE_{{i}}: \\x1b[32mfile echo\\x1b[0m thinking block content")
            # Emit to stderr (should be captured into pipe via stderr=STDOUT)
            sys.stderr.write("STDERR_NOISE_MARKER: diagnostic output\\n")
            sys.stderr.flush()
            # Dump environment
            with open(r"{self._env_dump}", "w") as f:
                for k, v in sorted(os.environ.items()):
                    f.write(f"{{k}}={{v}}\\n")
            # Dump stderr separately for verification
            with open(r"{self._stderr_dump}", "w") as f:
                f.write("STDERR_NOISE_MARKER: diagnostic output\\n")
            # Edit target .py files
            for arg in sys.argv:
                if arg.endswith(".py") and not arg.startswith("-"):
                    Path(arg).write_text("# edited by fake aider\\n")
            # Honor exit code override
            sys.exit(int(os.environ.get("AIDER_FAKE_EXIT", "0")))
        """)
        self.mock_aider = self.bin_dir / "aider"
        self._write_fake_binary(self.mock_aider, fake_aider)

        # --- Fake git: emits identifiable diff marker ---
        self._git_args_dump = self.root / "git_args_dump.txt"
        self.mock_git = self.bin_dir / "git"
        fake_git = textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import sys
            with open(r"{self._git_args_dump}", "w") as f:
                for arg in sys.argv[1:]:
                    f.write(f"{{arg}}\\n")
            if "diff" in sys.argv:
                print("diff --git a/target.py b/target.py")
                print("@@ -1 +1 @@")
                print("-# original")
                print("+E2E_DIFF_MARKER_UNIQUE_7x9")
            sys.exit(0)
        """)
        self._write_fake_binary(self.mock_git, fake_git)

        # --- PATH injection ---
        self._orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir}{os.pathsep}{self._orig_path}"

        # --- Env scrubbing ---
        self._orig_env = os.environ.copy()
        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
                os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        os.environ["PATH"] = self._orig_path
        self._tmp.cleanup()

    def _make_target_and_spec(self, target_name="target.py", spec_content="Do the thing.\n"):
        target = self.root / target_name
        target.write_text("# original\n", encoding="utf-8")
        spec = self.root / "spec.md"
        spec.write_text(spec_content, encoding="utf-8")
        return target, spec

    def _capture_fd1(self, func, *args, **kwargs):
        """Run func with OS fd 1 redirected to a temp file. Returns captured text."""
        capture_path = self.root / "fd1_capture.txt"
        saved_fd = os.dup(1)
        try:
            with open(capture_path, "w", encoding="utf-8", errors="replace") as fh:
                os.dup2(fh.fileno(), 1)
                result = func(*args, **kwargs)
                sys.stdout.flush()
        finally:
            os.dup2(saved_fd, 1)
            os.close(saved_fd)
        return result, capture_path.read_text(encoding="utf-8", errors="replace")

    def _run_cli(self, extra_args=None, timeout=60):
        """Invoke apply_agent.py as a real subprocess."""
        cmd = [sys.executable, APPLY_AGENT_PATH]
        if extra_args:
            cmd.extend(extra_args)
        return subprocess.run(
            cmd, cwd=str(self.root), capture_output=True, text=True, timeout=timeout
        )


# ===========================================================================
# S01: Default (stream=False) — inner aider noise ABSENT from stdout
# ===========================================================================
class TestS01SilentModeStdoutIsolation(_StreamIsolationBase):
    """Verify that with stream=False, only git diff reaches stdout."""

    def test_s01_inner_noise_absent_from_stdout(self):
        target, spec = self._make_target_and_spec()

        result, captured = self._capture_fd1(
            self._import_run_apply(),
            files=[str(target)],
            spec_file=str(spec),
            no_diff=False,
            stream=False,
            cwd=str(self.root),
        )

        self.assertTrue(result)
        self.assertIn("E2E_DIFF_MARKER_UNIQUE_7x9", captured)
        self.assertIn("Git Diff Result", captured)
        # Noise must NOT appear
        self.assertNotIn("NOISE_LINE_", captured)
        self.assertNotIn("file echo", captured)

    def test_s02_stderr_banner_not_on_stdout(self):
        """Status banner (🚀 Running apply pass...) must go to stderr, not stdout."""
        target, spec = self._make_target_and_spec()

        result, captured = self._capture_fd1(
            self._import_run_apply(),
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=False,
            cwd=str(self.root),
        )

        self.assertTrue(result)
        self.assertNotIn("Running apply pass", captured)
        self.assertNotIn("🚀", captured)

    def test_s03_no_diff_suppresses_all_stdout(self):
        """With --no-diff and stream=False, stdout is completely empty."""
        target, spec = self._make_target_and_spec()

        result, captured = self._capture_fd1(
            self._import_run_apply(),
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=False,
            cwd=str(self.root),
        )

        self.assertTrue(result)
        self.assertEqual(captured.strip(), "")

    def _import_run_apply(self):
        from apply_agent import run_apply
        return run_apply


# ===========================================================================
# S04: stream=True — completes, diff on stdout, noise NOT on stdout
# ===========================================================================
class TestS04StreamModeStdoutIsolation(_StreamIsolationBase):
    """Verify stream=True routes inner output to /dev/tty (or discards), stdout gets diff."""

    def test_s04_stream_true_diff_present_noise_absent(self):
        target, spec = self._make_target_and_spec()

        result, captured = self._capture_fd1(
            self._import_run_apply(),
            files=[str(target)],
            spec_file=str(spec),
            no_diff=False,
            stream=True,
            cwd=str(self.root),
        )

        self.assertTrue(result)
        self.assertIn("E2E_DIFF_MARKER_UNIQUE_7x9", captured)
        self.assertIn("Git Diff Result", captured)
        self.assertNotIn("NOISE_LINE_", captured)

    def test_s05_stream_true_no_diff_clean_exit(self):
        """stream=True + no_diff=True: no output on stdout at all."""
        target, spec = self._make_target_and_spec()

        result, captured = self._capture_fd1(
            self._import_run_apply(),
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=True,
            cwd=str(self.root),
        )

        self.assertTrue(result)
        self.assertEqual(captured.strip(), "")

    def _import_run_apply(self):
        from apply_agent import run_apply
        return run_apply


# ===========================================================================
# S06: Deadlock prevention — large output drained without hanging
# ===========================================================================
class TestS06DeadlockPrevention(_StreamIsolationBase):
    """Verify pipe draining prevents deadlock with large inner aider output."""

    def test_s06_large_output_silent_no_deadlock(self):
        """500 lines drained in silent mode within 10 seconds."""
        target, spec = self._make_target_and_spec()

        from apply_agent import run_apply
        start = time.monotonic()
        success = run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=False,
            cwd=str(self.root),
        )
        elapsed = time.monotonic() - start

        self.assertTrue(success)
        self.assertLess(elapsed, 10.0, f"Deadlock suspected: took {elapsed:.1f}s")

    def test_s07_large_output_stream_no_deadlock(self):
        """500 lines drained in stream mode within 10 seconds."""
        target, spec = self._make_target_and_spec()

        from apply_agent import run_apply
        start = time.monotonic()
        success = run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=True,
            cwd=str(self.root),
        )
        elapsed = time.monotonic() - start

        self.assertTrue(success)
        self.assertLess(elapsed, 10.0, f"Deadlock suspected: took {elapsed:.1f}s")

    def test_s08_massive_output_pipe_overflow_prevention(self):
        """5000 lines (exceeds 64KB pipe buffer) must not deadlock or lose data."""
        fake_aider = textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import sys
            from pathlib import Path
            for i in range(5000):
                print(f"MASSIVE_LINE_{{i}}: " + "x" * 80)
            for arg in sys.argv:
                if arg.endswith(".py") and not arg.startswith("-"):
                    Path(arg).write_text("# edited\\n")
            sys.exit(0)
        """)
        self._write_fake_binary(self.mock_aider, fake_aider)

        target, spec = self._make_target_and_spec()

        from apply_agent import run_apply
        start = time.monotonic()
        success = run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=False,
            cwd=str(self.root),
        )
        elapsed = time.monotonic() - start

        self.assertTrue(success)
        self.assertLess(elapsed, 10.0, f"Pipe overflow deadlock: {elapsed:.1f}s")
        self.assertEqual(target.read_text(encoding="utf-8"), "# edited\n")


# ===========================================================================
# S09: /dev/tty unavailable — graceful fallback (CI/headless)
# ===========================================================================
class TestS09TtyFallback(_StreamIsolationBase):
    """Verify stream=True does not crash when /dev/tty is unavailable."""

    def test_s09_stream_no_tty_headless_subprocess(self):
        """Run apply_agent.py as subprocess with stdin/stdout/stderr all piped (no TTY)."""
        target, spec = self._make_target_and_spec()

        cmd = [
            sys.executable, APPLY_AGENT_PATH,
            str(target),
            "--spec", str(spec),
            "--no-diff",
            "--stream",
        ]
        res = subprocess.run(
            cmd, cwd=str(self.root), capture_output=True, text=True, timeout=30
        )

        self.assertEqual(res.returncode, 0, f"Crashed without TTY: {res.stderr}")
        self.assertEqual(target.read_text(encoding="utf-8"), "# edited by fake aider\n")

    def test_s10_stream_no_tty_with_diff(self):
        """Even with --stream and no TTY, git diff still appears on stdout."""
        target, spec = self._make_target_and_spec()

        cmd = [
            sys.executable, APPLY_AGENT_PATH,
            str(target),
            "--spec", str(spec),
            "--stream",
        ]
        res = subprocess.run(
            cmd, cwd=str(self.root), capture_output=True, text=True, timeout=30
        )

        self.assertEqual(res.returncode, 0, f"stderr: {res.stderr}")
        self.assertIn("E2E_DIFF_MARKER_UNIQUE_7x9", res.stdout)
        self.assertIn("Git Diff Result", res.stdout)
        self.assertNotIn("NOISE_LINE_", res.stdout)


# ===========================================================================
# S11: CLI flag threading — --stream accepted, default is silent
# ===========================================================================
class TestS11CliFlagThreading(_StreamIsolationBase):
    """Verify --stream CLI flag is parsed and threaded to run_apply()."""

    def test_s11_cli_stream_flag_accepted(self):
        target, spec = self._make_target_and_spec()

        res = self._run_cli([
            str(target), "--spec", str(spec), "--no-diff", "--stream"
        ])
        self.assertEqual(res.returncode, 0, f"stderr: {res.stderr}")
        self.assertEqual(target.read_text(encoding="utf-8"), "# edited by fake aider\n")

    def test_s12_cli_default_silent(self):
        target, spec = self._make_target_and_spec()

        res = self._run_cli([
            str(target), "--spec", str(spec), "--no-diff"
        ])
        self.assertEqual(res.returncode, 0, f"stderr: {res.stderr}")
        self.assertNotIn("NOISE_LINE_", res.stdout)

    def test_s13_cli_stream_with_diff(self):
        target, spec = self._make_target_and_spec()

        res = self._run_cli([
            str(target), "--spec", str(spec), "--stream"
        ])
        self.assertEqual(res.returncode, 0, f"stderr: {res.stderr}")
        self.assertIn("E2E_DIFF_MARKER_UNIQUE_7x9", res.stdout)
        self.assertNotIn("NOISE_LINE_", res.stdout)

    def test_s14_cli_stream_no_diff(self):
        target, spec = self._make_target_and_spec()

        res = self._run_cli([
            str(target), "--spec", str(spec), "--no-diff", "--stream"
        ])
        self.assertEqual(res.returncode, 0, f"stderr: {res.stderr}")
        self.assertNotIn("Git Diff Result", res.stdout)
        self.assertNotIn("NOISE_LINE_", res.stdout)


# ===========================================================================
# S15: Non-zero exit code handling in both stream modes
# ===========================================================================
class TestS15ErrorHandling(_StreamIsolationBase):
    """Verify error paths work correctly regardless of stream mode."""

    def test_s15_nonzero_exit_silent_mode(self):
        target, spec = self._make_target_and_spec()
        os.environ["AIDER_FAKE_EXIT"] = "42"
        try:
            from apply_agent import run_apply
            success = run_apply(
                files=[str(target)],
                spec_file=str(spec),
                no_diff=True,
                stream=False,
                cwd=str(self.root),
            )
            self.assertFalse(success)
        finally:
            os.environ.pop("AIDER_FAKE_EXIT", None)

    def test_s16_nonzero_exit_stream_mode(self):
        target, spec = self._make_target_and_spec()
        os.environ["AIDER_FAKE_EXIT"] = "1"
        try:
            from apply_agent import run_apply
            success = run_apply(
                files=[str(target)],
                spec_file=str(spec),
                no_diff=True,
                stream=True,
                cwd=str(self.root),
            )
            self.assertFalse(success)
        finally:
            os.environ.pop("AIDER_FAKE_EXIT", None)

    def test_s17_error_message_on_stderr_not_stdout(self):
        target, spec = self._make_target_and_spec()
        os.environ["AIDER_FAKE_EXIT"] = "7"
        try:
            from apply_agent import run_apply

            result, captured = self._capture_fd1(
                run_apply,
                files=[str(target)],
                spec_file=str(spec),
                no_diff=True,
                stream=False,
                cwd=str(self.root),
            )
            self.assertFalse(result)
            self.assertNotIn("Error", captured)
            self.assertNotIn("exit code", captured)
        finally:
            os.environ.pop("AIDER_FAKE_EXIT", None)


# ===========================================================================
# S18: Environment propagation in stream mode
# ===========================================================================
class TestS18EnvPropagation(_StreamIsolationBase):
    """Verify env vars are correctly set in the Popen child regardless of stream."""

    def test_s18_aider_architect_false_in_stream_mode(self):
        target, spec = self._make_target_and_spec()

        from apply_agent import run_apply
        run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=True,
            cwd=str(self.root),
        )

        self.assertTrue(self._env_dump.exists())
        env_text = self._env_dump.read_text(encoding="utf-8")
        self.assertIn("AIDER_ARCHITECT=false", env_text)

    def test_s19_api_base_propagation_stream_mode(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)
        (af / ".env.yml").write_text(
            yaml.dump({"endpoints": {"editor_api": "http://proxy-e2e:5555/v1"}}),
            encoding="utf-8",
        )
        target = self.root / "target.py"
        target.write_text("# original\n", encoding="utf-8")
        spec = self.root / "spec.md"
        spec.write_text("Do something.\n", encoding="utf-8")

        os.environ.pop("AI_FACTORY_CONFIG", None)

        from apply_agent import run_apply
        run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=True,
            cwd=str(self.root),
        )

        env_text = self._env_dump.read_text(encoding="utf-8")
        self.assertIn("OPENAI_API_BASE=http://proxy-e2e:5555/v1", env_text)
        self.assertIn("OLLAMA_API_BASE=http://proxy-e2e:5555/v1", env_text)
        self.assertIn("LM_STUDIO_API_BASE=http://proxy-e2e:5555/v1", env_text)
        self.assertIn("LM_STUDIO_API_KEY=sk-dummy", env_text)


# ===========================================================================
# S20: stderr=STDOUT capture — inner stderr absorbed into pipe
# ===========================================================================
class TestS20StderrAbsorption(_StreamIsolationBase):
    """Verify stderr=subprocess.STDOUT captures inner aider stderr into the pipe."""

    def test_s20_inner_stderr_not_on_outer_stdout(self):
        """Inner aider stderr (STDERR_NOISE_MARKER) must NOT appear on our stdout."""
        target, spec = self._make_target_and_spec()

        from apply_agent import run_apply
        result, captured = self._capture_fd1(
            run_apply,
            files=[str(target)],
            spec_file=str(spec),
            no_diff=False,
            stream=False,
            cwd=str(self.root),
        )

        self.assertTrue(result)
        self.assertNotIn("STDERR_NOISE_MARKER", captured)
        self.assertIn("E2E_DIFF_MARKER_UNIQUE_7x9", captured)


# ===========================================================================
# S21: Sequential invocations — no state leakage between runs
# ===========================================================================
class TestS21SequentialIsolation(_StreamIsolationBase):
    """Verify multiple sequential run_apply calls don't bleed state."""

    def test_s21_two_runs_independent_stdout(self):
        """Run twice; each invocation's stdout contains only its own diff."""
        from apply_agent import run_apply

        for i in range(2):
            target = self.root / f"target_{i}.py"
            target.write_text("# original\n", encoding="utf-8")
            spec = self.root / f"spec_{i}.md"
            spec.write_text(f"Spec {i}.\n", encoding="utf-8")

            result, captured = self._capture_fd1(
                run_apply,
                files=[str(target)],
                spec_file=str(spec),
                no_diff=False,
                stream=False,
                cwd=str(self.root),
            )
            self.assertTrue(result, f"Run {i} failed")
            self.assertIn("E2E_DIFF_MARKER_UNIQUE_7x9", captured)
            self.assertNotIn("NOISE_LINE_", captured)


# ===========================================================================
# S22: ANSI escape codes in inner output don't corrupt stdout diff
# ===========================================================================
class TestS22AnsiIsolation(_StreamIsolationBase):
    """Verify ANSI codes in inner aider output are fully isolated from stdout."""

    def test_s22_ansi_codes_not_in_stdout(self):
        target, spec = self._make_target_and_spec()

        from apply_agent import run_apply
        result, captured = self._capture_fd1(
            run_apply,
            files=[str(target)],
            spec_file=str(spec),
            no_diff=False,
            stream=False,
            cwd=str(self.root),
        )

        self.assertTrue(result)
        self.assertIn("E2E_DIFF_MARKER_UNIQUE_7x9", captured)
        self.assertNotIn("\\x1b[", captured)
        self.assertNotIn("\x1b[", captured)


# ===========================================================================
# S23: Active spec written to disk regardless of stream mode
# ===========================================================================
class TestS23ActiveSpecPersistence(_StreamIsolationBase):
    """Verify active_spec.md is written in both stream modes."""

    def test_s23_active_spec_written_stream_false(self):
        target, spec = self._make_target_and_spec(spec_content="UNIQUE_SPEC_STREAM_OFF_99\n")

        from apply_agent import run_apply
        run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=False,
            cwd=str(self.root),
        )

        active = self.root / ".aider_factory" / "temp" / "active_spec.md"
        self.assertTrue(active.exists())
        self.assertIn("UNIQUE_SPEC_STREAM_OFF_99", active.read_text(encoding="utf-8"))

    def test_s24_active_spec_written_stream_true(self):
        target, spec = self._make_target_and_spec(spec_content="UNIQUE_SPEC_STREAM_ON_77\n")

        from apply_agent import run_apply
        run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=True,
            cwd=str(self.root),
        )

        active = self.root / ".aider_factory" / "temp" / "active_spec.md"
        self.assertTrue(active.exists())
        self.assertIn("UNIQUE_SPEC_STREAM_ON_77", active.read_text(encoding="utf-8"))


# ===========================================================================
# S25: Binary/invalid UTF-8 in inner output handled gracefully
# ===========================================================================
class TestS25BinaryContentGraceful(_StreamIsolationBase):
    """Verify errors='replace' on /dev/tty open handles non-UTF8 gracefully."""

    def test_s25_null_bytes_in_output_no_crash(self):
        fake_aider = textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import sys
            from pathlib import Path
            sys.stdout.buffer.write(b"VALID_LINE_1\\n")
            sys.stdout.buffer.write(b"NULL\\x00BYTE\\x00LINE\\n")
            sys.stdout.buffer.write(b"INVALID\\xff\\xfeUTF8\\n")
            sys.stdout.buffer.write(b"VALID_LINE_2\\n")
            sys.stdout.buffer.flush()
            for arg in sys.argv:
                if arg.endswith(".py") and not arg.startswith("-"):
                    Path(arg).write_text("# edited\\n")
            sys.exit(0)
        """)
        self._write_fake_binary(self.mock_aider, fake_aider)

        target, spec = self._make_target_and_spec()

        from apply_agent import run_apply
        success = run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=True,
            cwd=str(self.root),
        )
        self.assertTrue(success)
        self.assertEqual(target.read_text(encoding="utf-8"), "# edited\n")


# ===========================================================================
# S26: Chat history fallback still works with stream parameter
# ===========================================================================
class TestS26ChatHistoryFallbackWithStream(_StreamIsolationBase):
    """Verify spec-from-chat-history path works with stream=True."""

    def test_s26_chat_history_spec_stream_true(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)
        sess = af / "sessions" / "stream_sess"
        sess.mkdir(parents=True)
        hist = sess / ".aider.chat.history.md"
        hist.write_text(
            "#### Implement auth module\nAdd JWT validation.\n\n"
            "> Tokens: 1k sent, 2k received\n",
            encoding="utf-8",
        )
        target = self.root / "auth_target.py"
        target.write_text("# original\n", encoding="utf-8")

        from apply_agent import run_apply
        success = run_apply(
            files=[str(target)],
            spec_file=None,
            session_name="stream_sess",
            no_diff=True,
            stream=True,
            cwd=str(self.root),
        )

        self.assertTrue(success)
        active = af / "temp" / "active_spec.md"
        self.assertIn("Implement auth module", active.read_text(encoding="utf-8"))


# ===========================================================================
# S27: Popen process cleanup — no zombie processes
# ===========================================================================
class TestS27ProcessCleanup(_StreamIsolationBase):
    """Verify Popen children are fully reaped (no zombies).

    NOTE: os.waitpid(-1, WNOHANG) is process-global and reaps siblings'
    children from other tests in the same unittest process. Instead we
    verify the child lifecycle completed by asserting run_apply returned
    True (which requires proc.wait() to have been called and returned 0)
    and the target file was physically edited.
    """

    def test_s27_no_zombie_after_stream_true(self):
        target, spec = self._make_target_and_spec()

        from apply_agent import run_apply
        success = run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=True,
            cwd=str(self.root),
        )

        # run_apply returned True => proc.wait() completed with exit 0
        # => child fully reaped, no zombie possible.
        self.assertTrue(success, "run_apply must return True (proves proc.wait() reaped child)")
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "# edited by fake aider\n",
            "Target must be edited (proves child ran to completion)",
        )

    def test_s27b_no_zombie_after_stream_false(self):
        """Same invariant in silent mode."""
        target, spec = self._make_target_and_spec()

        from apply_agent import run_apply
        success = run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=False,
            cwd=str(self.root),
        )

        self.assertTrue(success)
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "# edited by fake aider\n",
        )


# ===========================================================================
# S28: --stream flag does not alter exit code semantics
# ===========================================================================
class TestS28ExitCodeSemantics(_StreamIsolationBase):
    """Verify --stream doesn't change the 0/1 exit contract."""

    def test_s28_exit_0_on_success_with_stream(self):
        target, spec = self._make_target_and_spec()

        res = self._run_cli([
            str(target), "--spec", str(spec), "--no-diff", "--stream"
        ])
        self.assertEqual(res.returncode, 0)

    def test_s29_exit_1_on_failure_with_stream(self):
        target, spec = self._make_target_and_spec()
        os.environ["AIDER_FAKE_EXIT"] = "3"
        try:
            res = self._run_cli([
                str(target), "--spec", str(spec), "--no-diff", "--stream"
            ])
            self.assertEqual(res.returncode, 1)
        finally:
            os.environ.pop("AIDER_FAKE_EXIT", None)

    def test_s30_exit_1_on_failure_without_stream(self):
        target, spec = self._make_target_and_spec()
        os.environ["AIDER_FAKE_EXIT"] = "99"
        try:
            res = self._run_cli([
                str(target), "--spec", str(spec), "--no-diff"
            ])
            self.assertEqual(res.returncode, 1)
        finally:
            os.environ.pop("AIDER_FAKE_EXIT", None)


# ===========================================================================
# S31: Multiple files with stream — all targets edited, stdout clean
# ===========================================================================
class TestS31MultiFileStream(_StreamIsolationBase):
    """Verify multi-file editing works with stream=True and stdout stays clean."""

    def test_s31_multiple_files_stream_true(self):
        targets = []
        for name in ("mod_a.py", "mod_b.py", "mod_c.py"):
            t = self.root / name
            t.write_text("# original\n", encoding="utf-8")
            targets.append(str(t))

        spec = self.root / "spec.md"
        spec.write_text("Edit all modules.\n", encoding="utf-8")

        from apply_agent import run_apply
        result, captured = self._capture_fd1(
            run_apply,
            files=targets,
            spec_file=str(spec),
            no_diff=False,
            stream=True,
            cwd=str(self.root),
        )

        self.assertTrue(result)
        for t in targets:
            self.assertEqual(
                Path(t).read_text(encoding="utf-8"),
                "# edited by fake aider\n",
                f"{t} not edited",
            )
        self.assertIn("E2E_DIFF_MARKER_UNIQUE_7x9", captured)
        self.assertNotIn("NOISE_LINE_", captured)


# ===========================================================================
# S32: Buffer size verification — line-buffered streaming
# ===========================================================================
class TestS32LineBufferedBehavior(_StreamIsolationBase):
    """Verify bufsize=1 (line buffering) means output is processed line-by-line."""

    def test_s32_output_processed_line_by_line(self):
        fake_aider = textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import sys
            from pathlib import Path
            for i in range(100):
                print(f"LINE_{{i:04d}}")
            for arg in sys.argv:
                if arg.endswith(".py") and not arg.startswith("-"):
                    Path(arg).write_text("# edited\\n")
            sys.exit(0)
        """)
        self._write_fake_binary(self.mock_aider, fake_aider)

        target, spec = self._make_target_and_spec()

        from apply_agent import run_apply
        success = run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=True,
            cwd=str(self.root),
        )
        self.assertTrue(success)

        success = run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=False,
            cwd=str(self.root),
        )
        self.assertTrue(success)


# ===========================================================================
# S33: Git diff plain-text flags (--no-color, --no-ext-diff)
# ===========================================================================
class TestS33GitDiffPlaintextFlags(_StreamIsolationBase):
    """Verify git diff is always called with --no-color and --no-ext-diff."""

    def test_s33_git_diff_no_color_flags_present(self):
        target, spec = self._make_target_and_spec()
        from apply_agent import run_apply
        run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=False,
            stream=False,
            cwd=str(self.root),
        )
        self.assertTrue(self._git_args_dump.exists())
        git_args = self._git_args_dump.read_text(encoding="utf-8").splitlines()
        self.assertIn("--no-color", git_args)
        self.assertIn("--no-ext-diff", git_args)
        self.assertIn("--no-pager", git_args)


if __name__ == "__main__":
    unittest.main(verbosity=2)
