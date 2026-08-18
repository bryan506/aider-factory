import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure package python directory is on sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
python_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
if python_dir not in sys.path:
    sys.path.insert(0, python_dir)

import oracle_agent
import validator


class TestOracleReranker(unittest.TestCase):
    def setUp(self):
        self.old_env = dict(os.environ)
        os.environ.pop("ORACLE_NO_RERANK", None)
        os.environ.pop("ORACLE_RANKING_MODEL", None)
        os.environ.pop("ORACLE_RANKING_API_BASE", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)

    @patch("requests.post")
    def test_rerank_chunks_remote_v1_rerank(self, mock_post):
        os.environ["ORACLE_RANKING_MODEL"] = "bge-reranker-large"
        os.environ["ORACLE_RANKING_API_BASE"] = "http://localhost:8080"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.12},
                {"index": 1, "relevance_score": 0.98},
            ]
        }
        mock_post.return_value = mock_resp

        candidates = [
            {"text": "Low relevance chunk", "_distance": 0.05},
            {"text": "Highly relevant chunk", "_distance": 0.80},
        ]

        reranked = oracle_agent._rerank_chunks("test query", candidates, top_n=2)

        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["text"], "Highly relevant chunk")
        self.assertEqual(reranked[0]["_relevance_score"], 0.98)
        self.assertEqual(reranked[1]["text"], "Low relevance chunk")

        mock_post.assert_called_once()
        self.assertIn("/v1/rerank", mock_post.call_args[0][0])

    @patch("requests.post")
    def test_rerank_chunks_remote_404_fallback(self, mock_post):
        os.environ["ORACLE_RANKING_MODEL"] = "bge-reranker-large"
        os.environ["ORACLE_RANKING_API_BASE"] = "http://localhost:8080"

        resp_404 = MagicMock()
        resp_404.status_code = 404

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = [
            {"index": 0, "score": 0.3},
            {"index": 1, "score": 0.9},
        ]

        mock_post.side_effect = [resp_404, resp_200]

        candidates = [
            {"text": "Chunk A"},
            {"text": "Chunk B"},
        ]

        reranked = oracle_agent._rerank_chunks("test query", candidates, top_n=2)

        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["text"], "Chunk B")
        self.assertEqual(mock_post.call_count, 2)
        self.assertIn("/rerank", mock_post.call_args_list[1][0][0])

    @patch("requests.post")
    def test_rerank_chunks_remote_error_fallback(self, mock_post):
        import requests

        os.environ["ORACLE_RANKING_MODEL"] = "bge-reranker-large"
        os.environ["ORACLE_RANKING_API_BASE"] = "http://localhost:8080"

        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")

        candidates = [
            {"text": "First chunk"},
            {"text": "Second chunk"},
        ]

        reranked = oracle_agent._rerank_chunks("test query", candidates, top_n=2)

        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["text"], "First chunk")
        self.assertEqual(reranked[1]["text"], "Second chunk")

    @patch("requests.post")
    def test_rerank_chunks_bypass_flag(self, mock_post):
        os.environ["ORACLE_NO_RERANK"] = "1"
        os.environ["ORACLE_RANKING_MODEL"] = "bge-reranker-large"
        os.environ["ORACLE_RANKING_API_BASE"] = "http://localhost:8080"

        candidates = [
            {"text": "Chunk 1"},
            {"text": "Chunk 2"},
            {"text": "Chunk 3"},
        ]

        reranked = oracle_agent._rerank_chunks("test query", candidates, top_n=2)

        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["text"], "Chunk 1")
        mock_post.assert_not_called()

    @patch("requests.post")
    @patch("rag_manager.embed_texts")
    @patch("lancedb.connect")
    def test_retrieve_two_stage_integration(self, mock_connect, mock_embed, mock_post):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_db:
            os.environ["ORACLE_RAG_DB_DIR"] = tmp_db
            os.environ["ORACLE_COLLECTION"] = "test_table"
            os.environ["ORACLE_RANKING_MODEL"] = "bge-reranker-large"
            os.environ["ORACLE_RANKING_API_BASE"] = "http://localhost:8080"
            os.environ["ORACLE_RECALL_K"] = "10"

            mock_embed.return_value = [[0.1, 0.2, 0.3]]

            mock_table = MagicMock()
            mock_search = MagicMock()
            mock_table.search.return_value = mock_search
            mock_search.limit.return_value = mock_search

            fake_chunks = [
                {"text": f"Chunk {i}", "source_file": "doc.md", "line_start": i, "line_end": i + 5}
                for i in range(10)
            ]
            mock_search.to_list.return_value = fake_chunks

            mock_db = MagicMock()
            mock_db.list_tables.return_value = ["test_table"]
            mock_db.open_table.return_value = mock_table
            mock_connect.return_value = mock_db

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "results": [
                    {"index": 8, "relevance_score": 0.99},
                    {"index": 2, "relevance_score": 0.85},
                    {"index": 0, "relevance_score": 0.50},
                ]
            }
            mock_post.return_value = mock_resp

            result = oracle_agent._retrieve("query text", k=3)

            mock_search.limit.assert_called_with(10)

            self.assertIn("Chunk 8", result)
            self.assertIn("Chunk 2", result)
            self.assertIn("Chunk 0", result)

    @patch("requests.post")
    def test_rerank_chunks_url_normalization(self, mock_post):
        os.environ["ORACLE_RANKING_MODEL"] = "bge-reranker-large"
        os.environ["ORACLE_RANKING_API_BASE"] = "http://localhost:8080/v1"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.85},
                {"index": 1, "relevance_score": 0.40},
            ]
        }
        mock_post.return_value = mock_resp

        candidates = [
            {"text": "Sample text 1", "_distance": 0.1},
            {"text": "Sample text 2", "_distance": 0.2},
        ]
        oracle_agent._rerank_chunks("test query", candidates, top_n=1)

        mock_post.assert_called_once()
        called_url = mock_post.call_args[0][0]
        self.assertEqual(called_url, "http://localhost:8080/v1/rerank")
        self.assertNotIn("/v1/v1/", called_url)

    @patch("oracle_agent._rerank_chunks")
    @patch("rag_manager.embed_texts")
    @patch("lancedb.connect")
    def test_validator_region_uses_relevance_score(self, mock_connect, mock_embed, mock_rerank):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_db:
            mock_embed.return_value = [[0.1, 0.2]]
            mock_table = MagicMock()
            mock_search = MagicMock()
            mock_table.search.return_value = mock_search
            mock_search.metric.return_value = mock_search
            mock_search.limit.return_value = mock_search
            mock_search.to_list.return_value = [
                {"text": "Relevant chunk", "source_file": "doc.md", "_distance": 0.80}
            ]

            mock_db = MagicMock()
            mock_db.list_tables.return_value = ["test_coll"]
            mock_db.open_table.return_value = mock_table
            mock_connect.return_value = mock_db

            mock_rerank.return_value = [
                {"text": "Relevant chunk", "source_file": "doc.md", "_distance": 0.80, "_relevance_score": 0.95}
            ]

            sim, chunks = validator._region("test block", tmp_db, "test_coll", k=1)

            self.assertEqual(sim, 0.95)
            self.assertNotEqual(sim, 0.20)


if __name__ == "__main__":
    unittest.main()
