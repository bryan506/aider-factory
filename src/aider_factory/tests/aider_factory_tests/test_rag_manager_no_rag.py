import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch

# Ensure the python directory is in the path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../python")))
import rag_manager

class TestRagManagerNoRag(unittest.TestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.mkdtemp()
        os.chdir(self.temp_dir)

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir)

    @patch("rag_manager.embed_texts")
    @patch("lancedb.connect")
    def test_ingest_ocr_only_bypasses_lancedb(self, mock_connect, mock_embed):
        """Test that passing ocr_only=True bypasses LanceDB insertion and embedding."""
        
        # Create a real dummy markdown file so _collection_sources finds it
        coll_dir = os.path.join(self.temp_dir, "test_coll")
        os.makedirs(coll_dir, exist_ok=True)
        with open(os.path.join(coll_dir, "dummy.md"), "w") as f:
            f.write("# Dummy Content\nThis is a test.")
            
        # Run ingest with ocr_only=True
        rag_manager.ingest(
            context_root=self.temp_dir,
            collection_name="test_coll",
            embed_model="dummy",
            ocr_only=True,
            batch=False
        )
        
        # embed_texts should NEVER be called because pending.extend is skipped
        mock_embed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
