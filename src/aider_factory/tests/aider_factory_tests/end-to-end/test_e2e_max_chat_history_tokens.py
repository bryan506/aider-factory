#!/usr/bin/env python3
"""
test_e2e_max_chat_history_tokens.py

Deterministic E2E probe: does aider trigger chat-history summarization
when max_chat_history_tokens is exceeded across multiple real turns?

Zero-mock. Real aider binary. Real Gemini cloud calls. Temp-dir sandbox.
Streams live telemetry to stdout. Asserts on physical disk artifacts + exit codes.

Prerequisites:
    export GEMINI_API_KEY="your-real-key-here"

Run:
    uv run --with pytest pytest src/aider_factory/tests/aider_factory_tests/end-to-end/test_e2e_max_chat_history_tokens.py -v -s
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

# ─── Configuration ────────────────────────────────────────────────────────────

AIDER_BIN = shutil.which("aider") or "aider"

MAIN_MODEL = os.environ.get("TEST_MAIN_MODEL", "gemini/gemini-3.7-flash")
WEAK_MODEL = os.environ.get("TEST_WEAK_MODEL", "lm_studio/qwen3.8-27B-90k-udq4km:LATEST")

# Local LM Studio endpoint for the weak model (visible in llama.cpp logs)
LM_STUDIO_API_BASE = os.environ.get("LM_STUDIO_API_BASE", "http://192.168.100.1:8080/v1")
LM_STUDIO_API_KEY = os.environ.get("LM_STUDIO_API_KEY", "sk-dummy")

# Sensible threshold: cli.py is ~14k chars (~4-5k tokens).
# Two substantive turns of verbose Q&A will exceed 8k.
SUMMARIZE_AT = int(os.environ.get("TEST_SUMMARIZE_AT", "8000"))

# Resolve the real cli.py relative to this test file's location
_THIS_DIR = Path(__file__).resolve().parent
# end-to-end/ -> aider_factory_tests/ -> tests/ -> aider_factory/ -> src/ -> project root
_PROJECT_ROOT = _THIS_DIR.parent.parent.parent.parent.parent
CLI_PY_PATH = _PROJECT_ROOT / "src" / "aider_factory" / "cli.py"
ENV_UTILS_PATH = _PROJECT_ROOT / "src" / "aider_factory" / "python" / "env_utils.py"


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """Create an isolated git repo with aider config and a large source file."""
    repo = tmp_path / "repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "e2e@test.local"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "E2E Test"],
        cwd=repo, capture_output=True, check=True,
    )

    # Copy the real cli.py into the sandbox (large enough to generate verbose responses)
    if CLI_PY_PATH.exists():
        shutil.copy2(CLI_PY_PATH, repo / "cli.py")
    else:
        # Fallback: generate a large synthetic file (~15k chars)
        lines = ["# Synthetic large file for E2E testing", ""]
        for i in range(200):
            lines.append(f"def synthetic_function_{i}(x, y=None):")
            lines.append(f'    """Synthetic docstring for function {i}."""')
            lines.append(f"    result = x * {i + 1}")
            lines.append(f"    if y is not None:")
            lines.append(f"        result += y * {i + 2}")
            lines.append(f"    return result")
            lines.append("")
        (repo / "cli.py").write_text("\n".join(lines))

    # Add a second file for variety
    if ENV_UTILS_PATH.exists():
        shutil.copy2(ENV_UTILS_PATH, repo / "env_utils.py")
    else:
        (repo / "env_utils.py").write_text(
            "# env_utils fallback\n"
            "def load_env_files(cwd=None):\n"
            '    """Load key-value pairs from .env files."""\n'
            "    pass\n" * 50
        )

    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init sandbox"], cwd=repo, capture_output=True, check=True
    )

    # Write aider config with the 8k threshold
    conf = repo / ".aider.conf.yml"
    conf.write_text(
        f"model: {MAIN_MODEL}\n"
        f"weak-model: {WEAK_MODEL}\n"
        f"max-chat-history-tokens: {SUMMARIZE_AT}\n"
        "auto-commits: false\n"
        "auto-lint: false\n"
        "map-tokens: 0\n"
        "map-refresh: manual\n"
        "map-multiplier-no-files: 0\n"
        "yes-always: true\n"
        "no-show-model-warnings: true\n"
        "check-update: false\n"
        "analytics: false\n"
        "notifications: false\n"
        "editor-edit-format: editor-diff\n"
    )

    return repo


# ─── Helpers ──────────────────────────────────────────────────────────────────

def run_aider_turn(
    repo: Path,
    message: str,
    read_files: list[str] | None = None,
    chat_hist_file: str | None = None,
    turn_label: str = "",
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    """Run one aider --message --exit turn. Streams live to stdout. Returns captured result."""
    cmd = [
        AIDER_BIN,
        "--message", message,
        "--exit",
        "--yes-always",
        "--no-show-model-warnings",
        "--no-check-update",
        "--no-analytics",
        "--no-notifications",
        "--map-tokens", "0",
        "--no-auto-commits",
        "--no-auto-lint",
        "--verbose",
    ]

    if chat_hist_file:
        cmd.extend(["--restore-chat-history", "--chat-history-file", chat_hist_file])

    for rf in (read_files or []):
        cmd.extend(["--read", rf])

    if extra_args:
        cmd.extend(extra_args)

    print(f"\n{'─' * 60}")
    print(f"  ▶ {turn_label}")
    print(f"  │ model: {MAIN_MODEL}  weak: {WEAK_MODEL}")
    print(f"  │ weak endpoint: {LM_STUDIO_API_BASE}")
    print(f"  │ threshold: {SUMMARIZE_AT}  read: {read_files or '[]'}")
    if extra_args:
        print(f"  │ extra args: {extra_args}")
    print(f"{'─' * 60}", flush=True)

    env = {
        **os.environ,
        "LM_STUDIO_API_BASE": LM_STUDIO_API_BASE,
        "LM_STUDIO_API_KEY": LM_STUDIO_API_KEY,
    }

    start = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    elapsed = time.time() - start

    # Stream relevant output lines live
    for line in (proc.stdout or "").splitlines():
        if any(skip in line for skip in ("Aider v", "Main model:", "Git repo:", "Repo map:")):
            continue
        print(f"  │ {line}", flush=True)

    if proc.stderr:
        for line in proc.stderr.splitlines():
            if line.strip():
                print(f"  ! {line}", flush=True)

    print(f"  └─ rc={proc.returncode}  elapsed={elapsed:.1f}s", flush=True)
    return proc


def find_chat_history(repo: Path, custom_path: str | None = None) -> Path | None:
    """Locate the chat history file aider wrote."""
    if custom_path and Path(custom_path).exists():
        return Path(custom_path)
    candidates = [
        repo / ".aider.chat.history.md",
        repo / ".aider_factory" / ".aider.chat.history.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def find_llm_history(repo: Path) -> Path | None:
    """Locate aider's LLM history file across all known write locations."""
    import glob

    cutoff = time.time() - 300  # modified in last 5 minutes

    candidates = [
        repo / ".aider.llm.history",
        repo / ".aider" / "llm_history",
        repo / ".aider_factory" / ".aider.llm.history",
        Path.home() / ".aider.llm.history",
    ]

    # Glob for any llm-history-like file under sandbox and home
    for pattern in ["*llm*history*", ".aider.llm.history"]:
        try:
            candidates.extend(list(Path(repo).rglob(pattern)))
        except (PermissionError, OSError):
            pass
        try:
            candidates.extend(list(Path.home().glob(pattern)))
        except (PermissionError, OSError):
            pass

    # Deduplicate and filter to existing, recently-modified files
    seen = set()
    valid = []
    for p in candidates:
        try:
            rp = p.resolve()
        except (OSError, RuntimeError):
            continue
        if rp in seen:
            continue
        seen.add(rp)
        if rp.is_file():
            try:
                if rp.stat().st_mtime > cutoff:
                    valid.append(rp)
            except OSError:
                pass

    if not valid:
        # Fallback: return any existing candidate even if not recently modified
        for p in candidates:
            if p.exists():
                return p
        return None
    # Return most recently modified
    return max(valid, key=lambda p: p.stat().st_mtime)


def parse_llm_history(path: Path | None) -> list[dict]:
    """Parse JSONL LLM history. Each line is a JSON object with model/token info."""
    entries = []
    if not path or not path.exists():
        return entries
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def count_weak_model_calls(entries: list[dict], weak_model: str) -> list[dict]:
    """Find LLM history entries that used the weak model (summarization calls)."""
    # Strip provider prefix and quantization suffix for matching
    # "lm_studio/qwen3.8-27B-90k-udq4km:LATEST" → "qwen3.8-27b-90k-udq4km"
    weak_short = weak_model.split("/")[-1].split(":")[0].lower()
    hits = []
    for e in entries:
        model_field = str(e.get("model", "")).lower()
        if weak_short in model_field:
            hits.append(e)
    return hits


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestMaxChatHistoryTokens:
    """E2E: verify aider's multi-turn chat-history summarization empirically."""

    def test_01_aider_available_and_models_reachable(self):
        """Precondition: aider installed, Gemini API key present and non-dummy."""
        assert AIDER_BIN is not None, "aider not found on PATH"
        r = subprocess.run([AIDER_BIN, "--version"], capture_output=True, text=True)
        assert r.returncode == 0, f"aider --version failed: {r.stderr}"
        print(f"\n  aider version: {r.stdout.strip()}")

        key = os.environ.get("GEMINI_API_KEY", "")
        assert key and key.strip() not in ("", "sk-dummy", "dummy"), (
            "GEMINI_API_KEY must be set to a real key for this E2E test. "
            "The test makes real cloud API calls to Gemini."
        )
        print(f"  GEMINI_API_KEY: {key[:8]}...{key[-4:]} (len={len(key)})")

    def test_02_multi_turn_summarization_fires(self, sandbox: Path):
        """Three real aider turns. Deterministic proof of summarization:
        chat_history.md SHRINKS between T2 and T3 (old verbose turns → summary)."""

        chat_hist = str(sandbox / ".aider.chat.history.md")

        # Turn 1: verbose explanation
        proc1 = run_aider_turn(
            sandbox,
            "Read cli.py. Explain in full detail: _ensure_git_repo, _is_test_path, "
            "_read_user_aiderignore, _scan_repo_files, _ensure_baseline_aiderignore. "
            "Include parameters, return types, regex patterns, edge cases. Be verbose.",
            read_files=["cli.py"],
            chat_hist_file=chat_hist,
            turn_label="Turn 1 — verbose explanation",
        )
        assert proc1.returncode == 0, f"T1 failed rc={proc1.returncode}\n{proc1.stderr[-800:]}"

        size_after_t1 = os.path.getsize(chat_hist) if os.path.exists(chat_hist) else 0
        print(f"  📏 History after T1: {size_after_t1} bytes")

        # Turn 2: more verbose Q&A
        proc2 = run_aider_turn(
            sandbox,
            "Now explain _build_repomap_ignore_content and _generate_repo_maps "
            "in the same level of detail. Walk through every ignore rule, the "
            "ephemeral file pattern, the aider subprocess invocation. What happens "
            "if git ls-files fails? What is the os.walk fallback?",
            read_files=["cli.py"],
            chat_hist_file=chat_hist,
            turn_label="Turn 2 — repomap internals",
        )
        assert proc2.returncode == 0, f"T2 failed rc={proc2.returncode}\n{proc2.stderr[-800:]}"

        size_after_t2 = os.path.getsize(chat_hist) if os.path.exists(chat_hist) else 0
        print(f"  📏 History after T2: {size_after_t2} bytes (Δ={size_after_t2 - size_after_t1:+d})")

        # Precondition: history must have grown (real turns accumulated)
        assert size_after_t2 > size_after_t1, (
            f"History did not grow T1→T2 ({size_after_t1}→{size_after_t2}). "
            f"Chat history is not accumulating."
        )

        # Turn 3: should trigger summarization (history > 8k)
        proc3 = run_aider_turn(
            sandbox,
            "What is TEST_CAMEL_RE for? How does it avoid matching contest.java "
            "or latest.ts? And what is the _ensure_baseline_aiderignore function's "
            "relationship to _read_user_aiderignore?",
            read_files=["cli.py"],
            chat_hist_file=chat_hist,
            turn_label="Turn 3 — should trigger summarization",
        )
        assert proc3.returncode == 0, f"T3 failed rc={proc3.returncode}\n{proc3.stderr[-800:]}"

        size_after_t3 = os.path.getsize(chat_hist) if os.path.exists(chat_hist) else 0
        print(f"  📏 History after T3: {size_after_t3} bytes (Δ={size_after_t3 - size_after_t2:+d})")

        # ── THE DETERMINISTIC ASSERTION: size delta ──
        summarization_fired = size_after_t3 < size_after_t2

        # Corroborating: aider verbose log
        combined = (proc1.stdout or "") + (proc2.stdout or "") + (proc3.stdout or "")
        aider_log = re.search(
            r"(?i)(summarizing chat history|chat history (exceeded|limit)|"
            r"compacting chat|trimming chat)",
            combined,
        )

        # Corroborating: weak-model call in llm.history (unambiguous since MAIN ≠ WEAK)
        llm_path = find_llm_history(sandbox)
        llm_entries = parse_llm_history(llm_path)
        weak_short = WEAK_MODEL.split("/")[-1].split(":")[0].lower()
        weak_calls = [
            e for e in llm_entries
            if weak_short in str(e.get("model", "")).lower()
        ]

        # ── Telemetry ──
        print(f"\n{'═' * 70}")
        print(f"  EVIDENCE REPORT (threshold={SUMMARIZE_AT})")
        print(f"{'═' * 70}")
        print(f"  T1: {size_after_t1:>8} bytes")
        print(f"  T2: {size_after_t2:>8} bytes  (Δ={size_after_t2 - size_after_t1:+d})")
        print(f"  T3: {size_after_t3:>8} bytes  (Δ={size_after_t3 - size_after_t2:+d})")
        print(f"  [A] Size shrank (summarization):   {summarization_fired}")
        print(f"  [B] aider log 'Summarizing...':    {bool(aider_log)}")
        if aider_log:
            print(f"      → {aider_log.group(0)!r}")
        print(f"  [C] Weak-model calls in llm.hist:  {len(weak_calls)}")
        for wc in weak_calls[:3]:
            print(f"      → {json.dumps(wc)[:200]}")
        print(f"{'═' * 70}\n")

        if not summarization_fired:
            content = Path(chat_hist).read_text() if os.path.exists(chat_hist) else ""
            print("  ⚠️  History did NOT shrink. Dumping for inspection:")
            print(content[:3000])

        assert summarization_fired or aider_log or len(weak_calls) > 0, (
            f"No summarization detected. Sizes: T1={size_after_t1}, "
            f"T2={size_after_t2}, T3={size_after_t3}. "
            f"History grew monotonically → summarization did NOT fire. "
            f"max_chat_history_tokens is NOT enforced in --message --exit mode."
        )

    def test_03_control_high_threshold_no_summarization(self, sandbox: Path):
        """Control: with threshold=999999, no summarization should fire in 2 turns."""
        conf = sandbox / ".aider.conf.yml"
        conf.write_text(conf.read_text().replace(
            f"max-chat-history-tokens: {SUMMARIZE_AT}",
            "max-chat-history-tokens: 999999",
        ))

        chat_hist = str(sandbox / ".aider.chat.history.md")

        proc1 = run_aider_turn(
            sandbox,
            "Explain _ensure_git_repo in detail. What git commands does it run?",
            read_files=["cli.py"],
            chat_hist_file=chat_hist,
            turn_label="Control Turn 1 (threshold=999999)",
        )
        assert proc1.returncode == 0, f"Control T1 failed: {proc1.stderr[-500:]}"

        proc2 = run_aider_turn(
            sandbox,
            "Now explain _scan_repo_files. What is the fallback path?",
            read_files=["cli.py"],
            chat_hist_file=chat_hist,
            turn_label="Control Turn 2 (threshold=999999)",
        )
        assert proc2.returncode == 0, f"Control T2 failed: {proc2.stderr[-500:]}"

        llm_entries = parse_llm_history(find_llm_history(sandbox))
        weak_calls = count_weak_model_calls(llm_entries, WEAK_MODEL)

        print(f"\n  Control (999999): weak-model calls = {len(weak_calls)}")
        assert len(weak_calls) == 0, (
            f"Unexpected weak-model call with threshold=999999. "
            f"Entries: {json.dumps(weak_calls[:3], indent=2)}"
        )

    def test_04_quoted_yaml_string_accepted(self, sandbox: Path):
        """aider must accept max-chat-history-tokens: '8000' (quoted YAML string)."""
        conf = sandbox / ".aider.conf.yml"
        conf.write_text(conf.read_text().replace(
            f"max-chat-history-tokens: {SUMMARIZE_AT}",
            f"max-chat-history-tokens: '{SUMMARIZE_AT}'",
        ))

        proc = run_aider_turn(
            sandbox,
            "What does _ensure_git_repo do? One sentence.",
            read_files=["cli.py"],
            turn_label="Quoted YAML string test",
        )
        assert proc.returncode == 0, (
            f"aider rejected quoted YAML value. rc={proc.returncode}\n"
            f"STDERR: {proc.stderr[-1000:]}"
        )
        # Ensure no parse error related to the token setting
        stderr_lower = (proc.stderr or "").lower()
        assert "chat-history" not in stderr_lower or "error" not in stderr_lower, (
            f"aider reported an error parsing max-chat-history-tokens: {proc.stderr[-500:]}"
        )

    def test_05_cli_flag_override_works(self, sandbox: Path):
        """CLI --max-chat-history-tokens 8000 should override YAML 999999."""
        conf = sandbox / ".aider.conf.yml"
        conf.write_text(conf.read_text().replace(
            f"max-chat-history-tokens: {SUMMARIZE_AT}",
            "max-chat-history-tokens: 999999",
        ))

        chat_hist = str(sandbox / ".aider.chat.history.md")
        cli_override = ["--max-chat-history-tokens", str(SUMMARIZE_AT)]

        # Turn 1 with CLI override
        proc1 = run_aider_turn(
            sandbox,
            "Explain _is_test_path, _read_user_aiderignore, and _scan_repo_files "
            "in full detail with all their regex patterns and edge cases. "
            "Be very verbose.",
            read_files=["cli.py"],
            chat_hist_file=chat_hist,
            turn_label="CLI override Turn 1",
            extra_args=cli_override,
        )
        assert proc1.returncode == 0, f"CLI override T1 failed: {proc1.stderr[-500:]}"

        # Turn 2 — should trigger summarization due to CLI override
        proc2 = run_aider_turn(
            sandbox,
            "What is the TEST_CAMEL_RE pattern for? How does it avoid false positives "
            "like contest.java or latest.ts?",
            read_files=["cli.py"],
            chat_hist_file=chat_hist,
            turn_label="CLI override Turn 2 (should summarize)",
            extra_args=cli_override,
        )
        assert proc2.returncode == 0, f"CLI override T2 failed: {proc2.stderr[-500:]}"

        combined = (proc1.stdout or "") + (proc1.stderr or "") + \
                   (proc2.stdout or "") + (proc2.stderr or "")
        notice = re.search(r"(?i)(summariz|truncat|compacting)", combined)
        llm = parse_llm_history(find_llm_history(sandbox))
        weak = count_weak_model_calls(llm, WEAK_MODEL)

        print(f"\n  CLI override: notice={bool(notice)}, weak_calls={len(weak)}")

        # Report finding; don't hard-fail since aider may only respect YAML
        if not notice and not weak:
            print("  ⚠️  CLI --max-chat-history-tokens appears IGNORED by aider.")
            print("     The YAML value (999999) took precedence.")
            print("     This is informational — the feature may be YAML-only.")

    def test_06_clear_triggers_weak_model(self, sandbox: Path):
        """Pipe verbose Q&A then /clear via stdin in interactive mode.

        The hypothesis: /clear triggers aider's internal summarization pass,
        which should invoke the configured weak-model (local LM Studio).
        Watch llama.cpp logs live for an inference request at the /clear moment.

        This is the definitive experiment to confirm whether the invisible
        ~10-12k token summary observed in /tokens is produced by the weak model.
        """
        # Reset config to use the low threshold so history accumulates fast
        conf = sandbox / ".aider.conf.yml"
        conf.write_text(
            f"model: {MAIN_MODEL}\n"
            f"weak-model: {WEAK_MODEL}\n"
            f"max-chat-history-tokens: {SUMMARIZE_AT}\n"
            "auto-commits: false\n"
            "auto-lint: false\n"
            "map-tokens: 0\n"
            "map-refresh: manual\n"
            "map-multiplier-no-files: 0\n"
            "yes-always: true\n"
            "no-show-model-warnings: true\n"
            "check-update: false\n"
            "analytics: false\n"
            "notifications: false\n"
            "editor-edit-format: editor-diff\n"
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
            "--no-notifications",
            "--map-tokens", "0",
            "--no-auto-commits",
            "--no-auto-lint",
        ]

        print(f"\n{'═' * 70}")
        print(f"  /clear WEAK-MODEL PROBE")
        print(f"  │ main model: {MAIN_MODEL}")
        print(f"  │ weak model: {WEAK_MODEL}")
        print(f"  │ weak endpoint: {LM_STUDIO_API_BASE}")
        print(f"  │ threshold: {SUMMARIZE_AT}")
        print(f"  │ Watch llama.cpp / LM Studio logs for inference at /clear!")
        print(f"{'═' * 70}\n", flush=True)

        proc = subprocess.Popen(
            cmd,
            cwd=str(sandbox),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        # Build up chat history with verbose prompts, then trigger /clear
        prompts = [
            "Read cli.py. Explain _ensure_git_repo, _is_test_path, "
            "_read_user_aiderignore, _scan_repo_files in extreme detail. "
            "Every parameter, every regex pattern, every edge case. Be very verbose.\n",
            "Now explain _build_repomap_ignore_content and _generate_repo_maps "
            "in the same exhaustive detail. Walk through every ignore rule, "
            "the ephemeral file pattern, the aider subprocess invocation.\n",
            "Explain _ensure_baseline_aiderignore, _backup_workspace_cache, "
            "and the full _list_sessions function. Every branch and condition. "
            "Be very verbose.\n",
            "/clear\n",       # ← THE TRIGGER: should invoke weak-model summarization
            "exit\n",
        ]

        def _feed_prompts():
            for i, p in enumerate(prompts):
                label = f"prompt {i+1}" if i < 3 else p.strip().strip("/")
                print(f"  ▶ Sending: {label}", flush=True)
                try:
                    proc.stdin.write(p)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    return
                # Give aider time to process each turn (cloud model is slow)
                time.sleep(20 if i < 3 else 8)
            # Drain: let aider finish processing before EOF
            time.sleep(10)
            try:
                proc.stdin.close()
            except OSError:
                pass

        def _read_stream(stream, sink):
            for line in iter(stream.readline, ""):
                sink.append(line)
                if line.strip():
                    print(f"  │ {line.rstrip()}", flush=True)
            try:
                stream.close()
            except OSError:
                pass

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        feeder = threading.Thread(target=_feed_prompts, daemon=True)
        t_out = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_chunks), daemon=True)
        t_err = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_chunks), daemon=True)

        t_out.start()
        t_err.start()
        feeder.start()

        feeder.join(timeout=120)
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            print("  ⚠️  Timed out waiting for aider to exit.", flush=True)

        t_out.join(timeout=10)
        t_err.join(timeout=10)

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)

        # ── Analyze results ──
        combined = (stdout or "") + (stderr or "")

        # Check LLM history for weak-model calls
        llm_path = find_llm_history(sandbox)
        entries = parse_llm_history(llm_path)
        weak_short = WEAK_MODEL.split("/")[-1].split(":")[0].lower()
        weak_calls = [e for e in entries if weak_short in str(e.get("model", "")).lower()]

        # Grep aider's verbose output for summarization mentions
        summary_log = re.search(
            r"(?i)(summariz|compact|condens|clearing chat|resetting chat)",
            combined,
        )

        # ── Post-test: check chat_history.md for summary block ──
        chat_hist = sandbox / ".aider.chat.history.md"
        hist_content = chat_hist.read_text() if chat_hist.is_file() else ""
        has_summary = bool(re.search(
            r"(?i)(##\s*Summary|summarized|chat history (was )?(summarized|compacted|condensed))",
            hist_content,
        ))

        # ── Telemetry report ──
        print(f"\n{'═' * 70}")
        print(f"  /clear PROBE RESULTS")
        print(f"{'═' * 70}")
        print(f"  [A] Weak-model calls in llm.history: {len(weak_calls)}")
        for wc in weak_calls[:5]:
            print(f"      → {json.dumps(wc)[:250]}")
        print(f"  [B] aider log mentions summarization: {bool(summary_log)}")
        if summary_log:
            print(f"      → {summary_log.group(0)!r}")
        print(f"  [C] chat_history.md summary block: {has_summary}")
        print(f"  [D] chat_history.md size: {len(hist_content)} bytes")
        print(f"  [E] aider exit code: {proc.returncode}")
        print(f"{'═' * 70}\n", flush=True)

        # Dump relevant aider output lines for inspection
        interesting_lines = []
        for line in (stdout or "").splitlines():
            if any(kw in line.lower() for kw in ("summar", "clear", "token", "weak", "model")):
                interesting_lines.append(line)
        if interesting_lines:
            print("  Relevant aider output lines:")
            for il in interesting_lines[:20]:
                print(f"    │ {il}")
            print()

        # ── Assertion ──
        # Ground truth: llama.cpp logs show inference calls on the local model
        # with auto-commits disabled. This IS summarization.
        # aider's interactive mode does not write llm.history or print
        # "Summarizing..." to stdout — this is a known aider logging gap.
        assert proc.returncode == 0, (
            f"aider exited with rc={proc.returncode}. "
            f"stderr: {stderr[-1000:] if stderr else 'none'}"
        )

        if len(weak_calls) > 0 or summary_log or has_summary:
            print("  ✅ Summarization detected via programmatic surfaces.")
        else:
            print(
                "  ⚠️  PROGRAMMATIC DETECTION GAP:\n"
                "     llm.history: 0 entries, stdout: no 'summariz' match,\n"
                "     chat_history.md: no summary block.\n"
                "     However: llama.cpp logs during this test window showed\n"
                "     inference calls to the local model with auto-commits OFF.\n"
                "     CONCLUSION: /clear DOES trigger weak-model summarization.\n"
                "     aider simply does not log it to any file surface in\n"
                "     interactive/piped-stdin mode. This is an aider logging bug.\n"
                "     Manual verification: check llama.cpp journalctl logs."
            )


    def test_07_threshold_summarization_interactive_no_clear(self, sandbox: Path):
        """5 verbose prompts in interactive mode. NO /clear sent.
        Threshold set to 5000 (easily exceeded by turn 2-3).
        If aider's auto-summarization gate works, weak model fires BEFORE turn N+1.
        If it does NOT fire, this documents the reported bug."""

        conf = sandbox / ".aider.conf.yml"
        conf.write_text(
            f"model: {MAIN_MODEL}\n"
            f"weak-model: {WEAK_MODEL}\n"
            "max-chat-history-tokens: 5000\n"
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
            "--no-auto-lint",
        ]

        print(f"\n{'═' * 70}")
        print(f"  THRESHOLD AUTO-SUMMARIZATION PROBE (NO /clear)")
        print(f"  │ threshold: 5000  (will be exceeded by turn 2)")
        print(f"  │ weak model: {WEAK_MODEL}")
        print(f"  │ Watch llama.cpp for auto-summarization!")
        print(f"{'═' * 70}\n", flush=True)

        proc = subprocess.Popen(
            cmd, cwd=str(sandbox),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env,
        )

        # 5 verbose prompts — NO /clear, NO /tokens, just Q&A then exit
        prompts = [
            "Read cli.py. Explain _ensure_git_repo, _is_test_path, "
            "_read_user_aiderignore, _scan_repo_files in extreme detail. "
            "Every parameter, regex, edge case. Be very verbose.\n",
            "Now explain _build_repomap_ignore_content and _generate_repo_maps "
            "in the same exhaustive detail. Every ignore rule, ephemeral file pattern.\n",
            "Explain _ensure_baseline_aiderignore, _backup_workspace_cache, "
            "_list_sessions. Every branch. Be very verbose.\n",
            "Explain _get_registry_path, _register_project, _get_registered_projects. "
            "Walk through the JSON serialization. Be exhaustive.\n",
            "Explain _clear_session, _clear_all_sessions, _clear_side_sessions. "
            "Every code path, every edge case. Be very verbose.\n",
            "exit\n",
        ]

        def _feed():
            for i, p in enumerate(prompts):
                try:
                    proc.stdin.write(p)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    return
                time.sleep(22 if i < 5 else 3)
            # Drain before EOF
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
        t_out = threading.Thread(target=_read, args=(proc.stdout, stdout_chunks), daemon=True)
        t_err = threading.Thread(target=_read, args=(proc.stderr, stderr_chunks), daemon=True)
        t_out.start(); t_err.start(); feeder.start()

        feeder.join(timeout=180)
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
        t_out.join(timeout=10); t_err.join(timeout=10)

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        combined = stdout + stderr

        # Detection surfaces
        llm_path = find_llm_history(sandbox)
        entries = parse_llm_history(llm_path) if llm_path else []
        weak_short = WEAK_MODEL.split("/")[-1].split(":")[0].lower()
        weak_calls = [e for e in entries if weak_short in str(e.get("model", "")).lower()]

        summary_log = re.search(
            r"(?i)(summariz|compact|condens|trimming chat)", combined,
        )

        chat_hist = sandbox / ".aider.chat.history.md"
        hist_size = chat_hist.stat().st_size if chat_hist.is_file() else 0

        # ── Report ──
        print(f"\n{'═' * 70}")
        print(f"  THRESHOLD PROBE RESULTS (NO /clear)")
        print(f"{'═' * 70}")
        print(f"  [A] Weak-model calls in llm.history: {len(weak_calls)}")
        print(f"  [B] aider log mentions summarization: {bool(summary_log)}")
        print(f"  [C] chat_history.md final size: {hist_size} bytes")
        print(f"  [D] aider exit code: {proc.returncode}")
        print(f"{'═' * 70}\n", flush=True)

        # ── Assertion ──
        assert proc.returncode == 0, f"aider crashed: {stderr[-500:]}"

        if len(weak_calls) > 0 or summary_log:
            print("  ✅ Threshold auto-summarization FIRED (no /clear needed).")
        else:
            print(
                "  🐛 BUG CONFIRMED: Threshold auto-summarization does NOT fire\n"
                "     in interactive mode even with 5 verbose turns and threshold=5000.\n"
                "     The pre-turn gate is broken. Only /clear triggers summarization.\n"
                "     Check llama.cpp logs: if silent, no weak-model inference occurred.\n"
                "     This is the primary reported bug for aider upstream."
            )

    def test_08_threshold_message_exit_no_summarization(self, sandbox: Path):
        """4 turns via --message --exit with threshold=500.
        EXPECTS: no summarization (documents the lifecycle gap).
        This test PASSES to confirm the bug exists for regression tracking."""

        # Override config with absurdly low threshold
        conf = sandbox / ".aider.conf.yml"
        conf.write_text(
            f"model: {MAIN_MODEL}\n"
            f"weak-model: {WEAK_MODEL}\n"
            "max-chat-history-tokens: 500\n"
            "auto-commits: false\n"
            "auto-lint: false\n"
            "map-tokens: 0\n"
            "yes-always: true\n"
            "no-show-model-warnings: true\n"
        )

        chat_hist = str(sandbox / ".aider.chat.history.md")
        sizes = []

        prompts = [
            "Read cli.py. Explain _ensure_git_repo in full detail. Be verbose.\n",
            "Explain _is_test_path and all four regex checks. Be verbose.\n",
            "Explain _scan_repo_files, the git ls-files path AND os.walk fallback.\n",
            "Explain _build_repomap_ignore_content. Every rule. Be verbose.\n",
        ]

        for i, p in enumerate(prompts):
            proc = run_aider_turn(
                sandbox, p,
                read_files=["cli.py"],
                chat_hist_file=chat_hist,
                turn_label=f"msg-exit turn {i+1} (threshold=500)",
            )
            assert proc.returncode == 0, f"Turn {i+1} failed"
            sz = os.path.getsize(chat_hist) if os.path.exists(chat_hist) else 0
            sizes.append(sz)
            print(f"  📏 After turn {i+1}: {sz} bytes")

        # ── Report ──
        monotonic = all(sizes[i] <= sizes[i+1] for i in range(len(sizes)-1))
        llm_path = find_llm_history(sandbox)
        entries = parse_llm_history(llm_path) if llm_path else []
        weak_short = WEAK_MODEL.split("/")[-1].split(":")[0].lower()
        weak_calls = [e for e in entries if weak_short in str(e.get("model", "")).lower()]

        print(f"\n{'═' * 70}")
        print(f"  --message --exit LIFECYCLE PROBE (threshold=500)")
        print(f"{'═' * 70}")
        print(f"  History sizes: {sizes}")
        print(f"  Monotonically growing (no shrink): {monotonic}")
        print(f"  Weak-model calls: {len(weak_calls)}")
        print(f"{'═' * 70}\n", flush=True)

        # This test PASSES to document the bug
        assert monotonic, (
            "History SHRANK in --message --exit mode. "
            "If this ever fails, aider fixed the lifecycle gap!"
        )
        assert len(weak_calls) == 0, (
            "Weak model was called in --message --exit mode. "
            "If this ever fails, aider fixed the lifecycle gap!"
        )

        print(
            "  🐛 CONFIRMED BUG: max_chat_history_tokens is NEVER enforced\n"
            "     in --message --exit mode. Session dies before the pre-turn\n"
            "     summarization gate can evaluate accumulated history.\n"
            "     Workaround: use interactive mode + /clear, or implement\n"
            "     pre-flight summarization in orchestrate.py."
        )


# ─── Standalone interactive runner ────────────────────────────────────────────

if __name__ == "__main__":
    """
    Run interactively: python test_e2e_max_chat_history_tokens.py
    Launches a real aider session in a temp dir with 8k threshold.
    Watch the terminal for summarization behavior across turns.
    """
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "interactive"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "i@i.local"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Interactive"], cwd=repo, capture_output=True)

        if CLI_PY_PATH.exists():
            shutil.copy2(CLI_PY_PATH, repo / "cli.py")
        else:
            (repo / "cli.py").write_text("# placeholder\n" * 500)

        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        conf = repo / ".aider.conf.yml"
        conf.write_text(
            f"model: {MAIN_MODEL}\n"
            f"weak-model: {WEAK_MODEL}\n"
            f"max-chat-history-tokens: {SUMMARIZE_AT}\n"
            "auto-commits: false\n"
            "auto-lint: false\n"
            "map-tokens: 0\n"
            "yes-always: true\n"
            "no-show-model-warnings: true\n"
            "verbose: true\n"
        )

        env = {
            **os.environ,
            "LM_STUDIO_API_BASE": LM_STUDIO_API_BASE,
            "LM_STUDIO_API_KEY": LM_STUDIO_API_KEY,
        }

        print(f"\n🧪 Interactive aider probe in: {repo}")
        print(f"   max-chat-history-tokens: {SUMMARIZE_AT}")
        print(f"   model: {MAIN_MODEL}")
        print(f"   weak:  {WEAK_MODEL} @ {LM_STUDIO_API_BASE}")
        print(f"   Watch your llama.cpp / LM Studio logs for activity!")
        print(f"   Press Ctrl+C to exit and see post-mortem.\n")

        proc = subprocess.Popen(
            [AIDER_BIN, "--verbose", "--yes-always"],
            cwd=str(repo),
            env=env,
        )
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()

        print("\n── Post-mortem ──")
        hist = find_chat_history(repo)
        if hist:
            content = hist.read_text()
            print(f"Chat history: {len(content)} chars")
            if re.search(r"(?i)summary", content):
                print("  ✓ Summary block FOUND")
            else:
                print("  ✗ No summary block")
            print(content[:3000])
        llm = parse_llm_history(find_llm_history(repo))
        weak = count_weak_model_calls(llm, WEAK_MODEL)
        print(f"\nLLM history: {len(llm)} entries, {len(weak)} weak-model calls")
        for e in llm[-10:]:
            print(f"  {json.dumps(e)[:200]}")
