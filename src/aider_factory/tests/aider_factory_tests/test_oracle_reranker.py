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
        oracle_agent._RERANKER_LOCAL_INSTANCE = None

    def tearDown(self):
        oracle_agent._RERANKER_LOCAL_INSTANCE = None
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
        os.environ["ORACLE_RANKING_API_BASE"] = "http://localhost:8080/v1"

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
        self.assertEqual(mock_post.call_args_list[0][0][0], "http://localhost:8080/v1/rerank")
        self.assertEqual(mock_post.call_args_list[1][0][0], "http://localhost:8080/rerank")

    @patch("requests.post")
    def test_rerank_chunks_remote_non_200_error_diagnostic(self, mock_post):
        os.environ["ORACLE_RANKING_MODEL"] = "test-model"
        os.environ["ORACLE_RANKING_API_BASE"] = "http://localhost:8080/v1"

        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.text = '{"error": "Unknown model"}'
        mock_post.return_value = resp_400

        candidates = [
            {"text": "Chunk 1"},
            {"text": "Chunk 2"},
        ]

        reranked = oracle_agent._rerank_chunks("test query", candidates, top_n=2)
        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["text"], "Chunk 1")
        self.assertEqual(reranked[1]["text"], "Chunk 2")

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

    @patch("sentence_transformers.CrossEncoder")
    def test_rerank_chunks_in_process_failure_fallback(self, mock_encoder_cls):
        mock_encoder_cls.side_effect = RuntimeError("CUDA out of memory")

        os.environ["ORACLE_RANKING_MODEL"] = "jinaai/jina-reranker-v3.5"
        os.environ.pop("ORACLE_RANKING_API_BASE", None)

        candidates = [{"text": "Chunk 1"}, {"text": "Chunk 2"}]
        reranked = oracle_agent._rerank_chunks("query text", candidates, top_n=2)

        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["text"], "Chunk 1")
        self.assertEqual(reranked[1]["text"], "Chunk 2")

    @patch("sentence_transformers.CrossEncoder")
    def test_rerank_chunks_in_process_chat_template_recovery(self, mock_encoder_cls):
        mock_tokenizer = MagicMock()
        mock_tokenizer.chat_template = "{% for msg in messages %}{{ msg['content'] }}{% endfor %}"

        mock_instance = MagicMock()
        mock_instance.tokenizer = mock_tokenizer
        mock_instance.predict.side_effect = [
            ValueError("The chat template of model cannot carry a 'query'/'document' pair"),
            [0.1, 0.9],
        ]
        mock_encoder_cls.return_value = mock_instance

        os.environ["ORACLE_RANKING_MODEL"] = "jinaai/jina-reranker-v3.5"
        os.environ.pop("ORACLE_RANKING_API_BASE", None)

        candidates = [{"text": "Doc A"}, {"text": "Doc B"}]
        reranked = oracle_agent._rerank_chunks("query", candidates, top_n=2)

        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["text"], "Doc B")
        self.assertEqual(reranked[0]["_relevance_score"], 0.9)
        self.assertIn("selectattr", str(mock_tokenizer.chat_template))

    @patch("sentence_transformers.CrossEncoder")
    def test_rerank_chunks_in_process_pad_token_recovery(self, mock_encoder_cls):
        mock_tokenizer = MagicMock()
        mock_tokenizer.pad_token = None
        mock_tokenizer.eos_token = "<|im_end|>"
        mock_tokenizer.chat_template = None

        mock_instance = MagicMock()
        mock_instance.tokenizer = mock_tokenizer
        mock_instance.predict.side_effect = [
            ValueError("Cannot handle batch sizes > 1 if no padding token is defined."),
            [0.2, 0.8],
        ]
        mock_encoder_cls.return_value = mock_instance

        os.environ["ORACLE_RANKING_MODEL"] = "jinaai/jina-reranker-v3.5"
        os.environ.pop("ORACLE_RANKING_API_BASE", None)

        candidates = [{"text": "Doc 1"}, {"text": "Doc 2"}]
        reranked = oracle_agent._rerank_chunks("query", candidates, top_n=2)

        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["text"], "Doc 2")
        self.assertEqual(mock_tokenizer.pad_token, "<|im_end|>")

    @patch("sentence_transformers.CrossEncoder")
    def test_rerank_chunks_in_process_2d_logits_handling(self, mock_encoder_cls):
        mock_instance = MagicMock()
        mock_instance.tokenizer = None
        # 2D logits: [negative_class_logit, positive_class_logit]
        # Chunk 1 is irrelevant ([0.9, 0.1]), Chunk 2 is relevant ([0.05, 0.95])
        mock_instance.predict.return_value = [[0.9, 0.1], [0.05, 0.95]]
        mock_encoder_cls.return_value = mock_instance

        os.environ["ORACLE_RANKING_MODEL"] = "jinaai/jina-reranker-v3.5"
        os.environ.pop("ORACLE_RANKING_API_BASE", None)

        candidates = [{"text": "Irrelevant chunk"}, {"text": "Highly relevant chunk"}]
        reranked = oracle_agent._rerank_chunks("query", candidates, top_n=2)

        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["text"], "Highly relevant chunk")
        self.assertEqual(reranked[0]["_relevance_score"], 0.95)
        self.assertEqual(reranked[1]["text"], "Irrelevant chunk")
        self.assertEqual(reranked[1]["_relevance_score"], 0.1)

    def test_rrf_merge_deterministic_tie_breaking(self):
        list1 = [{"source_file": "b.md", "text": "Content B"}]
        list2 = [{"source_file": "a.md", "text": "Content A"}]

        # Both have rank 0 in their respective tables (tied RRF scores)
        # Permutation 1: [list1, list2]
        res1 = oracle_agent._rrf_merge([list1, list2], k=2)
        # Permutation 2: [list2, list1]
        res2 = oracle_agent._rrf_merge([list2, list1], k=2)

        # Must yield identical deterministic ordering: a.md before b.md
        self.assertEqual(res1[0]["source_file"], "a.md")
        self.assertEqual(res2[0]["source_file"], "a.md")
        self.assertEqual(res1[1]["source_file"], "b.md")
        self.assertEqual(res2[1]["source_file"], "b.md")

    @patch("rag_manager.embed_texts")
    @patch("lancedb.connect")
    def test_dynamic_recall_scaling_multi_table(self, mock_connect, mock_embed):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_db:
            os.environ["ORACLE_RAG_DB_DIR"] = tmp_db
            os.environ["ORACLE_COLLECTION"] = "*"
            os.environ.pop("ORACLE_RECALL_K", None)

            mock_embed.return_value = [[0.1, 0.2]]
            mock_table = MagicMock()
            mock_search = MagicMock()
            mock_table.search.return_value = mock_search
            mock_search.limit.return_value = mock_search
            mock_search.to_list.return_value = []

            # 10 tables -> len(tables) * 4 = 40 (> 30)
            table_list = [f"doc_{i}" for i in range(10)]
            mock_db = MagicMock()
            mock_db.list_tables.return_value = table_list
            mock_db.open_table.return_value = mock_table
            mock_connect.return_value = mock_db

            oracle_agent._retrieve("query text", k=5)

            mock_search.limit.assert_called_with(40)

    @patch("lancedb.connect")
    def test_remove_file_calls_optimize(self, mock_connect):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_db:
            os.environ["ORACLE_RAG_DB_DIR"] = tmp_db
            os.environ["ORACLE_COLLECTION"] = "test_coll"

            mock_tbl = MagicMock()
            mock_tbl.schema.names = ["source_file", "text"]
            mock_tbl.count_rows.side_effect = [10, 5]

            mock_db = MagicMock()
            mock_db.list_tables.return_value = ["test_coll_docs"]
            mock_db.open_table.return_value = mock_tbl
            mock_connect.return_value = mock_db

            res = oracle_agent._remove_file("target.md")

            self.assertEqual(res, 0)
            mock_tbl.delete.assert_called_once()
            mock_tbl.optimize.assert_called_once()

    @patch("sentence_transformers.CrossEncoder")
    def test_cross_encoder_offline_first_loading(self, mock_encoder_cls):
        mock_instance = MagicMock()
        mock_instance.predict.return_value = [0.9, 0.1]
        mock_encoder_cls.return_value = mock_instance

        os.environ["ORACLE_RANKING_MODEL"] = "jinaai/jina-reranker-v3.5"
        os.environ.pop("ORACLE_RANKING_API_BASE", None)

        candidates = [{"text": "Doc text 1"}, {"text": "Doc text 2"}]
        oracle_agent._rerank_chunks("query", candidates, top_n=1)

        mock_encoder_cls.assert_called_once_with(
            "jinaai/jina-reranker-v3.5", trust_remote_code=True, local_files_only=True
        )


if __name__ == "__main__":
    unittest.main()
