#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.request
import yaml

from aider_factory.python.apply_agent import run_apply


def _probe_endpoint(url: str, timeout: float = 1.5) -> bool:
    if not url:
        return False
    clean = url.rstrip("/")
    models_url = f"{clean}/models" if not clean.endswith("/v1") else f"{clean}/models"
    try:
        req = urllib.request.Request(
            models_url,
            headers={"User-Agent": "AI-Factory/1.0", "Authorization": "Bearer sk-dummy"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _generate_6k_context() -> str:
    sections = []
    sections.append("# Core Financial Data Pipeline Scaffolding\n")
    for i in range(1, 13):
        sections.append(f"""
class FinancialFeaturePipeline_{i}:
    \"\"\"Module {i}: Computes rolling volatility, leverage ratios, and liquidity sweeps.\"\"\"
    def __init__(self, window_size: int = 252, decay_rate: float = 0.94):
        self.window = window_size
        self.decay = decay_rate
        self.cache = {{}}

    def process_series_{i}(self, prices: list[float], volumes: list[float]) -> dict:
        if not prices:
            return {{"status": "empty", "metric": 0.0}}
        cum_ret = 1.0
        for p in prices:
            cum_ret *= (1.0 + p * 0.001)
        return {{"window": self.window, "volatility": 0.15 * {i}, "cum_ret": cum_ret}}
""")
    return "\n".join(sections)


class TestE2EApplyAgentLiveCluster(unittest.TestCase):
    ARCH_API_BASE = os.environ.get("ARCHITECT_API_BASE", "http://192.168.100.1:8080/v1")
    ARCH_MODEL = "lm_studio/qwen3.6-27B-90k-udq4kxl:LATEST"

    EDITOR_API_BASE = os.environ.get("EDITOR_OLLAMA_API", "http://192.168.100.2:8081/v1")
    EDITOR_MODEL = "openai/qwen3.6-27B-90k-udq4kxl-rag:LATEST"

    @classmethod
    def setUpClass(cls):
        arch_online = _probe_endpoint(cls.ARCH_API_BASE)
        editor_online = _probe_endpoint(cls.EDITOR_API_BASE)

        if not arch_online:
            raise unittest.SkipTest(f"Architect endpoint {cls.ARCH_API_BASE} unreachable.")
        if not editor_online:
            raise unittest.SkipTest(f"Editor endpoint {cls.EDITOR_API_BASE} unreachable.")

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.old_env = dict(os.environ)

        # 1. Initialize real Git repo
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Cluster Test"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@cluster.local"], cwd=self.test_dir, check=True)

        # 2. Create initial target file and commit
        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        self.target_file = os.path.join(self.test_dir, "src", "math_service.py")
        with open(self.target_file, "w", encoding="utf-8") as f:
            f.write("def divide(a, b):\n    return a / b\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        # 3. Create .aider_factory/.env.yml with live dual cluster endpoints
        self.af_dir = os.path.join(self.test_dir, ".aider_factory")
        os.makedirs(self.af_dir, exist_ok=True)
        env_config = {
            "name": "Live Cluster Apply Test",
            "working_directory": self.test_dir,
            "endpoints": {
                "architect_api_base": self.ARCH_API_BASE,
                "editor_ollama_api": self.EDITOR_API_BASE,
            },
            "models": {
                "architect_agent": self.ARCH_MODEL,
                "editor_agent": self.EDITOR_MODEL,
            },
        }
        with open(os.path.join(self.af_dir, ".env.yml"), "w", encoding="utf-8") as f:
            yaml.dump(env_config, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _run_arch_ask(self, prompt: str, chat_hist: str, env: dict, turn_label: str) -> None:
        cmd = [
            "aider",
            "--no-check-model-accepts-settings",
            "--no-show-model-warnings",
            "--model", self.ARCH_MODEL,
            "--edit-format", "ask",
            "--no-auto-commits",
            "--map-tokens", "0",
            "--map-refresh", "manual",
            "--map-multiplier-no-files", "0",
            "--max-chat-history-tokens", "100000",
            "--no-check-update",
            "--no-detect-urls",
            "--no-suggest-shell-commands",
            "--restore-chat-history",
            "--chat-history-file", chat_hist,
            "--message", prompt,
        ]
        t0 = time.time()
        res = subprocess.run(cmd, cwd=self.test_dir, env=env, capture_output=True, text=True, timeout=300)
        elapsed = time.time() - t0
        self.assertEqual(res.returncode, 0, f"Architect {turn_label} failed: {res.stderr}")
        print(f"\n[Timing] {turn_label} completed in {elapsed:.2f}s (rc=0)")

    def test_live_cluster_ask_apply_and_resume_lifecycle(self):
        session_dir = os.path.join(self.af_dir, "sessions", "cluster_session")
        os.makedirs(session_dir, exist_ok=True)
        chat_hist = os.path.join(session_dir, ".aider.chat.history.md")

        env = os.environ.copy()
        env["LM_STUDIO_API_BASE"] = self.ARCH_API_BASE
        env["OPENAI_API_BASE"] = self.EDITOR_API_BASE
        env["LM_STUDIO_API_KEY"] = "sk-dummy"
        env["OPENAI_API_KEY"] = "sk-dummy"
        env["AIDER_ARCHITECT"] = "false"
        env["AI_FACTORY_SESSION"] = "cluster_session"

        # --- Architect Turn 1: 6k base context + Plan ---
        context_6k = _generate_6k_context()
        turn1_prompt = (
            f"{context_6k}\n\n"
            "# Directive:\n"
            "Review src/math_service.py. Create a technical plan to update divide(a, b) so it raises ValueError('Cannot divide by zero') if b == 0."
        )
        self._run_arch_ask(turn1_prompt, chat_hist, env, "Architect Turn 1 (6k Context)")
        self.assertTrue(os.path.isfile(chat_hist))

        # --- Architect Turn 2: Follow-up 1 ---
        turn2_prompt = "Also ensure that negative divisors (e.g. b == -0.0) are handled safely."
        self._run_arch_ask(turn2_prompt, chat_hist, env, "Architect Turn 2 (Refinement)")

        # --- Architect Turn 3: Follow-up 2 (Concrete Directive) ---
        turn3_prompt = (
            "Output the exact SEARCH/REPLACE block to update divide(a, b) in src/math_service.py "
            "so that if b == 0 it raises ValueError('Cannot divide by zero')."
        )
        self._run_arch_ask(turn3_prompt, chat_hist, env, "Architect Turn 3 (Final Spec)")

        # --- Editor Pass (Single-Shot apply on Node 2 via turn extraction) ---
        t_apply0 = time.time()
        success = run_apply(
            ["src/math_service.py"],
            turns=1,
            session_name="cluster_session",
            cwd=self.test_dir,
        )
        apply_elapsed = time.time() - t_apply0
        print(f"\n[Timing] Editor Apply Pass completed in {apply_elapsed:.2f}s (success={success})")
        self.assertTrue(success, "aider-apply execution failed with live cluster editor.")

        # Assert physical file mutation & commit
        with open(self.target_file, "r", encoding="utf-8") as f:
            new_content = f.read()
        self.assertTrue(
            "ValueError" in new_content or "0" in new_content,
            f"File was not properly edited by local editor model:\n{new_content}",
        )

        git_count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=self.test_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(int(git_count.stdout.strip()), 2, "Git commit count mismatch after apply.")

        # --- Architect Turn 4: Post-Apply Test Design ---
        turn4_prompt = "The changes have been applied and committed. Outline a unit test suite for divide(a, b)."
        self._run_arch_ask(turn4_prompt, chat_hist, env, "Architect Turn 4 (Test Design)")

        # --- Architect Turn 5: Floating point edge cases ---
        turn5_prompt = "Detail edge cases regarding floating point precision and infinity representations."
        self._run_arch_ask(turn5_prompt, chat_hist, env, "Architect Turn 5 (Edge Cases)")

        # --- Architect Turn 6: Summary & Sign-off ---
        turn6_prompt = "Summarize the final test verification criteria."
        self._run_arch_ask(turn6_prompt, chat_hist, env, "Architect Turn 6 (Final Sign-off)")


if __name__ == "__main__":
    unittest.main()
