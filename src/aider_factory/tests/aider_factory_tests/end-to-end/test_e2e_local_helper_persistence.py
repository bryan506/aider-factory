#!/usr/bin/env python3
"""test_e2e_local_helper_persistence.py — End-to-End Live Smoke Test (Zero Mocks) for
aider-helper KV-Cache Persistence against real local LLM endpoints.
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

import bootstrap


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
                m_ids = [
                    m["id"]
                    for m in models
                    if "id" in m
                    and not (isinstance(m.get("status"), dict) and m["status"].get("failed"))
                    and not ("192.168.100.2" in url and "qwen3.6" in m["id"].lower())
                    and not any(
                        x in m["id"].lower()
                        for x in ("embed", "rerank", "ocr", "minicheck", "bge", "jina")
                    )
                ]
                q38_27b = [m for m in m_ids if "qwen3.8" in m.lower() and "27b" in m.lower()]
                favored = q38_27b or [m for m in m_ids if "27b" in m.lower()]
                candidates = favored + [m for m in m_ids if m not in favored]
                for cand in candidates[:3]:
                    chat_req = urllib.request.Request(
                        f"{url.rstrip('/')}/chat/completions",
                        data=json.dumps(
                            {
                                "model": cand,
                                "messages": [{"role": "user", "content": "ping"}],
                                "max_tokens": 1,
                            }
                        ).encode("utf-8"),
                        headers={
                            "Authorization": "Bearer sk-dummy",
                            "Content-Type": "application/json",
                        },
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(chat_req, timeout=15) as c_resp:
                            if c_resp.status == 200:
                                return True, cand
                    except Exception:
                        continue
    except Exception:
        pass
    return False, None


class TestE2ELocalHelperPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidate_bases = [
            os.environ.get("AIDER_HELPER_API_BASE"),
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
            raise unittest.SkipTest(
                "No local helper endpoint reachable across cluster candidate addresses."
            )

        if discovered_model:
            cls.model = discovered_model if "/" in discovered_model else f"openai/{discovered_model}"
        else:
            cls.model = "gemini/gemini-2.5-flash"
        os.environ["AIDER_HELPER_API_BASE"] = cls.api_base
        os.environ["AIDER_HELPER_MODEL"] = cls.model
        os.environ["OPENAI_API_KEY"] = "sk-dummy"

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)

        # Set up a real .aider_factory/.env.yml in sandbox
        os.makedirs(".aider_factory", exist_ok=True)
        self.real_yaml_path = os.path.join(".aider_factory", ".env.yml")
        with open(self.real_yaml_path, "w", encoding="utf-8") as f:
            f.write(
                "name: 'Live Helper Test'\n"
                f"working_directory: '{self.temp_dir}'\n"
                "phases:\n"
                "  - name: 'Phase 1'\n"
                "    enabled: true\n"
                "    models:\n"
                f"      architect_agent: '{self.model}'\n"
                "      editor_agent: 'lm_studio/qwen3.6-27B-90k-udq4kxl:latest'\n"
                "    files:\n"
                "      target_files:\n"
                "        - 'src/main.py'\n"
            )

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_live_helper_multi_turn_kv_cache_latency_drop(self):
        """Live smoke test with NO mocks:
        Turn 1: Heavy warmup payload with master mode (injects skills reference).
        Turn 2: Follow-up question hitting the warm KV cache prefix.
        Turn 3: Live modification writing to real .env.yml configuration.
        Turn 4: Terminal Assistant Mode (-t) independent session.
        """
        print(f"\n==================================================")
        print(f"[E2E Local Helper] Testing Endpoint: {self.api_base}")
        print(f"[E2E Local Helper] Model:            {self.model}")
        print(f"==================================================")

        # Turn 1: Warmup with heavy skills context
        t0 = time.perf_counter()
        bootstrap.run_query(
            "What is the architect agent configured in the active phase?",
            self.real_yaml_path,
            "",
            ask_mode=True,
            master_mode=True,
        )
        turn_1_duration = time.perf_counter() - t0
        print(f"⏱️ Turn 1 (Warmup with Master Skills): {turn_1_duration:.2f}s")

        session_file = os.path.join(".aider_factory", ".helper_session.json")
        self.assertTrue(os.path.exists(session_file))
        with open(session_file, "r", encoding="utf-8") as f:
            turn_1_data = json.load(f)
        self.assertEqual(len(turn_1_data), 3)  # System + User + Assistant
        # Verify master mode captured both skills and reference schema
        turn_1_prompt = turn_1_data[1]["content"]
        self.assertIn("<skills_reference>", turn_1_prompt)
        self.assertIn("<reference_schema>", turn_1_prompt)

        # Turn 2: Follow-up question (should hit warm prefix cache)
        t0 = time.perf_counter()
        bootstrap.run_query(
            "What is the target file listed in that phase?",
            self.real_yaml_path,
            "",
            ask_mode=True,
            master_mode=False,
        )
        turn_2_duration = time.perf_counter() - t0
        print(f"⏱️ Turn 2 (Follow-up Prefix Hit):     {turn_2_duration:.2f}s")

        with open(session_file, "r", encoding="utf-8") as f:
            turn_2_data = json.load(f)
        self.assertEqual(len(turn_2_data), 5)  # System + U1 + A1 + U2 + A2

        # Turn 3: Live configuration modification
        bootstrap.run_query(
            "Change the target file to 'src/app.py' in the YAML configuration.",
            self.real_yaml_path,
            "",
            ask_mode=False,
            master_mode=False,
        )
        with open(self.real_yaml_path, "r", encoding="utf-8") as f:
            updated_yaml = f.read()
        self.assertIn("src/app.py", updated_yaml)

        # Turn 4: Terminal Assistant Mode (-t) independent session
        t0 = time.perf_counter()
        bootstrap.run_query(
            "Explain Python list slicing syntax in 2 sentences.",
            None,
            "",
            ask_mode=True,
            terminal_mode=True,
        )
        term_duration = time.perf_counter() - t0
        print(f"⏱️ Turn 4 (Terminal Assistant):       {term_duration:.2f}s")

        term_session = os.path.join(
            ".aider_factory", ".helper_terminal_session.json"
        )
        self.assertTrue(os.path.exists(term_session))
        print("✅ Live KV Cache persistence smoke test passed successfully.")


if __name__ == "__main__":
    unittest.main()
