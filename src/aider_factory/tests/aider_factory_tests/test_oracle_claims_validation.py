import os
import sys
import unittest
from unittest.mock import patch

# Ensure the python directory is in the path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../python")))
import oracle_agent

class TestOracleClaimsValidation(unittest.TestCase):
    def setUp(self):
        # Clear env vars before each test
        os.environ.pop("ORACLE_CLAIMS_ONLY", None)
        os.environ.pop("ORACLE_NO_PRINT", None)

    def tearDown(self):
        # Clean up env vars after each test
        os.environ.pop("ORACLE_CLAIMS_ONLY", None)
        os.environ.pop("ORACLE_NO_PRINT", None)

    def test_extract_overrides_flags(self):
        """Test that --claims-only and --no-print are parsed and set in os.environ."""
        args = ["--claims-only", "--no-print", "Summarize the findings"]
        out, do_list, did_clear, maint_act, maint_tgt = oracle_agent._extract_overrides(args)
        
        # The flags should be consumed, leaving only the query
        self.assertEqual(out, ["Summarize the findings"])
        self.assertEqual(os.environ.get("ORACLE_CLAIMS_ONLY"), "1")
        self.assertEqual(os.environ.get("ORACLE_NO_PRINT"), "1")

    @patch("validator._run_claims_only")
    def test_validate_oracle_response_active(self, mock_run):
        """Test that the validator is called with a temp file when the flag is active."""
        os.environ["ORACLE_CLAIMS_ONLY"] = "1"
        os.environ["ORACLE_NO_PRINT"] = "1"
        mock_run.return_value = 0
        
        test_response = "The Oracle says this is true."
        
        # We patch os.remove to verify cleanup without actually deleting it before we can read it
        with patch("os.remove") as mock_remove:
            oracle_agent._validate_oracle_response(test_response)
            
            # Verify validator was called
            self.assertTrue(mock_run.called)
            
            # Inspect the arguments passed to validator._run_claims_only
            val_args = mock_run.call_args[0][0]
            self.assertTrue(val_args.claims_only)
            self.assertTrue(val_args.no_print)
            
            # Verify the temp file was created and contains the Oracle's response
            self.assertTrue(os.path.exists(val_args.file))
            with open(val_args.file, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), test_response)
                
            # Verify cleanup was called on the temp file
            mock_remove.assert_called_once_with(val_args.file)

    @patch("validator._run_claims_only")
    def test_validate_oracle_response_inactive(self, mock_run):
        """Test that the validator is skipped if the flag is not set."""
        # ORACLE_CLAIMS_ONLY is not set
        oracle_agent._validate_oracle_response("This should be ignored.")
        
        # Validator should not be called
        self.assertFalse(mock_run.called)
