#!/usr/bin/env python3
"""test_e2e_local_persistent_pipeline.py — Live End-to-End Pipeline Smoke Test (Zero Mocks)
Running run_workflow.py with live local models:
  - Architect: qwen3.6-27b-90k:latest (192.168.100.2:8081)
  - Editor:    qwen3.6-35B-80k:latest (192.168.100.1:8080)
  - RAG Agent: qwen3.6-27B-90k-udq4kxl-rag:latest (192.168.100.2:8080)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
pkg_dir = os.path.abspath(os.path.join(script_dir, "../../.."))
python_dir = os.path.join(pkg_dir, "python")
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)
if python_dir not in sys.path:
    sys.path.insert(0, python_dir)


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


class TestE2ELocalPersistentPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Architect Endpoint
        cls.arch_api = os.environ.get(
            "ARCHITECT_API_BASE", "http://192.168.100.2:8080/v1"
        )
        ok, m_id = _probe_local_endpoint(cls.arch_api)
        if not ok:
            for fallback in ["http://192.168.100.1:8080/v1", "http://localhost:8080/v1"]:
                ok, m_id = _probe_local_endpoint(fallback)
                if ok:
                    cls.arch_api = fallback
                    break
            else:
                raise unittest.SkipTest(
                    "No local Architect router reachable on port 8080 or fallback."
                )
        cls.arch_model = (
            (m_id if "/" in m_id else f"openai/{m_id}")
            if ok and m_id
            else "openai/qwen3.6-27b-90k:LATEST"
        )

        # 2. Editor Endpoint
        cls.editor_api = os.environ.get(
            "EDITOR_API_BASE", "http://192.168.100.1:8080/v1"
        )
        ok, m_id = _probe_local_endpoint(cls.editor_api)
        if not ok:
            for fallback in ["http://localhost:8080/v1", cls.arch_api]:
                ok, m_id = _probe_local_endpoint(fallback)
                if ok:
                    cls.editor_api = fallback
                    break
        cls.editor_model = (
            (m_id if "/" in m_id else f"lm_studio/{m_id}")
            if ok and m_id
            else "lm_studio/qwen3.6-27B-90k-udq4kxl:LATEST"
        )

        # 3. RAG Oracle Endpoint
        cls.rag_api = os.environ.get(
            "RAG_AGENT_API", "http://192.168.100.2:8080/v1"
        )
        ok, m_id = _probe_local_endpoint(cls.rag_api)
        if not ok:
            for fallback in [
                "http://192.168.100.1:8080/v1",
                "http://localhost:8080/v1",
                cls.arch_api,
            ]:
                ok, m_id = _probe_local_endpoint(fallback)
                if ok:
                    cls.rag_api = fallback
                    break
        cls.rag_model = (
            (m_id if "/" in m_id else f"openai/{m_id}")
            if ok and m_id
            else "openai/qwen3.6-27B-90k-udq4kxl-rag:LATEST"
        )

        # 4. OCR / Embedder Endpoint
        cls.ocr_embed_api = os.environ.get(
            "OCR_API_BASE", "http://192.168.100.2:8081/v1"
        )
        ok, _ = _probe_local_endpoint(cls.ocr_embed_api)
        if not ok:
            for fallback in [cls.editor_api, cls.arch_api]:
                ok, _ = _probe_local_endpoint(fallback)
                if ok:
                    cls.ocr_embed_api = fallback
                    break

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)

        import cli
        cli.init_user_project(self.temp_dir)

        # Create target code and test files
        os.makedirs("src", exist_ok=True)
        os.makedirs("tests", exist_ok=True)

        self.target_py = os.path.join("src", "calc.py")
        with open(self.target_py, "w", encoding="utf-8") as f:
            f.write(
                "def calculate_leverage(debt, equity):\n"
                "    # INTENTIONAL BUG: Unhandled zero equity\n"
                "    return debt / equity\n"
            )

        self.test_py = os.path.join("tests", "test_calc.py")
        with open(self.test_py, "w", encoding="utf-8") as f:
            f.write(
                "import pytest\n"
                "from src.calc import calculate_leverage\n\n"
                "def test_leverage_normal():\n"
                "    assert calculate_leverage(100, 50) == 2.0\n\n"
                "def test_leverage_zero_equity():\n"
                "    assert calculate_leverage(100, 0) == 0.0\n"
            )

        # Build real .env.yml matching the target architecture
        os.makedirs(".aider_factory", exist_ok=True)
        self.yaml_path = os.path.join(".aider_factory", ".env.yml")

        cfg_data = {
            "name": "Live Local Persistent Pipeline Test",
            "working_directory": self.temp_dir,
            "test_command_prefix": "",
            "test_runner": "python -m pytest {file}",
            "test_naming_and_path": "tests/test_{stem}.py",
            "loop_aider_test": 2,
            "models": {
                "architect_agent": self.arch_model,
                "editor_agent": self.editor_model,
                "editor_agent_test": self.editor_model,
                "editor_agent_test_fallback": self.editor_model,
                "rag_agent": self.rag_model,
                "ocr_agent": "glm-ocr-f16:LATEST",
                "embed_model": "qwen3-embedding-8b-8k:LATEST",
            },
            "endpoints": {
                "architect_api_base": self.arch_api,
                "editor_ollama_api": self.editor_api,
                "editor_test_ollama_api": self.editor_api,
                "rag_agent_api": self.rag_api,
                "ocr_api_base": self.ocr_embed_api,
                "embed_api_base": self.ocr_embed_api,
            },
            "phases": [
                {
                    "name": "Code Repair and Debate",
                    "enabled": True,
                    "rag": {
                        "collection_name": "",
                        "run_ocr_rag": False,
                        "batch": True,
                    },
                    "oracle": {
                        "start_job": False,
                        "template": "src/aider_factory/markdown/internal/analyze_bugs.md",
                        "pre_edit_debate": {
                            "enabled": False,
                        },
                    },
                    "toggles": {
                        "pair_programming": False,
                        "run_job_one": False,
                        "run_job_two": False,
                        "iterate_test": True,
                        "auto_test": False,
                        "sticky_context": True,
                    },
                    "escalation_debate": {
                        "loops": 3,
                        "rounds": 1,
                        "pass_history": True,
                    },
                    "files": {
                        "target_files": [self.target_py],
                        "test_files": [self.test_py],
                        "context_files_job": [self.target_py],
                        "context_files_test": [self.target_py],
                    },
                }
            ],
        }

        with open(self.yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg_data, f)

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_live_full_pipeline_execution(self):
        """Execute run_workflow.py live end-to-end with real local models (Zero Mocks)."""
        workflow_script = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../../python/run_workflow.py")
        )

        print(f"\n==================================================")
        print(f"[E2E Local Pipeline] Starting full pipeline execution...")
        print(f"[E2E Local Pipeline] YAML: {self.yaml_path}")
        print(f"==================================================")

        t0 = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, workflow_script, self.yaml_path],
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
        )
        duration = time.perf_counter() - t0
        print(f"⏱️ Pipeline Finished in: {duration:.2f}s")
        print(f"Stdout:\n{proc.stdout[-1500:]}")
        if proc.stderr:
            print(f"Stderr:\n{proc.stderr[-1000:]}")

        logs_dir = os.path.join(".aider_factory", "logs")
        self.assertTrue(os.path.exists(logs_dir))
        print("✅ Live Local Pipeline E2E Smoke Test completed.")


if __name__ == "__main__":
    unittest.main()
