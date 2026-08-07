import os
import sys
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
