#!/usr/bin/env python3
# test_e2e_research_web_rag.py — Comprehensive unit & integration tests
# for research_agent sitemap harvester, rag_web concurrent batching, and oracle --add-web.

import os
import re
import sys
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Mock trafilatura in sys.modules before importing package modules
sys.modules["trafilatura"] = MagicMock()

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
if python_module_dir not in sys.path:
    sys.path.insert(0, python_module_dir)

import research_agent
import rag_web
import oracle_agent


class TestSitemapHarvester(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch("research_agent.requests.get")
    def test_sitemap_xml_parsing_and_nested_recursion(self, mock_get):
        """Verify sitemap harvester recursively parses nested sitemapindex XML files."""
        parent_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sitemap-docs.xml</loc></sitemap>
        </sitemapindex>"""

        child_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/intro</loc></url>
            <url><loc>https://example.com/docs/api</loc></url>
            <url><loc>https://example.com/blog/news</loc></url>
        </urlset>"""

        def mock_get_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "sitemap-docs.xml" in url:
                resp.content = child_xml.encode("utf-8")
            else:
                resp.content = parent_xml.encode("utf-8")
            return resp

        mock_get.side_effect = mock_get_side_effect

        out_file = os.path.join(self.temp_dir, "urls.txt")
        result_path = research_agent.run_sitemap_harvester(
            "https://example.com/", depth=2, out_path=out_file
        )

        self.assertEqual(result_path, out_file)
        self.assertTrue(os.path.exists(out_file))

        with open(out_file, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]

        self.assertEqual(len(urls), 3)
        self.assertIn("https://example.com/docs/intro", urls)
        self.assertIn("https://example.com/docs/api", urls)
        self.assertIn("https://example.com/blog/news", urls)

    @patch("research_agent.requests.get")
    def test_sitemap_robots_txt_fallback(self, mock_get):
        """Verify fallback to robots.txt when /sitemap.xml returns 404."""
        sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/setup</loc></url>
        </urlset>"""

        robots_txt = "User-agent: *\nSitemap: https://example.com/custom_sitemap.xml\n"

        def mock_get_side_effect(url, **kwargs):
            resp = MagicMock()
            if url == "https://example.com/sitemap.xml":
                resp.status_code = 404
                resp.content = b""
            elif "robots.txt" in url:
                resp.status_code = 200
                resp.text = robots_txt
                resp.content = robots_txt.encode("utf-8")
            elif "custom_sitemap.xml" in url:
                resp.status_code = 200
                resp.content = sitemap_xml.encode("utf-8")
            else:
                resp.status_code = 404
            return resp

        mock_get.side_effect = mock_get_side_effect

        out_file = os.path.join(self.temp_dir, "robots_urls.txt")
        research_agent.run_sitemap_harvester("https://example.com/", out_path=out_file)

        with open(out_file, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]

        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0], "https://example.com/docs/setup")

    @patch("research_agent.requests.get")
    def test_grep_and_grep_exclude_regex_filtering(self, mock_get):
        """Verify case-insensitive anywhere-matching regex filtering (-i / re.search)."""
        sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/EN/guide</loc></url>
            <url><loc>https://example.com/docs/api</loc></url>
            <url><loc>https://example.com/docs/zh-cn/guide</loc></url>
            <url><loc>https://example.com/blog/news</loc></url>
        </urlset>"""

        resp = MagicMock()
        resp.status_code = 200
        resp.content = sitemap_xml.encode("utf-8")
        mock_get.return_value = resp

        out_file = os.path.join(self.temp_dir, "filtered_urls.txt")
        research_agent.run_sitemap_harvester(
            "https://example.com/sitemap.xml",
            grep_pat="docs",
            grep_ex_pat="zh-cn|ja",
            out_path=out_file,
        )

        with open(out_file, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]

        self.assertEqual(len(urls), 2)
        self.assertIn("https://example.com/docs/EN/guide", urls)
        self.assertIn("https://example.com/docs/api", urls)
        self.assertNotIn("https://example.com/docs/zh-cn/guide", urls)
        self.assertNotIn("https://example.com/blog/news", urls)


class TestRagWebAndConcurrentBatch(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch("rag_web.requests.head")
    @patch("rag_web.requests.get")
    def test_pdf_direct_download(self, mock_get, mock_head):
        """Verify HEAD sniff detects PDF and downloads binary directly."""
        head_resp = MagicMock()
        head_resp.headers = {"Content-Type": "application/pdf"}
        mock_head.return_value = head_resp

        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.iter_content.return_value = [b"%PDF-1.4 dummy content"]
        mock_get.return_value = get_resp

        saved_path, ctype = rag_web.fetch_and_convert_url(
            "https://example.com/paper.pdf", self.temp_dir
        )

        self.assertEqual(ctype, "pdf")
        self.assertTrue(saved_path.endswith(".pdf"))
        self.assertTrue(os.path.exists(saved_path))

    @patch("rag_web.fetch_and_convert_url")
    def test_fetch_urls_batch_concurrent_threadpool_and_exception_isolation(self, mock_convert):
        """Verify concurrent batch processing handles thread errors gracefully without crashing."""
        def mock_convert_side_effect(url, job_dir):
            if "fail" in url:
                raise RuntimeError("Simulated network/rendering crash")
            if "skip" in url:
                return None, None
            out_path = os.path.join(job_dir, "doc.md")
            return out_path, "text_doc"

        mock_convert.side_effect = mock_convert_side_effect

        urls = [
            "https://example.com/page1",
            "https://example.com/page_fail",
            "https://example.com/page_skip",
            "https://example.com/page2",
        ]

        success_count, skipped_count = rag_web.fetch_urls_batch(
            urls, self.temp_dir, workers=4
        )

        self.assertEqual(success_count, 2)
        self.assertEqual(skipped_count, 2)


class TestOracleAddWebCLI(unittest.TestCase):
    def test_add_web_parsing_flags(self):
        """Verify --add-web parsing handles --no-rag, --workers, and --file:<path>."""
        args = [
            "--add-web",
            "--file:temp/urls.txt",
            "--no-rag",
            "--workers",
            "8",
        ]
        out, do_list, did_clear, action, target = oracle_agent._extract_overrides(args)

        self.assertEqual(action, "add-web")
        self.assertEqual(target, ["--file:temp/urls.txt"])
        self.assertEqual(os.environ.get("ORACLE_NO_RAG_INGEST"), "1")
        self.assertEqual(os.environ.get("ORACLE_WEB_WORKERS"), "8")


if __name__ == "__main__":
    unittest.main()
