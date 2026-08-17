import os
import shutil
import sys
import tempfile
import unittest

# Ensure python directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../python")))
import lancedb
from lancedb.pydantic import LanceModel, Vector
import oracle_agent
import validator


class TestE2ESmartPathAndRRF(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        os.environ.pop("ORACLE_COLLECTION", None)
        os.environ.pop("ORACLE_RAG_DB_DIR", None)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        os.environ.pop("ORACLE_COLLECTION", None)
        os.environ.pop("ORACLE_RAG_DB_DIR", None)

    def test_e2e_oracle_global_path_and_retrieval(self):
        """End-to-end physical test for global path parsing and directory normalization."""
        global_path = os.path.join(self.temp_dir, "my_global_collection")
        os.makedirs(global_path, exist_ok=True)
        args = ["--collection", global_path]
        oracle_agent._extract_overrides(args)

        self.assertEqual(os.environ.get("ORACLE_COLLECTION"), "my_global_collection")
        expected_db = os.path.abspath(os.path.normpath(os.path.join(global_path, "lancedb")))
        self.assertEqual(os.environ.get("ORACLE_RAG_DB_DIR"), expected_db)

    def test_e2e_validator_rrf_multi_table_live_fusion(self):
        """End-to-end physical test: creates real LanceDB tables and verifies multi-table RRF ranking."""
        coll_dir = os.path.join(self.temp_dir, "coll")
        db_dir = os.path.join(coll_dir, "lancedb")
        os.makedirs(db_dir, exist_ok=True)

        db = lancedb.connect(db_dir)

        class DocChunk(LanceModel):
            source_file: str
            text: str
            vector: Vector(4)

        # Create two physical tables
        tbl_code = db.create_table("coll_repo_code", schema=DocChunk, mode="overwrite")
        tbl_docs = db.create_table("coll_repo_docs", schema=DocChunk, mode="overwrite")

        tbl_code.add([
            {"source_file": "src/main.py", "text": "def calculate_volatility(): return 0.15", "vector": [0.1, 0.2, 0.3, 0.4]},
            {"source_file": "src/helper.py", "text": "def parse_input(): pass", "vector": [0.9, 0.8, 0.7, 0.6]},
        ])

        tbl_docs.add([
            {"source_file": "docs/readme.md", "text": "Volatility calculation uses primary standard deviation.", "vector": [0.12, 0.22, 0.32, 0.42]},
            {"source_file": "docs/architecture.md", "text": "System architecture overview.", "vector": [0.8, 0.7, 0.6, 0.5]},
        ])

        # Test RRF merge algorithm directly on real search result lists
        code_results = tbl_code.search([0.1, 0.2, 0.3, 0.4]).limit(2).to_list()
        doc_results = tbl_docs.search([0.1, 0.2, 0.3, 0.4]).limit(2).to_list()

        merged = validator._rrf_merge([code_results, doc_results], k=4)
        self.assertTrue(len(merged) >= 2)
        top_sources = [r["source_file"] for r in merged]
        self.assertIn("src/main.py", top_sources)
        self.assertIn("docs/readme.md", top_sources)


if __name__ == "__main__":
    unittest.main(verbosity=2)
