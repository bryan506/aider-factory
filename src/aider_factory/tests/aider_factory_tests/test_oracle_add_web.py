#!/usr/bin/env python3
# test_oracle_add_web.py — Unit tests for oracle --add-web CLI parsing.

import os
import sys
import unittest

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

import oracle_agent


class TestOracleAddWebCLI(unittest.TestCase):
    def test_add_web_parsing(self):
        args = [
            "--add-web",
            "https://example.com/paper.pdf",
            "https://example.com/article.html",
        ]
        out, do_list, did_clear, action, target = oracle_agent._extract_overrides(args)

        self.assertEqual(action, "add-web")
        self.assertEqual(
            target,
            ["https://example.com/paper.pdf", "https://example.com/article.html"],
        )

    def test_resolve_file_path_utility(self):
        # 1. Tilde expansion
        resolved_home = oracle_agent._resolve_file_path("~/test.txt")
        self.assertTrue(resolved_home.startswith(os.path.expanduser("~")))
        self.assertFalse("~" in resolved_home)

        # 2. Relative path resolution
        resolved_rel = oracle_agent._resolve_file_path("rel/test.txt", "/base/dir")
        self.assertEqual(resolved_rel, os.path.normpath("/base/dir/rel/test.txt"))

        # 3. Absolute path preservation
        resolved_abs = oracle_agent._resolve_file_path("/tmp/test.txt")
        self.assertEqual(resolved_abs, os.path.normpath("/tmp/test.txt"))

    def test_add_web_file_expansion(self):
        import shutil
        import tempfile
        from unittest.mock import patch

        temp_dir = tempfile.mkdtemp()
        try:
            urls_file = os.path.join(temp_dir, "test_urls.txt")
            with open(urls_file, "w", encoding="utf-8") as f:
                f.write("# Sample URLs file\n")
                f.write("https://example.com/page1.html\n")
                f.write("\n")
                f.write("  https://example.com/page2.html  \n")

            with patch("rag_web.fetch_and_convert_url") as mock_fetch, patch("rag_manager.ingest") as mock_ingest:
                mock_fetch.return_value = ("/fake/path.md", "text_doc")
                mock_ingest.return_value = True

                rc = oracle_agent._add_web_maintenance([f"--file:{urls_file}"])
                self.assertEqual(rc, 0)
                self.assertEqual(mock_fetch.call_count, 2)
                fetched_urls = [call[0][0] for call in mock_fetch.call_args_list]
                self.assertEqual(
                    fetched_urls,
                    ["https://example.com/page1.html", "https://example.com/page2.html"],
                )
        finally:
            shutil.rmtree(temp_dir)

    def test_add_web_ignores_inherited_doc_collection(self):
        import shutil
        import tempfile
        from unittest.mock import patch

        temp_dir = tempfile.mkdtemp()
        try:
            urls_file = os.path.join(temp_dir, "test_urls.txt")
            with open(urls_file, "w", encoding="utf-8") as f:
                f.write("https://example.com/inherited_test.html\n")

            # Simulate batch: false task environment variable inheritance
            os.environ["ORACLE_COLLECTION"] = "response_template"
            os.environ.pop("ORACLE_EXPLICIT_COLLECTION", None)

            with patch("rag_web.fetch_and_convert_url") as mock_fetch, patch("rag_manager.ingest") as mock_ingest:
                mock_fetch.return_value = ("/fake/path.md", "text_doc")
                mock_ingest.return_value = True

                rc = oracle_agent._add_web_maintenance([f"--file:{urls_file}"])
                self.assertEqual(rc, 0)
                # Verify that the collection resolved to the base collection from config, NOT "response_template"
                resolved_coll = os.environ.get("ORACLE_COLLECTION")
                self.assertNotEqual(resolved_coll, "response_template")
                self.assertEqual(mock_ingest.call_args[1]["collection_name"], resolved_coll)
        finally:
            os.environ.pop("ORACLE_COLLECTION", None)
            os.environ.pop("ORACLE_EXPLICIT_COLLECTION", None)
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    unittest.main()
