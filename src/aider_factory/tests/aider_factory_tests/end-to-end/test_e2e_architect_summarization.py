#!/usr/bin/env python3
"""
test_e2e_architect_summarization.py

E2E probe: does aider's chat-history summarization behave differently
in --architect mode? Specifically:
  1. Does threshold-based auto-summarization fire without /clear?
  2. Does /clear trigger summarization in architect mode?
  3. Which model does aider use for summarization in architect mode?

Zero-mock. Real aider binary. Real Gemini calls. Temp-dir sandbox.
Watch llama.cpp logs for local weak-model activity.

Run:
    uv run --with pytest pytest src/aider_factory/tests/aider_factory_tests/end-to-end/test_e2e_architect_summarization.py -v -s
"""

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

AIDER_BIN = shutil.which("aider") or "aider"

MAIN_MODEL = os.environ.get("TEST_MAIN_MODEL", "gemini/gemini-3.7-flash")
WEAK_MODEL = os.environ.get("TEST_WEAK_MODEL", "lm_studio/qwen3.8-27B-90k-udq4km:LATEST")
LM_STUDIO_API_BASE = os.environ.get("LM_STUDIO_API_BASE", "http://192.168.100.1:8080/v1")
LM_STUDIO_API_KEY = os.environ.get("LM_STUDIO_API_KEY", "sk-dummy")

ARCHITECT_THRESHOLD = int(os.environ.get("TEST_ARCH_THRESHOLD", "5000"))

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent.parent.parent.parent
CLI_PY_PATH = _PROJECT_ROOT / "src" / "aider_factory" / "cli.py"


@pytest.fixture()
def sandbox_architect(tmp_path: Path) -> Path:
    """Git repo with architect: true and 5k threshold."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "e2e@test.local"],
        cwd=repo,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "E2E"], cwd=repo, capture_output=True
    )

    if CLI_PY_PATH.exists():
        shutil.copy2(CLI_PY_PATH, repo / "cli.py")
    else:
        lines = ["# Synthetic\n"] * 400
        (repo / "cli.py").write_text("\n".join(lines))

    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, capture_output=True
    )

    conf = repo / ".aider.conf.yml"
    conf.write_text(
        f"model: {MAIN_MODEL}\n"
        f"weak-model: {WEAK_MODEL}\n"
        "architect: true\n"
        f"max-chat-history-tokens: {ARCHITECT_THRESHOLD}\n"
        "auto-commits: false\n"
        "auto-lint: false\n"
        "map-tokens: 0\n"
        "map-refresh: manual\n"
        "yes-always: true\n"
        "no-show-model-warnings: true\n"
        "check-update: false\n"
        "analytics: false\n"
        "notifications: false\n"
        "verbose: true\n"
    )
    return repo


class TestArchitectSummarization:

    def test_01_architect_threshold_no_clear(self, sandbox_architect: Path):
        """4 verbose prompts in architect mode. NO /clear. Threshold=5000.
        Does aider auto-summarize when history crosses 5k?
        Watch llama.cpp for weak-model inference between turns."""

        env = {
            **os.environ,
            "LM_STUDIO_API_BASE": LM_STUDIO_API_BASE,
            "LM_STUDIO_API_KEY": LM_STUDIO_API_KEY,
        }

        cmd = [
            AIDER_BIN,
            "--architect",
            "--yes-always",
            "--verbose",
            "--no-check-update",
            "--no-analytics",
            "--map-tokens", "0",
            "--no-auto-commits",
            "--no-auto-lint",
        ]

        print(f"\n{'═' * 70}")
        print(f"  ARCHITECT MODE — THRESHOLD AUTO-SUMMARIZATION (NO /clear)")
        print(f"  │ model: {MAIN_MODEL}  weak: {WEAK_MODEL}")
        print(f"  │ threshold: {ARCHITECT_THRESHOLD}")
        print(f"  │ architect: true")
        print(f"  │ Watch llama.cpp for inference between turns!")
        print(f"{'═' * 70}\n", flush=True)

        proc = subprocess.Popen(
            cmd,
            cwd=str(sandbox_architect),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        prompts = [
            "Read cli.py. Explain _ensure_git_repo, _is_test_path, "
            "_read_user_aiderignore, _scan_repo_files in extreme detail. "
            "Every parameter, regex, edge case. Be very verbose.\n",
            "Now explain _build_repomap_ignore_content and _generate_repo_maps "
            "in exhaustive detail. Every ignore rule, ephemeral pattern.\n",
            "Explain _ensure_baseline_aiderignore, _backup_workspace_cache, "
            "_list_sessions. Every branch. Be very verbose.\n",
            "Explain _get_registry_path, _register_project, _clear_session. "
            "Every code path. Be very verbose.\n",
            "exit\n",
        ]

        def _feed():
            for i, p in enumerate(prompts):
                try:
                    proc.stdin.write(p)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    return
                # Architect mode is slower (plan + execute per turn)
                time.sleep(35 if i < 4 else 5)
            time.sleep(10)
            try:
                proc.stdin.close()
            except OSError:
                pass

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def _read(stream, sink):
            for line in iter(stream.readline, ""):
                sink.append(line)
            try:
                stream.close()
            except OSError:
                pass

        feeder = threading.Thread(target=_feed, daemon=True)
        t_out = threading.Thread(
            target=_read, args=(proc.stdout, stdout_chunks), daemon=True
        )
        t_err = threading.Thread(
            target=_read, args=(proc.stderr, stderr_chunks), daemon=True
        )
        t_out.start()
        t_err.start()
        feeder.start()

        feeder.join(timeout=240)
        try:
            proc.wait(timeout=90)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        t_out.join(timeout=15)
        t_err.join(timeout=15)

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        combined = stdout + stderr

        # Detection
        summary_log = re.search(
            r"(?i)(summariz|compact|condens|trimming chat)", combined
        )
        chat_hist = sandbox_architect / ".aider.chat.history.md"
        hist_size = chat_hist.stat().st_size if chat_hist.is_file() else 0

        # Check for architect-specific output
        architect_ran = bool(
            re.search(r"(?i)(architect|planning|plan generated)", combined)
        )

        print(f"\n{'═' * 70}")
        print(f"  ARCHITECT THRESHOLD RESULTS")
        print(f"{'═' * 70}")
        print(f"  [A] aider log mentions summarization: {bool(summary_log)}")
        print(f"  [B] chat_history.md size: {hist_size} bytes")
        print(f"  [C] architect mode active: {architect_ran}")
        print(f"  [D] aider exit code: {proc.returncode}")
        print(f"{'═' * 70}\n", flush=True)

        assert proc.returncode == 0, f"aider crashed: {stderr[-500:]}"

        if summary_log:
            print(
                f"  ✅ Threshold summarization FIRED in architect mode: "
                f"{summary_log.group(0)!r}"
            )
        else:
            print(
                "  ℹ️  No summarization detected in aider's stdout/stderr.\n"
                "     CHECK LLAMA.CPP LOGS: if the local model fired during\n"
                "     this test window, summarization DID occur but aider\n"
                "     didn't log it. If llama.cpp is silent, architect mode\n"
                "     does NOT auto-summarize on threshold.\n"
                "     This is the key finding for architect mode."
            )

    def test_02_architect_clear_triggers_summarization(self, sandbox_architect: Path):
        """3 verbose prompts + /clear in architect mode.
        Does /clear trigger weak-model summarization in architect mode?
        Direct comparison to test_06 in the non-architect suite."""

        env = {
            **os.environ,
            "LM_STUDIO_API_BASE": LM_STUDIO_API_BASE,
            "LM_STUDIO_API_KEY": LM_STUDIO_API_KEY,
        }

        cmd = [
            AIDER_BIN,
            "--architect",
            "--yes-always",
            "--verbose",
            "--no-check-update",
            "--no-analytics",
            "--map-tokens", "0",
            "--no-auto-commits",
            "--no-auto-lint",
        ]

        print(f"\n{'═' * 70}")
        print(f"  ARCHITECT MODE — /clear SUMMARIZATION PROBE")
        print(f"  │ model: {MAIN_MODEL}  weak: {WEAK_MODEL}")
        print(f"  │ architect: true")
        print(f"  │ Watch llama.cpp for inference at /clear!")
        print(f"{'═' * 70}\n", flush=True)

        proc = subprocess.Popen(
            cmd,
            cwd=str(sandbox_architect),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        prompts = [
            "Read cli.py. Explain _ensure_git_repo, _is_test_path, "
            "_read_user_aiderignore, _scan_repo_files in extreme detail. "
            "Every parameter, regex, edge case. Be very verbose.\n",
            "Now explain _build_repomap_ignore_content and _generate_repo_maps "
            "in exhaustive detail. Every ignore rule, ephemeral pattern.\n",
            "Explain _ensure_baseline_aiderignore, _backup_workspace_cache, "
            "_list_sessions. Every branch. Be very verbose.\n",
            "/clear\n",
            "exit\n",
        ]

        def _feed():
            for i, p in enumerate(prompts):
                try:
                    proc.stdin.write(p)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    return
                time.sleep(35 if i < 3 else 10)
            time.sleep(10)
            try:
                proc.stdin.close()
            except OSError:
                pass

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def _read(stream, sink):
            for line in iter(stream.readline, ""):
                sink.append(line)
            try:
                stream.close()
            except OSError:
                pass

        feeder = threading.Thread(target=_feed, daemon=True)
        t_out = threading.Thread(
            target=_read, args=(proc.stdout, stdout_chunks), daemon=True
        )
        t_err = threading.Thread(
            target=_read, args=(proc.stderr, stderr_chunks), daemon=True
        )
        t_out.start()
        t_err.start()
        feeder.start()

        feeder.join(timeout=240)
        try:
            proc.wait(timeout=90)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        t_out.join(timeout=15)
        t_err.join(timeout=15)

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        combined = stdout + stderr

        summary_log = re.search(
            r"(?i)(summariz|compact|condens|clearing chat|resetting chat)",
            combined,
        )
        chat_hist = sandbox_architect / ".aider.chat.history.md"
        hist_size = chat_hist.stat().st_size if chat_hist.is_file() else 0

        print(f"\n{'═' * 70}")
        print(f"  ARCHITECT /clear RESULTS")
        print(f"{'═' * 70}")
        print(f"  [A] aider log mentions summarization: {bool(summary_log)}")
        print(f"  [B] chat_history.md size: {hist_size} bytes")
        print(f"  [C] aider exit code: {proc.returncode}")
        print(f"{'═' * 70}\n", flush=True)

        assert proc.returncode == 0, f"aider crashed: {stderr[-500:]}"

        if summary_log:
            print("  ✅ /clear triggers summarization in architect mode.")
        else:
            print(
                "  ℹ️  No summarization in stdout. CHECK LLAMA.CPP:\n"
                "     If local model fired → /clear works in architect mode,\n"
                "     aider just doesn't log it.\n"
                "     If silent → /clear does NOT summarize in architect mode.\n"
                "     This would mean architect mode bypasses summarization entirely."
            )

    def test_03_architect_vs_coder_comparison(self, tmp_path: Path):
        """Same prompts, /clear, same config. Run with and without --architect.
        Compare timing and history size to detect different code paths."""

        results = {}

        for mode in ("coder", "architect"):
            repo = tmp_path / mode
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "cmp@test.local"],
                cwd=repo,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Cmp"],
                cwd=repo,
                capture_output=True,
            )
            if CLI_PY_PATH.exists():
                shutil.copy2(CLI_PY_PATH, repo / "cli.py")
            subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init"], cwd=repo, capture_output=True
            )

            arch_line = "architect: true\n" if mode == "architect" else ""
            conf = repo / ".aider.conf.yml"
            conf.write_text(
                f"model: {MAIN_MODEL}\n"
                f"weak-model: {WEAK_MODEL}\n"
                f"{arch_line}"
                f"max-chat-history-tokens: {ARCHITECT_THRESHOLD}\n"
                "auto-commits: false\n"
                "auto-lint: false\n"
                "map-tokens: 0\n"
                "yes-always: true\n"
                "no-show-model-warnings: true\n"
                "check-update: false\n"
                "analytics: false\n"
                "verbose: true\n"
            )

            env = {
                **os.environ,
                "LM_STUDIO_API_BASE": LM_STUDIO_API_BASE,
                "LM_STUDIO_API_KEY": LM_STUDIO_API_KEY,
            }

            cmd = [
                AIDER_BIN,
                "--yes-always",
                "--verbose",
                "--no-check-update",
                "--no-analytics",
                "--map-tokens", "0",
                "--no-auto-commits",
            ]
            if mode == "architect":
                cmd.append("--architect")

            start = time.time()
            proc = subprocess.Popen(
                cmd,
                cwd=str(repo),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )

            prompts = [
                "Read cli.py. Explain _ensure_git_repo, _is_test_path, "
                "_read_user_aiderignore, _scan_repo_files in extreme detail.\n",
                "Explain _build_repomap_ignore_content and _generate_repo_maps "
                "in exhaustive detail.\n",
                "/clear\n",
                "exit\n",
            ]

            def _feed(p=proc, prompts=prompts):
                for i, msg in enumerate(prompts):
                    try:
                        p.stdin.write(msg)
                        p.stdin.flush()
                    except (BrokenPipeError, OSError):
                        return
                    time.sleep(35 if i < 2 else 10)
                time.sleep(8)
                try:
                    p.stdin.close()
                except OSError:
                    pass

            out_chunks: list[str] = []
            err_chunks: list[str] = []

            def _read(s, sink):
                for line in iter(s.readline, ""):
                    sink.append(line)
                try:
                    s.close()
                except OSError:
                    pass

            f = threading.Thread(target=_feed, daemon=True)
            to = threading.Thread(
                target=_read, args=(proc.stdout, out_chunks), daemon=True
            )
            te = threading.Thread(
                target=_read, args=(proc.stderr, err_chunks), daemon=True
            )
            to.start()
            te.start()
            f.start()
            f.join(timeout=200)
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            to.join(timeout=10)
            te.join(timeout=10)

            elapsed = time.time() - start
            hist = repo / ".aider.chat.history.md"
            hist_size = hist.stat().st_size if hist.is_file() else 0
            out_text = "".join(out_chunks) + "".join(err_chunks)
            has_summ = bool(re.search(r"(?i)summariz", out_text))

            results[mode] = {
                "elapsed": elapsed,
                "hist_size": hist_size,
                "rc": proc.returncode,
                "summ_in_log": has_summ,
            }

        # ── Comparison table ──
        print(f"\n{'═' * 70}")
        print(f"  ARCHITECT vs CODER COMPARISON")
        print(f"{'═' * 70}")
        print(
            f"  {'Mode':<12} {'Elapsed':<10} {'Hist Size':<12} "
            f"{'RC':<4} {'Summ in log'}"
        )
        print(f"  {'─' * 12} {'─' * 10} {'─' * 12} {'─' * 4} {'─' * 10}")
        for mode, r in results.items():
            print(
                f"  {mode:<12} {r['elapsed']:<10.1f}s "
                f"{r['hist_size']:<12} {r['rc']:<4} {r['summ_in_log']}"
            )
        print(f"{'═' * 70}")
        print(
            f"  If elapsed differs significantly → different code path.\n"
            f"  If hist_size differs → summarization behaved differently.\n"
            f"  Check llama.cpp logs for BOTH test windows.\n",
            flush=True,
        )

        assert results["coder"]["rc"] == 0
        assert results["architect"]["rc"] == 0
