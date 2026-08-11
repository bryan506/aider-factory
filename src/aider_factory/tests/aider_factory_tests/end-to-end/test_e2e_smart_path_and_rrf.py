import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Ensure the python directory is in the path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../python")))
import oracle_agent
import validator

class TestE2ESmartPathAndRRF(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        os.environ.pop("ORACLE_COLLECTION", None)
        os.environ.pop("ORACLE_RAG_DB_DIR", None)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)
        os.environ.pop("ORACLE_COLLECTION", None)
        os.environ.pop("ORACLE_RAG_DB_DIR", None)

    def test_e2e_oracle_global_path_and_retrieval(self):
        """End-to-end test for oracle global path parsing and RRF fusion triggering."""
        # 1. Test global path overrides in oracle
        global_path = os.path.join(self.temp_dir, "my_global_collection")
        args = ["--collection", global_path]
        oracle_agent._extract_overrides(args)

        self.assertEqual(os.environ.get("ORACLE_COLLECTION"), "my_global_collection")
        expected_db = os.path.abspath(os.path.normpath(os.path.join(global_path, "lancedb")))
        self.assertEqual(os.environ.get("ORACLE_RAG_DB_DIR"), expected_db)

    @patch("rag_manager.embed_texts")
    @patch("lancedb.connect")
    def test_e2e_validator_rrf_region_check(self, mock_connect, mock_embed):
        """End-to-end test for validator region check multi-table RRF fusion."""
        mock_embed.return_value = [[0.1, 0.2, 0.3]]
        
        mock_db = MagicMock()
        mock_connect.return_value = mock_db
        mock_db.list_tables.return_value = ["coll_repo_code", "coll_repo_docs"]
        mock_db.table_names.return_value = ["coll_repo_code", "coll_repo_docs"]
        
        mock_tbl_code = MagicMock()
        mock_tbl_docs = MagicMock()
        
        def open_table_side_effect(name):
            if name == "coll_repo_code": return mock_tbl_code
            if name == "coll_repo_docs": return mock_tbl_docs
            raise ValueError("Unknown table")
            
        mock_db.open_table.side_effect = open_table_side_effect
        
        mock_tbl_code.search().metric().limit().to_list.return_value = [
            {"source_file": "src/main.py", "text": "code snippet", "_distance": 0.1}
        ]
        mock_tbl_docs.search().metric().limit().to_list.return_value = [
            {"source_file": "docs/readme.md", "text": "doc snippet", "_distance": 0.2}
        ]

        sim, chunks = validator._region("query block", self.temp_dir, "coll", 5)
        
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0][0], "src/main.py")
        self.assertEqual(chunks[1][0], "docs/readme.md")
        self.assertAlmostEqual(sim, 0.9)
