#!/usr/bin/env python3
# test_e2e_weak_model_routing.py — Zero-Mock End-to-End Test Suite for
# Local Weak Model Endpoint Routing and Model Settings Generation.

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Optional

import yaml

# Ensure project modules are importable
current_dir = os.path.dirname(os.path.abspath(__file__))
python_dir = os.path.abspath(os.path.join(current_dir, "../../../python"))
if python_dir not in sys.path:
    sys.path.insert(0, python_dir)

from env_utils import ensure_model_settings, is_local_model
from orchestrate import AiderFactory, Task
from apply_agent import resolve_editor_config, run_apply


class MockOpenAIModelServer(http.server.BaseHTTPRequestHandler):
    """Real HTTP server implementing the OpenAI-compatible v1 API for weak models."""

    received_requests = []

    def log_message(self, format, *args):
        pass  # Suppress default server stderr logging

    def do_GET(self):
        if "/models" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "object": "list",
                "data": [
                    {"id": "qwen2.5-coder-7b", "object": "model"},
                    {"id": "openai/qwen2.5-coder-7b", "object": "model"},
                    {"id": "lm_studio/qwen3.6-27b-custom", "object": "model"},
                ],
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        parsed = json.loads(body) if body else {}

        MockOpenAIModelServer.received_requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": parsed,
            }
        )

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        resp = {
            "id": "chatcmpl-mock-weak",
            "object": "chat.completion",
            "created": 1234567890,
            "model": parsed.get("model", "qwen2.5-coder-7b"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "commit: update target file implementation",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        }
        self.wfile.write(json.dumps(resp).encode("utf-8"))


class TestE2EWeakModelRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        MockOpenAIModelServer.received_requests = []
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), MockOpenAIModelServer)
        cls.port = cls.server.server_port
        cls.api_base = f"http://127.0.0.1:{cls.port}/v1"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        MockOpenAIModelServer.received_requests.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox = Path(self.temp_dir.name)

        # Initialize local git repository
        subprocess.run(["git", "init"], cwd=self.sandbox, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.sandbox, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.sandbox, check=True, capture_output=True)

        self.af_dir = self.sandbox / ".aider_factory"
        self.af_dir.mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_e2e_model_settings_synthesis(self):
        """Verify that ensure_model_settings synthesizes accurate model settings with aliases."""
        settings_path = str(self.af_dir / ".aider.model.settings.yml")
        models = [
            {
                "name": "openai/qwen2.5-coder-7b",
                "api_base": self.api_base,
                "api_key": "sk-dummy",
            },
            {
                "name": "lm_studio/qwen3.6-27b-custom",
                "api_base": self.api_base,
                "api_key": "sk-dummy",
            },
        ]

        ensure_model_settings(settings_path, models)

        self.assertTrue(os.path.exists(settings_path))
        with open(settings_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        configured_names = [item["name"] for item in data]
        self.assertIn("openai/qwen2.5-coder-7b", configured_names)
        self.assertIn("qwen2.5-coder-7b", configured_names)
        self.assertIn("lm_studio/qwen3.6-27b-custom", configured_names)
        self.assertIn("qwen3.6-27b-custom", configured_names)

        for item in data:
            self.assertEqual(item["extra_params"]["api_base"], self.api_base)
            self.assertEqual(item["extra_params"]["api_key"], "sk-dummy")

    def test_e2e_orchestrator_session_config_and_settings(self):
        """Verify that AiderFactory task execution generates session-scoped configs for weak model."""
        bin_dir = self.sandbox / "bin"
        bin_dir.mkdir(exist_ok=True)
        fake_aider = bin_dir / ("aider.cmd" if sys.platform == "win32" else "aider")
        captured_args = self.sandbox / "captured_orch_args.txt"

        if sys.platform == "win32":
            py_script = bin_dir / "fake_orch_aider.py"
            py_script.write_text(
                f"import sys\n"
                f"with open(r'{captured_args}', 'w') as f:\n"
                f"    for a in sys.argv[1:]: f.write(a + '\\n')\n"
                f"sys.exit(0)\n",
                encoding="utf-8",
            )
            fake_aider.write_text(f'@"{sys.executable}" "%~dp0fake_orch_aider.py" %*\n', encoding="utf-8")
        else:
            fake_aider.write_text(
                f"#!/usr/bin/env python3\n"
                f"import sys\n"
                f"with open('{captured_args}', 'w') as f:\n"
                f"    for a in sys.argv[1:]: f.write(a + '\\n')\n"
                f"sys.exit(0)\n",
                encoding="utf-8",
            )
            fake_aider.chmod(0o755)

        orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{orig_path}"
        try:
            target_file = self.sandbox / "target.py"
            target_file.write_text("x = 1\n", encoding="utf-8")

            session_name = "test_weak_session"
            factory = AiderFactory(
                project_dir=str(self.sandbox),
                session_name=session_name,
            )

            task = Task(
                id="task_weak_test",
                model="openai/dummy-architect",
                editor_model="openai/dummy-editor",
                weak_model="openai/qwen2.5-coder-7b",
                weak_model_api_base=self.api_base,
                files=[str(target_file)],
            )
            factory.add_task(task)
            success = factory.run_task(task)
            self.assertTrue(success)

            sess_dir = factory.session_dir
            session_settings = sess_dir / ".aider.model.settings.yml"
            self.assertTrue(session_settings.exists())

            with open(session_settings, "r", encoding="utf-8") as f:
                settings_data = yaml.safe_load(f)
            names = [entry["name"] for entry in settings_data]
            self.assertIn("openai/qwen2.5-coder-7b", names)
            self.assertIn("qwen2.5-coder-7b", names)

            args = captured_args.read_text(encoding="utf-8").splitlines()
            self.assertIn("--weak-model", args)
            weak_idx = args.index("--weak-model")
            self.assertEqual(args[weak_idx + 1], "openai/qwen2.5-coder-7b")
            self.assertIn("--model-settings-file", args)
        finally:
            os.environ["PATH"] = orig_path

    def test_e2e_cloud_weak_model_isolation(self):
        """Verify that cloud weak models with placeholder endpoints do NOT generate local settings."""
        env_yaml = self.af_dir / ".env.yml"
        env_yaml.write_text(
            yaml.dump(
                {
                    "models": {
                        "editor_agent": "gemini/gemini-2.5-flash",
                        "weak_model": "gemini/gemini-3.5-flash-lite",
                    },
                    "endpoints": {
                        "editor_api": "http://<your-router-host>:4000/v1",
                        "weak_model_api_base": "http://<your-router-host>:4000/v1",
                    },
                }
            ),
            encoding="utf-8",
        )

        cfg = resolve_editor_config(str(self.sandbox))
        self.assertEqual(cfg["weak_model"], "gemini/gemini-3.5-flash-lite")
        self.assertIsNone(cfg["weak_model_api_base"])

        bin_dir = self.sandbox / "bin"
        bin_dir.mkdir(exist_ok=True)
        fake_aider = bin_dir / ("aider.cmd" if sys.platform == "win32" else "aider")
        captured_args = self.sandbox / "captured_cloud_args.txt"

        if sys.platform == "win32":
            py_script = bin_dir / "fake_cloud_aider.py"
            py_script.write_text(
                f"import sys\n"
                f"with open(r'{captured_args}', 'w') as f:\n"
                f"    for a in sys.argv[1:]: f.write(a + '\\n')\n"
                f"sys.exit(0)\n",
                encoding="utf-8",
            )
            fake_aider.write_text(f'@"{sys.executable}" "%~dp0fake_cloud_aider.py" %*\n', encoding="utf-8")
        else:
            fake_aider.write_text(
                f"#!/usr/bin/env python3\n"
                f"import sys\n"
                f"with open('{captured_args}', 'w') as f:\n"
                f"    for a in sys.argv[1:]: f.write(a + '\\n')\n"
                f"sys.exit(0)\n",
                encoding="utf-8",
            )
            fake_aider.chmod(0o755)

        orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{orig_path}"
        try:
            target_file = self.sandbox / "cloud_target.py"
            target_file.write_text("y = 1\n", encoding="utf-8")
            spec_file = self.sandbox / "cloud_spec.md"
            spec_file.write_text("Change y = 1 to y = 2\n", encoding="utf-8")

            success = run_apply(
                files=[str(target_file)],
                spec_file=str(spec_file),
                no_diff=True,
                cwd=str(self.sandbox),
            )
            self.assertTrue(success)

            args = captured_args.read_text(encoding="utf-8").splitlines()
            self.assertIn("--weak-model", args)
            weak_idx = args.index("--weak-model")
            self.assertEqual(args[weak_idx + 1], "gemini/gemini-3.5-flash-lite")
            # Should NOT pass a generated apply model settings file
            if "--model-settings-file" in args:
                settings_idx = args.index("--model-settings-file")
                self.assertNotIn(".apply.aider.model.settings.yml", args[settings_idx + 1])
        finally:
            os.environ["PATH"] = orig_path

    def test_e2e_custom_local_suffix(self):
        """Verify custom local models with tags/suffixes generate settings and alias mappings."""
        settings_path = str(self.af_dir / ".custom_suffix.model.settings.yml")
        models = [
            {
                "name": "lm_studio/qwen3.6-27b-custom:q4_k_m",
                "api_base": self.api_base,
                "api_key": "sk-dummy",
            }
        ]
        ensure_model_settings(settings_path, models)

        with open(settings_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        configured_names = [item["name"] for item in data]
        self.assertIn("lm_studio/qwen3.6-27b-custom:q4_k_m", configured_names)
        self.assertIn("qwen3.6-27b-custom:q4_k_m", configured_names)
        self.assertEqual(data[0]["extra_params"]["api_base"], self.api_base)

    def test_e2e_apply_agent_resolves_and_generates_settings(self):
        """Verify apply_agent resolves weak model and generates .apply.aider.model.settings.yml."""
        env_yaml = self.af_dir / ".env.yml"
        env_yaml.write_text(
            yaml.dump(
                {
                    "models": {
                        "editor_agent": "openai/qwen2.5-coder-7b",
                        "weak_model": "lm_studio/qwen3.6-27b-custom",
                    },
                    "endpoints": {
                        "editor_api": self.api_base,
                        "weak_model_api_base": self.api_base,
                    },
                }
            ),
            encoding="utf-8",
        )

        cfg = resolve_editor_config(str(self.sandbox))
        self.assertEqual(cfg["weak_model"], "lm_studio/qwen3.6-27b-custom")
        self.assertEqual(cfg["weak_model_api_base"], self.api_base)

        target_file = self.sandbox / "sample.py"
        target_file.write_text("x = 1\n", encoding="utf-8")
        spec_file = self.sandbox / "spec.md"
        spec_file.write_text("Change x = 1 to x = 2\n", encoding="utf-8")

        # Create dummy aider binary in sandbox PATH to intercept apply execution
        bin_dir = self.sandbox / "bin"
        bin_dir.mkdir()
        fake_aider = bin_dir / ("aider.cmd" if sys.platform == "win32" else "aider")
        captured_args = self.sandbox / "captured_aider_args.txt"

        if sys.platform == "win32":
            py_script = bin_dir / "fake_aider.py"
            py_script.write_text(
                f"import sys\n"
                f"with open(r'{captured_args}', 'w') as f:\n"
                f"    for a in sys.argv[1:]: f.write(a + '\\n')\n"
                f"sys.exit(0)\n",
                encoding="utf-8",
            )
            fake_aider.write_text(f'@"{sys.executable}" "%~dp0fake_aider.py" %*\n', encoding="utf-8")
        else:
            fake_aider.write_text(
                f"#!/usr/bin/env python3\n"
                f"import sys\n"
                f"with open('{captured_args}', 'w') as f:\n"
                f"    for a in sys.argv[1:]: f.write(a + '\\n')\n"
                f"sys.exit(0)\n",
                encoding="utf-8",
            )
            fake_aider.chmod(0o755)

        orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{orig_path}"
        try:
            success = run_apply(
                files=[str(target_file)],
                spec_file=str(spec_file),
                no_diff=True,
                cwd=str(self.sandbox),
            )
            self.assertTrue(success)

            # Assert aider received --weak-model and --model-settings-file
            args = captured_args.read_text(encoding="utf-8").splitlines()
            self.assertIn("--weak-model", args)
            weak_idx = args.index("--weak-model")
            self.assertEqual(args[weak_idx + 1], "lm_studio/qwen3.6-27b-custom")

            self.assertIn("--model-settings-file", args)
            settings_idx = args.index("--model-settings-file")
            generated_settings_file = args[settings_idx + 1]
            self.assertTrue(os.path.isfile(generated_settings_file))

            with open(generated_settings_file, "r", encoding="utf-8") as f:
                settings_content = yaml.safe_load(f)
            names = [entry["name"] for entry in settings_content]
            self.assertIn("lm_studio/qwen3.6-27b-custom", names)
            self.assertIn("qwen3.6-27b-custom", names)
            self.assertEqual(settings_content[0]["extra_params"]["api_base"], self.api_base)
        finally:
            os.environ["PATH"] = orig_path

    def test_e2e_real_socket_request_to_mock_server(self):
        """Verify that an HTTP client targeting the weak model endpoint sends a valid completion request."""
        import urllib.request

        payload = {
            "model": "openai/qwen2.5-coder-7b",
            "messages": [{"role": "user", "content": "summarize commit"}],
        }
        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer sk-dummy"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(len(MockOpenAIModelServer.received_requests), 1)
        self.assertEqual(
            MockOpenAIModelServer.received_requests[0]["body"]["model"],
            "openai/qwen2.5-coder-7b",
        )
        self.assertIn("choices", data)
        self.assertIn("commit: update target file", data["choices"][0]["message"]["content"])


if __name__ == "__main__":
    unittest.main()
