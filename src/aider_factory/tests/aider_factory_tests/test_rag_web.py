#!/usr/bin/env python3
# test_rag_web.py — Unit tests for web content fetching & conversion.

import os
import shutil
import sys
import unittest
from unittest.mock import patch

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "../../python"))

import rag_web


class TestRagWeb(unittest.TestCase):
    def setUp(self):
        self.temp_dir = os.path.join(script_dir, "../../temp/test_rag_web_job")
        os.makedirs(self.temp_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch("rag_web.requests.head")
    @patch("rag_web.requests.get")
    def test_pdf_download(self, mock_get, mock_head):
        mock_head.return_value.headers = {"Content-Type": "application/pdf"}
        mock_get.return_value.status_code = 200
        mock_get.return_value.iter_content = lambda chunk_size: [
            b"%PDF-1.4 mock pdf binary content"
        ]

        url = "https://example.com/research_paper.pdf"
        saved_path, ctype = rag_web.fetch_and_convert_url(url, self.temp_dir)

        self.assertEqual(ctype, "pdf")
        self.assertIsNotNone(saved_path)
        self.assertTrue(saved_path.endswith(".pdf"))
        self.assertTrue(os.path.exists(saved_path))

    @patch("rag_web.requests.head")
    @patch("rag_web.trafilatura.extract")
    @patch("rag_web.trafilatura.fetch_url")
    @patch("rag_web.requests.get")
    def test_html_trafilatura_extraction(
        self, mock_get, mock_fetch, mock_extract, mock_head
    ):
        mock_head.return_value.headers = {"Content-Type": "text/html"}
        mock_get.return_value.status_code = 404
        mock_fetch.return_value = (
            "<html><body><h1>Test Page</h1><p>Main content text...</p></body></html>"
        )
        mock_extract.return_value = (
            "# Test Page\n\nMain content text exceeding two hundred characters to satisfy "
            "the minimum length threshold required by trafilatura extraction check. "
            "Adding additional text here to make sure it easily exceeds two hundred characters total."
        )

        url = "https://example.com/article"
        saved_path, ctype = rag_web.fetch_and_convert_url(url, self.temp_dir)

        self.assertEqual(ctype, "text_doc")
        self.assertIsNotNone(saved_path)
        self.assertTrue(saved_path.endswith(".md"))
        self.assertTrue(os.path.exists(saved_path))
        with open(saved_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("# Test Page", content)


if __name__ == "__main__":
    unittest.main()
