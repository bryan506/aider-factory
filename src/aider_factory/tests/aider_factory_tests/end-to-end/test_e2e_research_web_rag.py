#!/usr/bin/env python3
# test_e2e_research_web_rag.py — Zero-Mock End-to-End Live Web Ingestion and LanceDB Indexing.

import http.server
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import tempfile
import unittest

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../../python"))
sys.path.insert(0, python_module_dir)

import lancedb
import oracle_agent
import rag_web
import research_agent


class LocalhostFixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/sitemap.xml":
            xml = """<?xml version="1.0" encoding="UTF-8"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>http://127.0.0.1:{port}/docs/guide.html</loc></url>
                <url><loc>http://127.0.0.1:{port}/docs/zh-cn/guide.html</loc></url>
                <url><loc>http://127.0.0.1:{port}/blog/news.html</loc></url>
            </urlset>""".format(port=self.server.server_address[1])
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.end_headers()
            self.wfile.write(xml.encode("utf-8"))
        elif self.path == "/docs/guide.html":
            html = """<!DOCTYPE html><html><head><title>System Documentation Guide</title></head>
            <body><main><h1>System Documentation Guide</h1>
            <p>This is a complete, live HTML guide explaining automated workflow pipelines and vector search indexing.
            It provides detailed documentation text exceeding the extraction threshold cleanly.</p>
            </main></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        elif self.path == "/llms.txt":
            content = f"# Docs Index\n- [Quickstart](http://127.0.0.1:{self.server.server_address[1]}/quickstart.md): Getting started\n- [Indexing](/indexing.md): Vector index guide\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        elif self.path == "/llms-full.txt":
            content = "# Full LanceDB Corpus\n\nComplete guide to vector search, IVF-PQ, and hybrid search.\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        elif self.path == "/quickstart.md":
            content = "# Quickstart Guide\n\nRun pip install lancedb and create a table in 3 lines.\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        elif self.path == "/indexing.md":
            content = "# Vector Indexing Guide\n\nLearn how to create IVF-PQ and HNSW indices.\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        if self.path in ("/docs/guide.html", "/quickstart.md", "/indexing.md", "/llms.txt", "/llms-full.txt"):
            self.send_response(200)
            if self.path.endswith((".md", ".txt")):
                self.send_header("Content-Type", "text/plain; charset=utf-8")
            else:
                self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress HTTP server console logs in test output


class TestE2EResearchWebRAG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.HTTPServer(("127.0.0.1", 0), LocalhostFixtureHandler)
        cls.port = cls.httpd.server_address[1]
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir)

        # Clear leaked environment variables from prior test modules
        for k in list(os.environ.keys()):
            if k.startswith("ORACLE_") or k.startswith("AI_FACTORY_"):
                os.environ.pop(k, None)

        self.collection = "e2e_live_web_smoke"
        self.context_root = os.path.join(self.temp_dir, ".aider_factory", "markdown", "lanceDB")
        self.job_dir = os.path.join(self.context_root, self.collection)
        os.makedirs(self.job_dir, exist_ok=True)

        os.environ["ORACLE_COLLECTION"] = self.collection
        os.environ["ORACLE_EXPLICIT_COLLECTION"] = "1"
        os.environ["ORACLE_RAG_DB_DIR"] = os.path.join(self.job_dir, "lancedb")

    def tearDown(self):
        os.chdir(self.old_cwd)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        for k in list(os.environ.keys()):
            if k.startswith("ORACLE_") or k.startswith("AI_FACTORY_"):
                os.environ.pop(k, None)

    def test_live_sitemap_harvest_and_localhost_web_ingestion(self):
        """Zero-mock live HTTP test: harvests sitemap over localhost and ingests into LanceDB."""
        sitemap_url = f"http://127.0.0.1:{self.port}/sitemap.xml"
        out_urls_file = os.path.join(self.temp_dir, "harvested_urls.txt")

        research_agent.run_sitemap_harvester(
            sitemap_url,
            grep_pat="docs",
            grep_ex_pat="zh-cn",
            out_path=out_urls_file,
        )

        self.assertTrue(os.path.exists(out_urls_file))
        with open(out_urls_file, "r", encoding="utf-8") as f:
            urls = [l.strip() for l in f if l.strip()]

        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0], f"http://127.0.0.1:{self.port}/docs/guide.html")

        # Ingest the harvested URL directly via oracle_agent maintenance
        saved_file, content_type = rag_web.fetch_and_convert_url(urls[0], self.job_dir)
        self.assertIsNotNone(saved_file)
        self.assertTrue(os.path.exists(saved_file))

        with open(saved_file, "r", encoding="utf-8") as f:
            md_text = f.read()
        self.assertIn("System Documentation Guide", md_text)

    def test_live_research_report_rendering(self):
        """Zero-mock test: renders research report to disk with physical file verification."""
        results = [
            {
                "title": "Empirical Study on Vector Indexes",
                "url": "https://example.org/study",
                "engine": "arxiv",
                "content": "Vector similarity benchmarks in LanceDB.",
            }
        ]
        report_path = research_agent.render_research_report(
            "vector benchmarks",
            results,
            engines_used="arxiv",
            out_path=os.path.join(self.temp_dir, "research_report.md"),
        )
        self.assertTrue(os.path.exists(report_path))
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Vector similarity benchmarks in LanceDB", content)

    def test_e2e_research_sitemap_harvester_llms_txt_cli(self):
        """Zero-mock E2E CLI smoke test: research_agent harvests llms.txt via subprocess."""
        out_file = os.path.join(self.temp_dir, "harvested_llms_urls.txt")
        target_url = f"http://127.0.0.1:{self.port}/llms.txt"
        research_script = os.path.join(python_module_dir, "research_agent.py")

        cmd = [
            sys.executable,
            research_script,
            "search",
            target_url,
            "--sitemap",
            "--out",
            out_file,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=self.temp_dir)
        self.assertEqual(res.returncode, 0, f"Process failed: {res.stderr}")
        self.assertTrue(os.path.exists(out_file))

        with open(out_file, "r", encoding="utf-8") as f:
            urls = [l.strip() for l in f if l.strip()]

        self.assertIn(f"http://127.0.0.1:{self.port}/quickstart.md", urls)
        self.assertIn(f"http://127.0.0.1:{self.port}/indexing.md", urls)

    def test_e2e_oracle_add_web_llms_full_txt_direct_download_cli(self):
        """Zero-mock E2E CLI smoke test: oracle --add-web downloads llms-full.txt directly without hijacking."""
        target_url = f"http://127.0.0.1:{self.port}/llms-full.txt"
        oracle_script = os.path.join(python_module_dir, "oracle_agent.py")

        # Set up a sandbox .aider_factory/.env.yml
        os.makedirs(os.path.join(self.temp_dir, ".aider_factory"), exist_ok=True)
        sandbox_env_yml = os.path.join(self.temp_dir, ".aider_factory", ".env.yml")
        with open(sandbox_env_yml, "w", encoding="utf-8") as f:
            f.write(f"working_directory: \"{self.temp_dir}\"\n")

        env = os.environ.copy()
        env["ORACLE_CONFIG_FILE"] = sandbox_env_yml
        env["ORACLE_COLLECTION"] = "e2e_full_docs"
        env["ORACLE_EXPLICIT_COLLECTION"] = "1"
        env["ORACLE_RAG_DB_DIR"] = os.path.join(
            self.temp_dir, ".aider_factory", "markdown", "lanceDB", "e2e_full_docs", "lancedb"
        )

        cmd = [
            sys.executable,
            oracle_script,
            "--collection",
            "e2e_full_docs",
            "--add-web",
            target_url,
            "--no-rag",
        ]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=self.temp_dir)
        self.assertEqual(res.returncode, 0, f"Process failed: {res.stderr}")

        job_dir = Path(self.temp_dir) / ".aider_factory" / "markdown" / "lanceDB" / "e2e_full_docs"
        self.assertTrue(job_dir.exists())

        md_files = list(job_dir.glob("*.md"))
        self.assertEqual(len(md_files), 1)

        saved_file = md_files[0]
        self.assertNotIn("_llms.md", saved_file.name, "File must not be hijacked to root _llms.md!")

        content = saved_file.read_text(encoding="utf-8")
        self.assertIn("# Full LanceDB Corpus", content)
        self.assertIn("Complete guide to vector search, IVF-PQ, and hybrid search.", content)

    def test_e2e_oracle_add_web_batch_llms_txt_expansion_cli(self):
        """Zero-mock E2E CLI smoke test: oracle --add-web expands llms.txt and batch-downloads child pages."""
        target_url = f"http://127.0.0.1:{self.port}/llms.txt"
        oracle_script = os.path.join(python_module_dir, "oracle_agent.py")

        os.makedirs(os.path.join(self.temp_dir, ".aider_factory"), exist_ok=True)
        sandbox_env_yml = os.path.join(self.temp_dir, ".aider_factory", ".env.yml")
        with open(sandbox_env_yml, "w", encoding="utf-8") as f:
            f.write(f"working_directory: \"{self.temp_dir}\"\n")

        env = os.environ.copy()
        env["ORACLE_CONFIG_FILE"] = sandbox_env_yml
        env["ORACLE_COLLECTION"] = "e2e_batch_docs"
        env["ORACLE_EXPLICIT_COLLECTION"] = "1"
        env["ORACLE_RAG_DB_DIR"] = os.path.join(
            self.temp_dir, ".aider_factory", "markdown", "lanceDB", "e2e_batch_docs", "lancedb"
        )

        cmd = [
            sys.executable,
            oracle_script,
            "--collection",
            "e2e_batch_docs",
            "--add-web",
            target_url,
            "--workers",
            "2",
            "--no-rag",
        ]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=self.temp_dir)
        self.assertEqual(res.returncode, 0, f"Process failed: {res.stderr}")

        job_dir = Path(self.temp_dir) / ".aider_factory" / "markdown" / "lanceDB" / "e2e_batch_docs"
        self.assertTrue(job_dir.exists())

        md_files = list(job_dir.glob("*.md"))
        self.assertEqual(len(md_files), 2)

        combined_text = "\n".join(f.read_text(encoding="utf-8") for f in md_files)
        self.assertIn("Quickstart Guide", combined_text)
        self.assertIn("Vector Indexing Guide", combined_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
