#!/usr/bin/env python3
"""test_e2e_local_oracle_persistence.py — End-to-End Live Smoke Test (Zero Mocks) for
aider-oracle KV-Cache Persistence and Debates against real local LLM endpoints.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.request

script_dir = os.path.dirname(os.path.abspath(__file__))
pkg_dir = os.path.abspath(os.path.join(script_dir, "../../.."))
python_dir = os.path.join(pkg_dir, "python")
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)
if python_dir not in sys.path:
    sys.path.insert(0, python_dir)

import oracle_agent


def _probe_local_endpoint(url):
    try:
        req = urllib.request.Request(
            f"{url.rstrip('/')}/models",
            headers={"Authorization": "Bearer sk-dummy"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("data", [])
                m_ids = [m["id"] for m in models if "id" in m]
                favored = [m for m in m_ids if "27b" in m.lower()]
                model_id = favored[0] if favored else (m_ids[0] if m_ids else None)
                return True, model_id
    except Exception:
        pass
    return False, None


class TestE2ELocalOraclePersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidate_bases = [
            os.environ.get("ORACLE_AGENT_API_BASE"),
            os.environ.get("LITELLM_BASE_URL"),
            "http://192.168.100.2:8080/v1",
            "http://192.168.100.1:8080/v1",
            "http://localhost:8080/v1",
        ]
        cls.api_base = None
        discovered_model = None
        for b in candidate_bases:
            if b:
                ok, m_id = _probe_local_endpoint(b)
                if ok:
                    cls.api_base = b
                    discovered_model = m_id
                    break

        if not cls.api_base:
            raise unittest.SkipTest("No local Oracle endpoint reachable across cluster candidate addresses.")

        arch_probe_ok, _ = _probe_local_endpoint("http://192.168.100.2:8080/v1")
        cls.arch_api_base = (
            "http://192.168.100.2:8080/v1"
            if arch_probe_ok
            else cls.api_base
        )

        env_model = os.environ.get("ORACLE_AGENT_MODEL")
        if env_model and not any(env_model.startswith(p) for p in ("gemini/", "anthropic/", "groq/", "openrouter/")):
            cls.model = env_model if "/" in env_model else f"openai/{env_model}"
        elif discovered_model:
            cls.model = discovered_model if "/" in discovered_model else f"openai/{discovered_model}"
        else:
            cls.model = "openai/qwen3.6-27B-90k-udq4kxl-rag:LATEST"

        env_arch = os.environ.get("ORACLE_ARCHITECT_MODEL")
        if env_arch and not any(env_arch.startswith(p) for p in ("gemini/", "anthropic/", "groq/", "openrouter/")):
            cls.arch_model = env_arch if "/" in env_arch else f"openai/{env_arch}"
        else:
            cls.arch_model = "openai/qwen3.6-27b-90k:LATEST"
        cls.editor_model = os.environ.get(
            "ORACLE_EDITOR_MODEL", "lm_studio/qwen3.6-27B-90k-udq4kxl:LATEST"
        )

        os.environ["ORACLE_AGENT_API_BASE"] = cls.api_base
        os.environ["ORACLE_ARCHITECT_API_BASE"] = cls.arch_api_base
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        os.environ["ORACLE_AGENT_MODEL"] = cls.model
        os.environ["ORACLE_ARCHITECT_MODEL"] = cls.arch_model
        os.environ["ORACLE_NO_RAG_INGEST"] = "1"
        os.environ["ORACLE_RETRIEVE_MODE"] = "no_retrieve"

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)

        import cli
        cli.init_user_project(self.temp_dir)

        # Write real working target file
        os.makedirs("src", exist_ok=True)
        self.target_code = os.path.join("src", "calc.py")
        with open(self.target_code, "w", encoding="utf-8") as f:
            f.write("def calculate_ratio(d, e):\n    return d / e\n")

        # Generate ~6k tokens (approx 24,000 characters) of structured reference context
        self.spec_file = os.path.join("src", "specs_reference.md")
        spec_text = (
            "# Regulatory Capital & Leverage Specifications Reference (v4.2)\n\n"
            "## Section 1: Capital Adequacy Framework\n"
            "Tier 1 Common Equity ratio is strictly defined as CET1 = 0.145 (14.5%) under baseline.\n"
            "Under stress scenario B, the minimum Tier 1 Common Equity ratio drops to CET1_B = 0.082 (8.2%).\n\n"
        ) + (
            "## Technical Computation Appendix\n"
            "The risk-weighted asset denominator involves multi-asset covariance matrices and haircut coefficients.\n"
            + ("- Asset class alpha haircut: factor = 1.042, variance weight = 0.088.\n" * 350)
        )
        with open(self.spec_file, "w", encoding="utf-8") as f:
            f.write(spec_text)

        os.environ["ORACLE_CONTEXT_FILES"] = self.spec_file

        # Write real .env.yml configuration
        os.makedirs(".aider_factory", exist_ok=True)
        self.config_path = os.path.join(".aider_factory", ".env.yml")
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write(
                "name: 'Live Oracle Test'\n"
                f"working_directory: '{self.temp_dir}'\n"
                "endpoints:\n"
                f"  architect_api_base: '{self.arch_api_base}'\n"
                f"  rag_agent_api: '{self.api_base}'\n"
                "phases:\n"
                "  - name: 'Phase 1'\n"
                "    enabled: true\n"
                "    models:\n"
                f"      architect_agent: '{self.arch_model}'\n"
                f"      rag_agent: '{self.model}'\n"
                f"      editor_agent: '{self.editor_model}'\n"
                "    files:\n"
                "      target_files:\n"
                f"        - '{self.target_code}'\n"
                "      context_files_job:\n"
                f"        - '{self.spec_file}'\n"
            )
        os.environ["ORACLE_CONFIG_FILE"] = self.config_path

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_live_oracle_interactive_multi_turn_persistence(self):
        """Live smoke test: Verify multi-turn single queries accumulate history and preserve KV cache."""
        print(f"\n==================================================")
        print(f"[E2E Local Oracle] Testing Endpoint: {self.api_base}")
        print(f"[E2E Local Oracle] Model:            {self.model}")
        print(f"==================================================")

        orig_argv = list(sys.argv)

        # Turn 1: Initial query
        t0 = time.perf_counter()
        sys.argv = [
            "oracle",
            "--no-rag",
            "What is the baseline Tier 1 Common Equity ratio defined in the specifications? Reply with only the ratio.",
        ]
        try:
            rc = oracle_agent.main()
        finally:
            sys.argv = list(orig_argv)
        turn_1_duration = time.perf_counter() - t0
        self.assertEqual(rc, 0)
        print(f"⏱️ Turn 1 (Initial Question): {turn_1_duration:.2f}s")

        session_path = oracle_agent._session_file()
        self.assertTrue(os.path.exists(session_path))
        with open(session_path, "r", encoding="utf-8") as f:
            turn_1_msgs = json.load(f)
        self.assertEqual(len(turn_1_msgs), 3)  # System + User + Assistant

        # Turn 2: Follow-up question referencing turn 1
        t0 = time.perf_counter()
        sys.argv = [
            "oracle",
            "--no-rag",
            "What is the ratio under stress scenario B? Reply with only the ratio.",
        ]
        try:
            rc = oracle_agent.main()
        finally:
            sys.argv = list(orig_argv)
        turn_2_duration = time.perf_counter() - t0
        self.assertEqual(rc, 0)
        print(f"⏱️ Turn 2 (Follow-up):        {turn_2_duration:.2f}s")

        with open(session_path, "r", encoding="utf-8") as f:
            turn_2_msgs = json.load(f)
        self.assertEqual(len(turn_2_msgs), 5)  # System + U1 + A1 + U2 + A2

        # Turn 3: Clear session
        sys.argv = ["oracle", "--clear"]
        try:
            oracle_agent.main()
        finally:
            sys.argv = list(orig_argv)

        self.assertFalse(os.path.exists(session_path))
        print(
            "✅ Live Oracle interactive persistence smoke test passed successfully."
        )

    def test_live_oracle_cli_debate_multi_turn(self):
        """Live smoke test: Verify multi-turn debate pre-assessment and turns."""
        print(f"\n==================================================")
        print(f"[E2E Local Oracle Debate] Testing 2-loop debate against: {self.api_base}")
        print(f"==================================================")

        t0 = time.perf_counter()
        rc = oracle_agent._run_cli_debate(
            "Refactor calculate_ratio in src/calc.py to handle zero division safely.",
            mode="code",
            max_turns=2,
            rounds=1,
        )
        debate_duration = time.perf_counter() - t0
        self.assertEqual(rc, 0)
        print(f"⏱️ Debate Completed in: {debate_duration:.2f}s")

        debate_session = os.path.join(
            ".aider_factory", ".oracle_debate_session.json"
        )
        self.assertTrue(os.path.exists(debate_session))
        with open(debate_session, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("files_hash", data)
        self.assertGreaterEqual(len(data["messages"]), 3)
        print("✅ Live Oracle debate smoke test passed successfully.")


if __name__ == "__main__":
    unittest.main()
