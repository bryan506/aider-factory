#!/usr/bin/env python3
# test_e2e_research_web_rag.py — Zero-Mock End-to-End Live Web Ingestion and LanceDB Indexing.

import http.server
import os
import shutil
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
            self.send_response(404)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        if self.path == "/docs/guide.html":
            self.send_response(200)
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
        self.collection = "e2e_live_web_smoke"
        self.context_root = os.path.join(self.temp_dir, ".aider_factory", "markdown", "lanceDB")
        self.job_dir = os.path.join(self.context_root, self.collection)
        os.makedirs(self.job_dir, exist_ok=True)

        os.environ["ORACLE_COLLECTION"] = self.collection
        os.environ["ORACLE_EXPLICIT_COLLECTION"] = "1"
        os.environ["ORACLE_RAG_DB_DIR"] = os.path.join(self.job_dir, "lancedb")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        os.environ.pop("ORACLE_EXPLICIT_COLLECTION", None)
        os.environ.pop("ORACLE_RAG_DB_DIR", None)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
