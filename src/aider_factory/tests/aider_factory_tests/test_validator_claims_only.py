import os
import sys
import io
import contextlib
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Ensure the python directory is in the path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../python")))
import validator

class TestValidatorClaimsOnly(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.temp_dir, "agent_response.md")
        self.report_path = os.path.join(self.temp_dir, "report.md")
        
        # Create a mock markdown file with headers, code blocks, and paragraphs
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(
                "# Main Header\n\n"
                "This is the first paragraph.\n"
                "It has two lines.\n\n"
                "```python\n"
                "def foo():\n"
                "    pass\n"
                "```\n\n"
                "## Subheader\n\n"
                "This is the second paragraph.\n"
            )
            
        self.args = MagicMock()
        self.args.file = self.file_path
        self.args.report = self.report_path
        self.args.no_print = True
        self.args.claims_only = True

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    @patch("validator._verify")
    def test_paragraph_extraction_and_all_pass(self, mock_verify):
        # Mock _verify to always return a passing score (0.9 > 0.6)
        mock_verify.return_value = ("cosine", 0.9, [], 0.6)
        
        result = validator._run_claims_only(self.args)
        
        self.assertEqual(result, 0)
        # Should only be called twice (Para 1 and Para 2). Headers and code blocks are ignored.
        self.assertEqual(mock_verify.call_count, 2)
        
        calls = mock_verify.call_args_list
        self.assertEqual(calls[0][0][0], "This is the first paragraph.\nIt has two lines.")
        self.assertEqual(calls[1][0][0], "This is the second paragraph.")

    @patch("validator._verify")
    def test_claims_only_with_failures(self, mock_verify):
        # Mock _verify to fail on the second paragraph
        def side_effect(block, a):
            if "first paragraph" in block:
                return ("cosine", 0.9, [("src1.md", "chunk1")], 0.6)
            else:
                return ("entail", 0.2, [("src2.md", "chunk2")], 0.5)
        mock_verify.side_effect = side_effect
        
        result = validator._run_claims_only(self.args)
        
        # Should return 1 (failure)
        self.assertEqual(result, 1)
        self.assertTrue(os.path.exists(self.report_path))
        
        with open(self.report_path, "r", encoding="utf-8") as f:
            report_content = f.read()
            
        self.assertIn("1 unsupported claims found", report_content)
        self.assertIn("## Paragraph 2", report_content)
        self.assertIn("0.20 (LOW, entail)", report_content)
        self.assertIn("[source: src2.md]", report_content)
        self.assertNotIn("Paragraph 1", report_content)

    @patch("validator._verify")
    def test_claims_only_print_behavior_on_failure(self, mock_verify):
        """Test that the full report prints to stdout on failure, unless --no-print is set."""
        # Force a failure
        mock_verify.return_value = ("cosine", 0.2, [("src.md", "chunk")], 0.6)
        
        # 1. Test WITHOUT --no-print (Should print report to stdout)
        self.args.no_print = False
        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            validator._run_claims_only(self.args)
        
        stdout_text = captured_stdout.getvalue()
        self.assertIn("2 unsupported claims found", stdout_text)
        self.assertIn("## Paragraph 1", stdout_text)
        self.assertIn("## Paragraph 2", stdout_text)
        
        # 2. Test WITH --no-print (Should keep stdout empty)
        self.args.no_print = True
        captured_stdout_empty = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout_empty):
            validator._run_claims_only(self.args)
            
        self.assertEqual(captured_stdout_empty.getvalue().strip(), "")

    @patch("sys.argv", ["validator.py", "--file", "dummy.md", "--claims-only", "--no-print"])
    @patch("validator._run_claims_only")
    def test_cli_auto_assigns_report_path(self, mock_run):
        mock_run.return_value = 0
        with patch("os.path.isfile", return_value=True):
            validator.main()
        
        # Check that the report path was auto-generated correctly
        args = mock_run.call_args[0][0]
        self.assertTrue(args.claims_only)
        self.assertTrue(args.report.endswith("dummy_claims_report.md"))
        self.assertIn(".aider_factory", args.report)

    @patch("litellm.completion")
    def test_grounding_cloud_model_bypasses_dummy_api_key(self, mock_completion):
        """Verify _entail() omits dummy api_key for cloud models when grounding_api_base is unset."""
        mock_completion.return_value = {
            "choices": [{"message": {"content": "SUPPORTED"}}],
            "usage": {}
        }

        class MockArgs:
            grounding_model = "gemini/gemini-2.5-flash"
            grounding_api_base = None
            grounding_api_key = "sk-dummy"
            entail_threshold = 0.5

        chunks = [("doc.md", "Evidence text passage")]
        score = validator._entail("A specific claim", chunks, MockArgs())

        self.assertEqual(score, 1.0)
        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args[1]
        self.assertNotEqual(kwargs.get("api_key"), "sk-dummy", "Dummy grounding key 'sk-dummy' must not be forwarded to cloud models!")

    @patch("validator._run_claims_only")
    def test_validator_yaml_auto_discovery(self, mock_run_claims):
        """Verify validator.main auto-discovers claims_only: true and custom db from .env.yml."""
        import yaml
        mock_run_claims.return_value = 0

        cfg = {
            "phases": [
                {
                    "enabled": True,
                    "rag": {
                        "collection_name": "auto_collection",
                        "db": "custom_rag_db",
                    },
                    "validation": {
                        "claims_only": True,
                    },
                }
            ]
        }
        env_yml_path = os.path.join(self.temp_dir, ".env.yml")
        with open(env_yml_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        orig_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        try:
            with patch("sys.argv", ["validator.py", "--file", self.file_path, "--no-print"]):
                validator.main()

            mock_run_claims.assert_called_once()
            args = mock_run_claims.call_args[0][0]
            self.assertTrue(args.claims_only, "claims_only should be True when configured in YAML")
            self.assertEqual(args.collection, "auto_collection")
            self.assertTrue(args.db.replace("\\", "/").endswith("/custom_rag_db"))
        finally:
            os.chdir(orig_cwd)


if __name__ == "__main__":
    unittest.main()
