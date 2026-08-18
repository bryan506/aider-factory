#!/usr/bin/env python3
"""Tests that _retrieve() truncates oversized queries before embedding.

In debate mode, the oracle's "question" is the full prompt (system instruction +
code files + architect proposal), easily 30K+ chars. Without truncation,
embed_texts() sends the full text and the server returns 400. Keeping the query
short (~500-800 tokens / 2000 chars) produces a focused embedding vector that
retrieves structurally similar patterns rather than broadly related code.

These tests verify that:
1. Short queries pass through unchanged.
2. Long queries are truncated to _MAX_EMBED_CHARS before embedding.
3. The truncated query still produces valid retrieval results.
4. The prefix is always prepended (not counted against truncation).
"""
import os
import sys
import shutil

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

base_dir = "temp/mock_rag_truncation"
shutil.rmtree(base_dir, ignore_errors=True)
os.makedirs(base_dir, exist_ok=True)
os.environ["ORACLE_RAG_DB_DIR"] = base_dir

# Track what embed_texts receives so we can assert on input length.
_captured_inputs = []

def mock_embed(texts, backend, model, api_base, batch_size=64):
    _captured_inputs.append(texts[0])
    return [[0.1] * 1024 for _ in texts]

import rag_manager
rag_manager.embed_texts = mock_embed
sys.modules["rag_manager"] = rag_manager

import lancedb
db = lancedb.connect(base_dir)

from lancedb.pydantic import LanceModel, Vector
class MChunk(LanceModel):
    text: str
    vector: Vector(1024)
    source_file: str
    source_type: str
    line_start: int = 0
    line_end: int = 0

from oracle_agent import _retrieve

def setup_function():
    shutil.rmtree(base_dir, ignore_errors=True)
    os.makedirs(base_dir, exist_ok=True)
    os.environ["ORACLE_RAG_DB_DIR"] = os.path.abspath(base_dir)
    os.environ["ORACLE_COLLECTION"] = "test_table"
    os.environ["ORACLE_TYPE_FILTER"] = ""
    os.environ["ORACLE_QUERY_PREFIX"] = "Instruct: retrieve\nQuery: "
    _captured_inputs.clear()
    rag_manager.embed_texts = mock_embed
    global db
    db = lancedb.connect(base_dir)
    db.create_table("test_table", schema=MChunk).add([
        {"text": "relevant chunk", "vector": [0.1]*1024, "source_file": "code.py",
         "source_type": "code", "line_start": 1, "line_end": 10}
    ])


def test_short_query_unchanged():
    """A short query (< _MAX_EMBED_CHARS) passes through fully."""
    _captured_inputs.clear()
    short_q = "How does leverage_lq compute the spread?"
    _retrieve(short_q, 5)
    assert len(_captured_inputs) == 1
    captured = _captured_inputs[0]
    prefix = os.environ["ORACLE_QUERY_PREFIX"]
    assert captured == prefix + short_q, f"Short query was modified: {captured!r}"
    print("  [PASS] short query passes through unchanged")


def test_long_query_truncated():
    """A query exceeding _MAX_EMBED_CHARS is truncated before embedding."""
    _captured_inputs.clear()
    # Simulate a debate prompt: 30K chars of code + proposal
    long_q = "Fix the bug in leverage_lq. " + "x" * 30000
    _retrieve(long_q, 5)
    assert len(_captured_inputs) == 1
    captured = _captured_inputs[0]
    prefix = os.environ["ORACLE_QUERY_PREFIX"]
    # The query portion should be truncated to 6000 chars
    assert len(captured) <= len(prefix) + 6000 + 1, (
        f"Query was not truncated: len={len(captured)}"
    )
    # The prefix must be present and intact
    assert captured.startswith(prefix), "Prefix was not prepended"
    # The meaningful start of the query should be preserved
    assert "Fix the bug in leverage_lq." in captured, "Query start was lost"
    print("  [PASS] long query truncated to _MAX_EMBED_CHARS")


def test_truncated_query_still_retrieves():
    """Truncated query still produces valid retrieval results."""
    _captured_inputs.clear()
    long_q = "Find leverage code. " + "y" * 50000
    result = _retrieve(long_q, 5)
    assert "relevant chunk" in result, f"No results from truncated query: {result!r}"
    print("  [PASS] truncated query produces valid retrieval results")


def test_exact_boundary():
    """A query exactly at _MAX_EMBED_CHARS is not modified."""
    _captured_inputs.clear()
    exact_q = "z" * 6000
    _retrieve(exact_q, 5)
    assert len(_captured_inputs) == 1
    captured = _captured_inputs[0]
    prefix = os.environ["ORACLE_QUERY_PREFIX"]
    assert captured == prefix + exact_q, "Boundary query was unexpectedly modified"
    print("  [PASS] query at exact boundary passes through unchanged")


def test_no_prefix_still_truncates():
    """Truncation works when ORACLE_QUERY_PREFIX is empty."""
    _captured_inputs.clear()
    os.environ["ORACLE_QUERY_PREFIX"] = ""
    long_q = "a" * 20000
    _retrieve(long_q, 5)
    assert len(_captured_inputs) == 1
    captured = _captured_inputs[0]
    assert len(captured) <= 6000, f"Query not truncated without prefix: len={len(captured)}"
    os.environ["ORACLE_QUERY_PREFIX"] = "Instruct: retrieve\nQuery: "
    print("  [PASS] truncation works with empty prefix")


if __name__ == "__main__":
    print("Starting Oracle Query Truncation Tests...")
    setup_function()
    test_short_query_unchanged()
    setup_function()
    test_long_query_truncated()
    setup_function()
    test_truncated_query_still_retrieves()
    setup_function()
    test_exact_boundary()
    setup_function()
    test_no_prefix_still_truncates()
    print("All Oracle Query Truncation Tests Passed!")
    shutil.rmtree(base_dir)
