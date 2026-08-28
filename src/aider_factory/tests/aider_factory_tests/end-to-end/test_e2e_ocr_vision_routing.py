import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer


class MockVisionServer(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)
        payload = json.loads(post_data)
        MockVisionServer.requests.append(payload)

        if self.path.endswith("/chat/completions"):
            model = payload.get("model", "")
            base_text = getattr(MockVisionServer, "mock_text_base", "")
            if "unlimited" in model.lower():
                text = base_text + "\n\nMocked Unlimited OCR Output. [Diagram: A chart showing FX rates]"
            else:
                text = base_text + "\n\nMocked GLM OCR Output. The quick brown fox."

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            response = {"choices": [{"message": {"content": text}}]}
            self.wfile.write(json.dumps(response).encode("utf-8"))
        elif self.path.endswith("/embeddings"):
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            response = {"data": [{"embedding": [0.1] * 1536}]}
            self.wfile.write(json.dumps(response).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class TestE2EOCRVisionRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        MockVisionServer.requests = []
        cls.server = HTTPServer(("localhost", 0), MockVisionServer)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()

        cls.pkg_dir = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
            )
        )
        cls.oracle_script = os.path.join(
            cls.pkg_dir, "aider_factory", "python", "oracle_agent.py"
        )

        cls.pdf_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "January-2026-FX-Report.pdf"
        )

        try:
            import fitz
            doc = fitz.open(cls.pdf_path)
            MockVisionServer.mock_text_base = doc[0].get_text("text")
        except Exception:
            MockVisionServer.mock_text_base = ""

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def setUp(self):
        MockVisionServer.requests = []
        self.temp_dir = tempfile.mkdtemp()

        # Ensure PDF fixture exists or create a dummy one if running in isolation
        if not os.path.exists(self.pdf_path):
            with open(self.pdf_path, "wb") as f:
                # Basic empty PDF header structure
                f.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\nxref\n0 3\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\ntrailer<</Size 3/Root 1 0 R>>\nstartxref\n102\n%%EOF")

    def _write_yaml(self, ocr_agent, ocr_prompt):
        yaml_path = os.path.join(self.temp_dir, ".env.yml")
        content = f"""
working_directory: "{self.temp_dir}"
endpoints:
  ocr_api_base: "http://localhost:{self.port}/v1"
  embed_api_base: "http://localhost:{self.port}/v1"
phases:
  - name: "Test"
    enabled: true
    models:
      ocr_agent: "{ocr_agent}"
      embed_model: "dummy-embed"
      embed_backend: "openai"
    rag:
      use_docling: false
      ocr_prompt: "{ocr_prompt}"
"""
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(content)
        return yaml_path

    def _run_and_verify(self, ocr_agent, ocr_prompt, expected_text):
        yaml_path = self._write_yaml(ocr_agent, ocr_prompt)
        collection_name = "test_coll"

        env = os.environ.copy()
        env["ORACLE_CONFIG_FILE"] = yaml_path
        env["OPENAI_API_KEY"] = "sk-dummy"

        cmd = [
            sys.executable,
            self.oracle_script,
            "--add-file",
            self.pdf_path,
            "--collection",
            collection_name,
        ]

        res = subprocess.run(
            cmd, env=env, capture_output=True, text=True, cwd=self.temp_dir
        )
        self.assertEqual(res.returncode, 0, f"Oracle ingestion failed:\n{res.stderr}")

        # 1. Verify Network Payload
        ocr_requests = [r for r in MockVisionServer.requests if "messages" in r]
        self.assertGreater(
            len(ocr_requests), 0, "No OCR request was sent to the mock server."
        )

        last_req = ocr_requests[-1]
        self.assertEqual(last_req["model"], ocr_agent)

        messages = last_req["messages"]
        self.assertEqual(messages[0]["role"], "user")
        content = messages[0]["content"]

        text_part = next(c for c in content if c["type"] == "text")
        self.assertEqual(text_part["text"], ocr_prompt)

        img_part = next(c for c in content if c["type"] == "image_url")
        self.assertTrue(
            img_part["image_url"]["url"].startswith("data:image/png;base64,")
        )

        # 2. Verify Physical Artifacts
        pdf_stem = os.path.splitext(os.path.basename(self.pdf_path))[0]
        md_out_path = os.path.join(
            self.temp_dir,
            ".aider_factory",
            "markdown",
            "lanceDB",
            collection_name,
            f"{pdf_stem}.md",
        )

        self.assertTrue(
            os.path.exists(md_out_path),
            f"Markdown artifact not generated at {md_out_path}",
        )

        with open(md_out_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        self.assertIn(
            expected_text,
            md_content,
            "Generated Markdown did not contain the expected OCR output.",
        )

    def test_glm_ocr_routing_and_artifacts(self):
        self._run_and_verify(
            ocr_agent="glm-ocr-f16:LATEST",
            ocr_prompt="Extract text, tables, math, code, and documentation into clean Markdown. Preserve all structural integrity.",
            expected_text="Mocked GLM OCR Output. The quick brown fox.",
        )

    def test_unlimited_ocr_routing_and_artifacts(self):
        self._run_and_verify(
            ocr_agent="unlimited-ocr-bf16:latest",
            ocr_prompt="<|grounding|>Convert the document to markdown.",
            expected_text="Mocked Unlimited OCR Output. [Diagram: A chart showing FX rates]",
        )


if __name__ == "__main__":
    unittest.main()
