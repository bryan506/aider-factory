#!/usr/bin/env python3
"""Tests for oracle _retrieve() prefix-match fallback in batch=true mode.

Verifies that when ORACLE_COLLECTION is a collection name (not a literal table),
_retrieve() prefix-matches all tables starting with {collection}_ and fuses them
via RRF. Also verifies the exact-match path (batch=false / literary review) is
unchanged, and that --type filtering works with prefix-matched tables.
"""
import os
import sys
import shutil

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

from oracle_agent import _retrieve

base_dir = "temp/mock_rag_batch"
shutil.rmtree(base_dir, ignore_errors=True)
os.makedirs(base_dir, exist_ok=True)
os.environ["ORACLE_RAG_DB_DIR"] = base_dir

def mock_embed(texts, backend, model, api_base, batch_size=64):
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

# Simulate batch=true table naming: {collection}_{repo}_{type}
db.create_table("MyProject_RepoA_code", schema=MChunk).add([
    {"text": "RepoA code result", "vector": [0.1]*1024, "source_file": "repoA/main.py",
     "source_type": "code", "line_start": 1, "line_end": 20}
])
db.create_table("MyProject_RepoA_docs", schema=MChunk).add([
    {"text": "RepoA docs result", "vector": [0.1]*1024, "source_file": "repoA/README.md",
     "source_type": "doc", "line_start": 0, "line_end": 0}
])
db.create_table("MyProject_RepoB_code", schema=MChunk).add([
    {"text": "RepoB code result", "vector": [0.1]*1024, "source_file": "repoB/lib.py",
     "source_type": "code", "line_start": 10, "line_end": 30}
])
db.create_table("MyProject_docs", schema=MChunk).add([
    {"text": "OCR docs result", "vector": [0.1]*1024, "source_file": "paper.pdf",
     "source_type": "doc", "line_start": 0, "line_end": 0}
])
# A table that does NOT belong to this collection (should never appear).
db.create_table("OtherProject_code", schema=MChunk).add([
    {"text": "Other project code", "vector": [0.1]*1024, "source_file": "other.py",
     "source_type": "code", "line_start": 0, "line_end": 0}
])
# Simulate batch=false: a table whose name IS the collection (exact match).
db.create_table("SinglePaperTable", schema=MChunk).add([
    {"text": "Single paper content", "vector": [0.1]*1024, "source_file": "paper.md",
     "source_type": "doc", "line_start": 0, "line_end": 0}
])


def test_prefix_match_fuses_all_tables():
    """batch=true: bare collection name prefix-matches all {collection}_* tables."""
    os.environ["ORACLE_COLLECTION"] = "MyProject"
    os.environ["ORACLE_TYPE_FILTER"] = ""
    res = _retrieve("query", 10)
    assert "RepoA code result" in res, "RepoA code missing from prefix-matched results"
    assert "RepoA docs result" in res, "RepoA docs missing from prefix-matched results"
    assert "RepoB code result" in res, "RepoB code missing from prefix-matched results"
    assert "OCR docs result" in res, "OCR docs missing from prefix-matched results"
    assert "Other project code" not in res, "OtherProject leaked into prefix-matched results"
    print("  [PASS] prefix-match fuses all {collection}_* tables via RRF")


def test_prefix_match_type_filter_code():
    """batch=true + --type code: prefix-match narrowed to _code tables only."""
    os.environ["ORACLE_COLLECTION"] = "MyProject"
    os.environ["ORACLE_TYPE_FILTER"] = "code"
    res = _retrieve("query", 10)
    assert "RepoA code result" in res, "RepoA code missing"
    assert "RepoB code result" in res, "RepoB code missing"
    assert "RepoA docs result" not in res, "Docs leaked through code filter"
    assert "OCR docs result" not in res, "OCR docs leaked through code filter"
    print("  [PASS] prefix-match + type_filter=code narrows to _code tables")


def test_prefix_match_type_filter_docs():
    """batch=true + --type docs: prefix-match narrowed to _docs tables only."""
    os.environ["ORACLE_COLLECTION"] = "MyProject"
    os.environ["ORACLE_TYPE_FILTER"] = "docs"
    res = _retrieve("query", 10)
    assert "RepoA docs result" in res, "RepoA docs missing"
    assert "OCR docs result" in res, "OCR docs missing"
    assert "RepoA code result" not in res, "Code leaked through docs filter"
    assert "RepoB code result" not in res, "Code leaked through docs filter"
    print("  [PASS] prefix-match + type_filter=docs narrows to _docs tables")


def test_exact_match_unchanged():
    """batch=false: collection name IS a literal table -> exact match (no prefix scan)."""
    os.environ["ORACLE_COLLECTION"] = "SinglePaperTable"
    os.environ["ORACLE_TYPE_FILTER"] = ""
    res = _retrieve("query", 10)
    assert "Single paper content" in res, "Exact-match table content missing"
    assert "RepoA" not in res, "Prefix-match tables leaked into exact-match"
    assert "Other project" not in res, "Other tables leaked into exact-match"
    print("  [PASS] exact-match path (batch=false) returns only the named table")


def test_wildcard_unchanged():
    """ORACLE_COLLECTION='*' fuses ALL tables (unchanged behavior)."""
    os.environ["ORACLE_COLLECTION"] = "*"
    os.environ["ORACLE_TYPE_FILTER"] = ""
    res = _retrieve("query", 20)
    assert "RepoA code result" in res
    assert "RepoB code result" in res
    assert "OCR docs result" in res
    assert "Single paper content" in res
    assert "Other project code" in res  # wildcard includes everything
    print("  [PASS] wildcard '*' fuses ALL tables (unchanged)")


def test_no_matching_prefix_returns_empty():
    """Collection name with no matching tables returns empty string."""
    os.environ["ORACLE_COLLECTION"] = "NonexistentProject"
    os.environ["ORACLE_TYPE_FILTER"] = ""
    res = _retrieve("query", 10)
    assert res == "", f"Expected empty string, got: {res!r}"
    print("  [PASS] non-matching collection name returns empty (no silent failure)")


if __name__ == "__main__":
    print("Starting Oracle Batch Retrieve Tests...")
    test_prefix_match_fuses_all_tables()
    test_prefix_match_type_filter_code()
    test_prefix_match_type_filter_docs()
    test_exact_match_unchanged()
    test_wildcard_unchanged()
    test_no_matching_prefix_returns_empty()
    print("All Oracle Batch Retrieve Tests Passed!")
    shutil.rmtree(base_dir)
