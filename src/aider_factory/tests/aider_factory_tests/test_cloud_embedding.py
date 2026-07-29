#!/usr/bin/env python3
"""Tests for cloud/local embedding routing in embed_texts().

Covers:
  - Local endpoint path: api_base set -> direct requests.post (unchanged)
  - Cloud model path: api_base empty/None -> litellm.embedding
  - Backward compat: sentence-transformers path unchanged
  - Batch iteration works on both paths
"""
import sys, os, types
sys.path.insert(0, ".aider_factory/python")

from rag_manager import embed_texts


# ---- Test 1: Local endpoint routing (unchanged) ----

def test_local_embedding():
    """When api_base is set, embed_texts posts directly to the endpoint."""
    print("test_local_embedding...")
    captured = {}
    call_count = {"n": 0}

    import requests as _real_requests
    orig_post = _real_requests.post

    def mock_post(url, json=None, headers=None, timeout=None):
        call_count["n"] += 1
        captured["url"] = url
        captured["model"] = json["model"]
        captured["input"] = json["input"]
        resp = types.SimpleNamespace()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}
                                       for _ in json["input"]]}
        return resp

    _real_requests.post = mock_post
    try:
        vecs = embed_texts(["hello", "world"], backend="openai",
                           model="qwen3-embedding", api_base="http://localhost:8080/v1")
        assert len(vecs) == 2
        assert vecs[0] == [0.1, 0.2, 0.3]
        assert captured["url"] == "http://localhost:8080/v1/embeddings"
        assert captured["model"] == "qwen3-embedding"
        print("  OK: local embedding routed to direct HTTP")
    finally:
        _real_requests.post = orig_post


# ---- Test 2: Cloud embedding routing ----

def test_cloud_embedding():
    """When api_base is empty/None, embed_texts uses litellm.embedding."""
    print("test_cloud_embedding...")
    captured = {}

    mock_litellm = types.ModuleType("litellm")
    def mock_embedding(model=None, input=None, **kw):
        captured["model"] = model
        captured["input"] = input
        return {"data": [{"embedding": [0.5, 0.6]} for _ in input]}
    mock_litellm.embedding = mock_embedding

    orig = sys.modules.get("litellm")
    sys.modules["litellm"] = mock_litellm

    try:
        # api_base="" -> cloud
        vecs = embed_texts(["test"], backend="openai",
                           model="gemini/text-embedding-004", api_base="")
        assert len(vecs) == 1
        assert vecs[0] == [0.5, 0.6]
        assert captured["model"] == "gemini/text-embedding-004"
        print("  OK: api_base='' routes to litellm")

        # api_base=None -> cloud
        captured.clear()
        vecs = embed_texts(["test"], backend="openai",
                           model="gemini/text-embedding-004", api_base=None)
        assert len(vecs) == 1
        assert captured["model"] == "gemini/text-embedding-004"
        print("  OK: api_base=None routes to litellm")
    finally:
        if orig is not None:
            sys.modules["litellm"] = orig
        else:
            sys.modules.pop("litellm", None)


# ---- Test 3: Cloud embedding batching ----

def test_cloud_embedding_batching():
    """Cloud path respects batch_size and iterates correctly."""
    print("test_cloud_embedding_batching...")
    call_count = {"n": 0}

    mock_litellm = types.ModuleType("litellm")
    def mock_embedding(model=None, input=None, **kw):
        call_count["n"] += 1
        return {"data": [{"embedding": [float(call_count["n"])]} for _ in input]}
    mock_litellm.embedding = mock_embedding

    orig = sys.modules.get("litellm")
    sys.modules["litellm"] = mock_litellm

    try:
        texts = [f"text_{i}" for i in range(10)]
        vecs = embed_texts(texts, backend="openai",
                           model="gemini/model", api_base="", batch_size=3)
        assert len(vecs) == 10, f"Expected 10 vectors, got {len(vecs)}"
        # batch_size=3, 10 texts -> 4 batches (3+3+3+1)
        assert call_count["n"] == 4, f"Expected 4 batches, got {call_count['n']}"
        print(f"  OK: 10 texts in 4 batches of 3")
    finally:
        if orig is not None:
            sys.modules["litellm"] = orig
        else:
            sys.modules.pop("litellm", None)


# ---- Test 4: Empty input returns [] ----

def test_empty_input():
    """Empty input returns [] without hitting any endpoint."""
    print("test_empty_input...")
    vecs = embed_texts([], backend="openai", model="any", api_base="http://x")
    assert vecs == []
    vecs = embed_texts([], backend="openai", model="any", api_base="")
    assert vecs == []
    print("  OK: empty input returns []")


# ---- Test 5: sentence-transformers path unchanged ----

def test_sentence_transformers_unchanged():
    """sentence-transformers backend still works regardless of api_base."""
    print("test_sentence_transformers_unchanged...")
    # This test uses the real sentence-transformers library (available in aider venv)
    vecs = embed_texts(["test embedding"], backend="sentence-transformers",
                       model="BAAI/bge-m3", api_base="")
    assert len(vecs) == 1
    assert len(vecs[0]) == 1024  # bge-m3 produces 1024-dim
    print(f"  OK: sentence-transformers still works (dim={len(vecs[0])})")


if __name__ == "__main__":
    test_local_embedding()
    test_cloud_embedding()
    test_cloud_embedding_batching()
    test_empty_input()
    test_sentence_transformers_unchanged()
    print("\nAll cloud embedding tests passed.")
