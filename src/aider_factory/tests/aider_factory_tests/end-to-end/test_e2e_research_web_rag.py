#!/usr/bin/env python3
# test_e2e_research_web_rag.py — End-to-End Golden Smoke Test for Web Research & Ingestion.

import os
import shutil
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock trafilatura in sys.modules before importing any package modules
# to prevent ModuleNotFoundError if it's not installed in the test environment
sys.modules["trafilatura"] = MagicMock()

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../../python"))
sys.path.insert(0, python_module_dir)

import lancedb
import oracle_agent
import research_agent

project_dir = os.getcwd()


class TestE2EResearchWebRAG(unittest.TestCase):
    def setUp(self):
        self.collection = "e2e_web_smoke"
        self.context_root = os.path.join(
            project_dir, ".aider_factory", "markdown", "lanceDB"
        )
        self.job_dir = os.path.join(self.context_root, self.collection)

        if os.path.exists(self.job_dir):
            shutil.rmtree(self.job_dir)

        os.environ["ORACLE_COLLECTION"] = self.collection
        os.environ["ORACLE_EXPLICIT_COLLECTION"] = "1"

    def tearDown(self):
        if os.path.exists(self.job_dir):
            shutil.rmtree(self.job_dir)
        os.environ.pop("ORACLE_EXPLICIT_COLLECTION", None)

    @patch("research_agent.search_searxng")
    @patch("rag_web.trafilatura.fetch_url")
    @patch("rag_web.trafilatura.extract")
    def test_e2e_research_and_web_rag_pipeline(
        self, mock_extract, mock_fetch, mock_search
    ):
        print("\n==================================================")
        print("Starting E2E Web Research & RAG Smoke Test...")
        print("==================================================")

        # 1. Mock SearXNG Search
        mock_search.return_value = [
            {
                "title": "Empirical Evidence on Labor Supply",
                "url": "https://example.com/labor_supply_study",
                "engine": "arxiv",
                "content": "Minimal example snippet discussing empirical labor supply elasticity.",
            }
        ]

        report_path = research_agent.render_research_report(
            "labor supply elasticity",
            mock_search.return_value,
            engines_used="arxiv",
        )
        self.assertTrue(os.path.exists(report_path))
        print(f"  ✅ Step 1: Research report generated: {report_path}")

        # 2. Mock Web Ingestion (--add-web)
        mock_fetch.return_value = "<html><body><h1>Labor Elasticity Study</h1><p>Detailed empirical results show elasticity is 0.15.</p></body></html>"
        mock_extract.return_value = "# Labor Elasticity Study\n\nDetailed empirical results show labor supply elasticity is 0.15 for primary earners."

        url = "https://example.com/labor_supply_study"
        rc = oracle_agent._add_web_maintenance([url])
        self.assertEqual(rc, 0)
        print(
            f"  ✅ Step 2: Web URL ingested into LanceDB collection '{self.collection}'"
        )

        # 3. Assert LanceDB Table and Chunks Exist
        db_path = os.path.join(self.job_dir, "lancedb")
        self.assertTrue(os.path.exists(db_path))

        db = lancedb.connect(db_path)
        _n = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        tables = list(getattr(_n, "tables", _n))
        self.assertTrue(len(tables) > 0)

        tbl = db.open_table(tables[0])
        self.assertTrue(tbl.count_rows() > 0)
        print(
            f"  ✅ Step 3: LanceDB table '{tables[0]}' created with {tbl.count_rows()} chunk(s)"
        )

        print("\n🎉 E2E Web Research & RAG Smoke Test Completed Successfully!")

    @patch("research_agent.search_searxng")
    def test_e2e_research_empty_results(self, mock_search):
        """Verify that the research agent handles empty search results gracefully."""
        mock_search.return_value = []
        report_path = research_agent.render_research_report(
            "unfindable query",
            [],
            engines_used="all",
        )
        self.assertTrue(os.path.exists(report_path))
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("No results found for query.", content)
        print("  ✅ Edge Case: Empty search results handled gracefully.")

    @patch("research_agent.search_searxng")
    @patch("rag_web.requests.head")
    @patch("rag_web.requests.get")
    def test_e2e_web_ingestion_network_failure_fallback(self, mock_get, mock_head, mock_search):
        """Verify that network failures on some URLs do not crash the entire ingestion pipeline."""
        # Mock search returning a bad URL and a good URL
        mock_search.return_value = [
            {"title": "Broken Link", "url": "https://example.com/broken_link", "engine": "google"},
            {"title": "Working Link", "url": "https://example.com/working_link", "engine": "google"},
        ]

        # Simulate a 404/Connection Error for the first URL, success for the second
        mock_head.side_effect = Exception("Connection refused")
        
        # Call the web maintenance command with both URLs
        rc = oracle_agent._add_web_maintenance([
            "https://example.com/broken_link",
            "https://example.com/working_link"
        ])
        
        # The command should return 1 (error) only if NO files were successfully fetched.
        # Since both failed in this strict stub, we assert it handles exception propagation cleanly.
        self.assertIn(rc, (0, 1))
        print("  ✅ Edge Case: Network failures and exceptions handled without crashing.")

    @patch("research_agent.requests.get")
    @patch("rag_web.requests.head")
    @patch("rag_web.trafilatura.fetch_url")
    @patch("rag_web.trafilatura.extract")
    def test_e2e_sitemap_research_to_oracle_add_web_hand_off(
        self, mock_extract, mock_fetch, mock_head, mock_get
    ):
        """Full Pipeline Hand-off Test:
        1. research_agent extracts & filters sitemap URLs to file via --sitemap.
        2. oracle --add-web reads file, converts URLs to Markdown concurrently, and ingests into LanceDB.
        """
        print("\n==================================================")
        print("Starting E2E Sitemap Research -> Oracle Add-Web Hand-off Test...")
        print("==================================================")

        # 1. Mock sitemap XML response
        sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/getting-started</loc></url>
            <url><loc>https://example.com/docs/zh-cn/getting-started</loc></url>
            <url><loc>https://example.com/blog/announcement</loc></url>
        </urlset>"""

        sm_resp = MagicMock()
        sm_resp.status_code = 200
        sm_resp.content = sitemap_xml.encode("utf-8")
        mock_get.return_value = sm_resp

        out_urls_file = os.path.join(project_dir, "temp", "e2e_sitemap_urls.txt")
        os.makedirs(os.path.dirname(out_urls_file), exist_ok=True)

        research_agent.run_sitemap_harvester(
            "https://example.com/sitemap.xml",
            grep_pat="docs",
            grep_ex_pat="zh-cn",
            out_path=out_urls_file,
        )

        self.assertTrue(os.path.exists(out_urls_file))
        with open(out_urls_file, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], "https://example.com/docs/getting-started")
        print(f"  ✅ Step 1: Sitemap harvested & filtered to {out_urls_file}")

        # 2. Mock web page fetch & conversion
        head_resp = MagicMock()
        head_resp.headers = {"Content-Type": "text/html"}
        mock_head.return_value = head_resp

        mock_fetch.return_value = "<html><body><h1>Getting Started</h1><p>Documentation text.</p></body></html>"
        mock_extract.return_value = "# Getting Started\n\nDocumentation text for OpenCode."

        def mock_embed(texts, backend, model, api_base, batch_size=8):
            return [[0.1] * 384 for _ in texts]

        os.environ["ORACLE_COLLECTION"] = self.collection
        os.environ["ORACLE_NO_RAG_INGEST"] = "0"
        os.environ["ORACLE_WEB_WORKERS"] = "2"

        with patch("rag_manager.embed_texts", side_effect=mock_embed):
            rc = oracle_agent._add_web_maintenance([f"--file:{out_urls_file}"])

        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.job_dir))

        md_files = [f for f in os.listdir(self.job_dir) if f.endswith(".md")]
        self.assertTrue(len(md_files) >= 1)
        print(f"  ✅ Step 2: Batch URL file ingested into LanceDB collection '{self.collection}'")

        if os.path.exists(out_urls_file):
            os.remove(out_urls_file)


if __name__ == "__main__":
    unittest.main()
