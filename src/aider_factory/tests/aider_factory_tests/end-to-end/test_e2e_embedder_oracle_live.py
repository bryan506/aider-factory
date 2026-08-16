#!/usr/bin/env python3
"""End-to-End test verifying live embedder endpoint -> LanceDB -> Oracle _retrieve()."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../python")))
import lancedb
import oracle_agent
import rag_manager


class TestE2ELiveEmbedderOracle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.collection = "e2e_live_embed_test"
        self.job_dir = os.path.join(self.temp_dir, self.collection)
        os.makedirs(self.job_dir, exist_ok=True)

        # Test document
        self.doc_path = os.path.join(self.job_dir, "treasury_sample.md")
        with open(self.doc_path, "w", encoding="utf-8") as f:
            f.write(
                "# Financial Analysis\n\n"
                "The borrowing limit was raised to $41.1 trillion under the Big Beautiful Bill Act.\n\n"
                "The gross federal debt stood at $37.6 trillion equal to 124% of GDP.\n"
            )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_live_node1_embedder_ingest_and_oracle_retrieval(self):
        """Test live ingestion & retrieval using Node 1 (http://192.168.100.1:8080/v1)."""
        api_base = "http://192.168.100.1:8080/v1"
        model = "qwen3-embedding-8b-8k-gpu:LATEST"

        try:
            import requests
            requests.get(f"{api_base}/models", timeout=5).raise_for_status()
        except Exception:
            self.skipTest(f"Live embedding endpoint at {api_base} is offline.")

        collection = "node1_test"
        job_dir = os.path.join(self.temp_dir, collection)
        os.makedirs(job_dir, exist_ok=True)
        doc_path = os.path.join(job_dir, "treasury_sample.md")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(
                "# Node 1 Financial Analysis\n\n"
                "The borrowing limit was raised to $41.1 trillion under the Big Beautiful Bill Act.\n\n"
                "The gross federal debt stood at $37.6 trillion equal to 124% of GDP.\n"
            )

        success = rag_manager.ingest(
            context_root=self.temp_dir,
            collection_name=collection,
            embed_model=model,
            embed_backend="openai",
            embed_api_base=api_base,
            batch=True,
            overwrite=True,
        )
        self.assertTrue(success, "Live Node 1 embedding ingestion failed.")

        os.environ["ORACLE_COLLECTION"] = collection
        os.environ["ORACLE_RAG_DB_DIR"] = os.path.join(job_dir, "lancedb")
        os.environ["ORACLE_EMBED_MODEL"] = model
        os.environ["ORACLE_EMBED_BACKEND"] = "openai"
        os.environ["ORACLE_EMBED_API_BASE"] = api_base
        os.environ["ORACLE_RETRIEVE_MODE"] = "top_k"
        os.environ["ORACLE_TYPE_FILTER"] = ""

        query = "What was the gross federal debt amount?"
        context = oracle_agent._retrieve(query, k=3)

        print("\n" + "="*60)
        print("VERBATIM RETRIEVED CHUNK (Node 1):")
        print("="*60)
        print(context)
        print("="*60)

        self.assertTrue(bool(context), "Oracle retrieved 0 chunks from Node 1!")
        self.assertIn("37.6 trillion", context)
        self.assertIn("[source: doc | treasury_sample.md]", context)

    def test_live_router_embedder_ingest_and_oracle_retrieval(self):
        """Test live ingestion & retrieval using Router (http://192.168.100.2:8081/v1)."""
        api_base = "http://192.168.100.2:8081/v1"
        model = "qwen3-embedding-8b-8k:LATEST"

        try:
            import requests
            requests.get(f"{api_base}/models", timeout=5).raise_for_status()
        except Exception:
            self.skipTest(f"Live embedding endpoint at {api_base} is offline.")

        collection = "router_test"
        job_dir = os.path.join(self.temp_dir, collection)
        os.makedirs(job_dir, exist_ok=True)
        doc_path = os.path.join(job_dir, "macro_sample.md")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(
                "# Router Macro Report\n\n"
                "In January 2026, the US Dollar Index rose by 1.4% following robust labor data.\n\n"
                "Private-sector employers added an average of 43,000 jobs per month since June.\n"
            )

        success = rag_manager.ingest(
            context_root=self.temp_dir,
            collection_name=collection,
            embed_model=model,
            embed_backend="openai",
            embed_api_base=api_base,
            batch=True,
            overwrite=True,
        )
        self.assertTrue(success, "Live Router embedding ingestion failed.")

        os.environ["ORACLE_COLLECTION"] = collection
        os.environ["ORACLE_RAG_DB_DIR"] = os.path.join(job_dir, "lancedb")
        os.environ["ORACLE_EMBED_MODEL"] = model
        os.environ["ORACLE_EMBED_BACKEND"] = "openai"
        os.environ["ORACLE_EMBED_API_BASE"] = api_base
        os.environ["ORACLE_RETRIEVE_MODE"] = "top_k"
        os.environ["ORACLE_TYPE_FILTER"] = ""

        query = "How many jobs were added per month?"
        context = oracle_agent._retrieve(query, k=3)

        print("\n" + "="*60)
        print("VERBATIM RETRIEVED CHUNK (Router):")
        print("="*60)
        print(context)
        print("="*60)

        self.assertTrue(bool(context), "Oracle retrieved 0 chunks from Router!")
        self.assertIn("43,000 jobs", context)
        self.assertIn("[source: doc | macro_sample.md]", context)


if __name__ == "__main__":
    unittest.main()
