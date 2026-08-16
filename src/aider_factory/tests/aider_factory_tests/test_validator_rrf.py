import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure the python directory is in the path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../python")))
import validator

class TestValidatorRRF(unittest.TestCase):
    def test_rrf_merge_logic(self):
        """Test that the RRF math correctly boosts chunks found in multiple tables."""
        list1 = [{"source_file": "a.md", "text": "chunk A", "_distance": 0.1}]
        list2 = [
            {"source_file": "b.md", "text": "chunk B", "_distance": 0.2}, 
            {"source_file": "a.md", "text": "chunk A", "_distance": 0.15}
        ]
        
        # chunk A is in both lists, so RRF should rank it higher than chunk B
        merged = validator._rrf_merge([list1, list2], k=2)
        
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["source_file"], "a.md")
        self.assertEqual(merged[1]["source_file"], "b.md")

    @patch("rag_manager.embed_texts")
    @patch("lancedb.connect")
    def test_region_multi_table_fusion(self, mock_connect, mock_embed):
        """Test that _region queries all matching tables and fuses them."""
        # Mock the embedding model returning a dummy vector
        mock_embed.return_value = [[0.1, 0.2, 0.3]]
        
        # Mock LanceDB connection and table listing
        mock_db = MagicMock()
        mock_connect.return_value = mock_db
        mock_db.list_tables.return_value = ["my_coll_docs", "my_coll_code", "unrelated_table"]
        mock_db.table_names.return_value = ["my_coll_docs", "my_coll_code", "unrelated_table"]
        
        # Mock the individual tables
        mock_table_docs = MagicMock()
        mock_table_code = MagicMock()
        
        def open_table_side_effect(name):
            if name == "my_coll_docs": return mock_table_docs
            if name == "my_coll_code": return mock_table_code
            raise ValueError("Wrong table")
            
        mock_db.open_table.side_effect = open_table_side_effect
        
        # Mock the search chains: table.search().metric().limit().to_list()
        mock_table_docs.search().metric().limit().to_list.return_value = [
            {"source_file": "doc.md", "text": "doc text", "_distance": 0.2}
        ]
        mock_table_code.search().metric().limit().to_list.return_value = [
            {"source_file": "code.py", "text": "code text", "_distance": 0.3}
        ]
        
        # Execute the region check
        with patch("os.path.isdir", return_value=True):
            sim, chunks = validator._region("test block", "/fake/db", "my_coll", 5)
        
        # Assert it opened both matching tables and ignored the unrelated one
        self.assertEqual(mock_db.open_table.call_count, 2)
        mock_db.open_table.assert_any_call("my_coll_docs")
        mock_db.open_table.assert_any_call("my_coll_code")
        
        # Assert RRF merged the chunks from both tables
        self.assertEqual(len(chunks), 2)
        
        # Assert the similarity score is derived from the top-ranked chunk (1.0 - 0.2 = 0.8)
        self.assertAlmostEqual(sim, 0.8)


if __name__ == "__main__":
    unittest.main()
