import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

# Ensure the python directory is in the path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../python")))
import oracle_agent
import validator

class TestSmartPathResolution(unittest.TestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.mkdtemp()
        os.chdir(self.temp_dir)
        os.environ.pop("ORACLE_COLLECTION", None)
        os.environ.pop("ORACLE_RAG_DB_DIR", None)

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir)
        os.environ.pop("ORACLE_COLLECTION", None)
        os.environ.pop("ORACLE_RAG_DB_DIR", None)

    def test_oracle_global_path_resolution(self):
        """Test that Oracle extracts the collection name and DB path from a global path."""
        args = ["--collection", "/global/path/my_collection"]
        oracle_agent._extract_overrides(args)
        
        self.assertEqual(os.environ.get("ORACLE_COLLECTION"), "my_collection")
        expected_db = os.path.abspath(os.path.normpath("/global/path/my_collection/lancedb"))
        self.assertEqual(os.environ.get("ORACLE_RAG_DB_DIR"), expected_db)

    def test_oracle_local_path_resolution(self):
        """Test that Oracle builds the local DB path when given just a name."""
        args = ["--collection", "local_coll"]
        oracle_agent._extract_overrides(args)
        
        self.assertEqual(os.environ.get("ORACLE_COLLECTION"), "local_coll")
        expected_db = os.path.join(os.getcwd(), ".aider_factory", "markdown", "lanceDB", "local_coll", "lancedb")
        self.assertEqual(os.environ.get("ORACLE_RAG_DB_DIR"), expected_db)

    @patch("validator._run_claims_only")
    def test_validator_global_path_resolution(self, mock_run):
        """Test that Validator extracts the collection name and DB path from a global path."""
        mock_run.return_value = 0
        
        # Create dummy file so os.path.isfile passes
        with open("dummy.md", "w") as f:
            f.write("test")
            
        test_args = ["validator.py", "--file", "dummy.md", "--claims-only", "--collection", "/global/path/val_coll"]
        
        with patch.object(sys, 'argv', test_args):
            validator.main()
        
        val_args = mock_run.call_args[0][0]
        self.assertEqual(val_args.collection, "val_coll")
        expected_db = os.path.abspath(os.path.normpath("/global/path/val_coll/lancedb"))
        self.assertEqual(val_args.db, expected_db)

    @patch("validator._run_claims_only")
    def test_validator_yaml_auto_discovery(self, mock_run):
        """Test that Validator auto-discovers the collection and DB from .env.yml when omitted."""
        mock_run.return_value = 0
        
        # Create dummy file
        with open("dummy.md", "w") as f:
            f.write("test")
            
        # Create fake .env.yml
        os.makedirs(".aider_factory", exist_ok=True)
        with open(".aider_factory/.env.yml", "w") as f:
            f.write("phases:\n  - enabled: true\n    rag:\n      collection_name: 'yaml_coll'\n")
            
        # Create the expected DB directory so os.path.isdir passes
        expected_db = os.path.join(os.getcwd(), ".aider_factory", "markdown", "lanceDB", "yaml_coll", "lancedb")
        os.makedirs(expected_db, exist_ok=True)
            
        test_args = ["validator.py", "--file", "dummy.md", "--claims-only"]
        
        with patch.object(sys, 'argv', test_args):
            validator.main()
        
        val_args = mock_run.call_args[0][0]
        self.assertEqual(val_args.collection, "yaml_coll")
        expected_db = os.path.join(os.getcwd(), ".aider_factory", "markdown", "lanceDB", "yaml_coll", "lancedb")
        self.assertEqual(val_args.db, expected_db)
