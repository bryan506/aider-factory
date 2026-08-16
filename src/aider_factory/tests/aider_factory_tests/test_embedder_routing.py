#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../python"))
from rag_manager import embed_texts

print("Starting Embedder Routing Tests...\n")

from unittest.mock import patch, MagicMock

def test_embed_texts_openai_routing():
    """Verify openai backend routes direct HTTP to api_base/embeddings."""
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"embedding": [0.1] * 4096}]
        }
        mock_post.return_value = mock_resp

        vecs = embed_texts(
            texts=["test query"],
            backend="openai",
            model="qwen3-embedding-8b-8k:LATEST",
            api_base="http://192.168.100.1:8080/v1",
        )
        assert len(vecs) == 1
        assert len(vecs[0]) == 4096
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url == "http://192.168.100.1:8080/v1/embeddings"
        print("  ✅ OpenAI backend correctly routes to {api_base}/embeddings.")

def test_embed_texts_unknown():
    try:
        embed_texts(["test"], "invalid-backend", "model", None)
        print("  ❌ Failed: should have raised ValueError for invalid backend.")
    except ValueError:
        print("  ✅ Invalid backend correctly raises ValueError.")

if __name__ == "__main__":
    test_embed_texts_openai_routing()
    test_embed_texts_unknown()
    print("\n🎉 Embedder Routing Tests Complete!")
