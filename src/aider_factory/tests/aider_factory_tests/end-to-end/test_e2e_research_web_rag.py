#!/usr/bin/env python3
# test_e2e_research_web_rag.py — End-to-End Golden Smoke Test for Web Research & Ingestion.

import os
import shutil
import sys
import unittest
from unittest.mock import patch

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "../../../python"))
project_dir = os.getcwd()

import lancedb
import oracle_agent
import research_agent


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

    def tearDown(self):
        if os.path.exists(self.job_dir):
            shutil.rmtree(self.job_dir)

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


if __name__ == "__main__":
    unittest.main()
