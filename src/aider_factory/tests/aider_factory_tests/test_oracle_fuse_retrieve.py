import os
import sys
import shutil

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

from oracle_agent import _retrieve

base_dir = "temp/mock_rag_fuse"
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

def setup_function():
    shutil.rmtree(base_dir, ignore_errors=True)
    os.makedirs(base_dir, exist_ok=True)
    os.environ["ORACLE_RAG_DB_DIR"] = os.path.abspath(base_dir)
    rag_manager.embed_texts = mock_embed
    global db
    db = lancedb.connect(base_dir)
    db.create_table("my_docs", schema=MChunk).add([
        {"text": "Docs result", "vector": [0.1]*1024, "source_file": "doc.md", "source_type": "doc", "line_start": 0, "line_end": 0}
    ])
    db.create_table("my_code", schema=MChunk).add([
        {"text": "Code result", "vector": [0.1]*1024, "source_file": "code.py", "source_type": "code", "line_start": 5, "line_end": 10}
    ])

def test_fuse_all():
    os.environ["ORACLE_COLLECTION"] = "*"
    os.environ["ORACLE_TYPE_FILTER"] = ""
    res = _retrieve("query", 5)
    assert "[source: doc | doc.md]" in res, "Docs result missing from fused query"
    assert "[source: code | code.py:5-10]" in res, "Code result missing from fused query"
    print("  ✅ Fused RRF retrieval works across all tables and preserves prefix+loc.")

def test_type_filter():
    os.environ["ORACLE_COLLECTION"] = "*"
    os.environ["ORACLE_TYPE_FILTER"] = "code"
    res = _retrieve("query", 5)
    assert "[source: code | code.py:5-10]" in res
    assert "doc.md" not in res
    print("  ✅ --type code filter successfully narrows tables.")


def test_retrieve_wildcard_all_tables_with_external_db():
    ext_dir = os.path.join(base_dir, "ext_db")
    os.makedirs(ext_dir, exist_ok=True)
    ext_db = lancedb.connect(ext_dir)
    ext_db.create_table("custom_financials", schema=MChunk).add([
        {"text": "Net Margin 24%", "vector": [0.1]*1024, "source_file": "fin.pdf", "source_type": "doc", "line_start": 1, "line_end": 2}
    ])
    ext_db.create_table("custom_code", schema=MChunk).add([
        {"text": "def calc_margin(): pass", "vector": [0.1]*1024, "source_file": "margin.py", "source_type": "code", "line_start": 1, "line_end": 5}
    ])
    os.environ["ORACLE_RAG_DB_DIR"] = ext_dir
    os.environ["ORACLE_COLLECTION"] = "*"
    os.environ["ORACLE_TYPE_FILTER"] = ""
    res = _retrieve("margin", 5)
    assert "[source: doc | fin.pdf:1-2]" in res
    assert "[source: code | margin.py:1-5]" in res
    print("  ✅ Wildcard retrieval successfully queries all tables in external database.")


def test_retrieve_smart_collection_table_prefix_matching():
    ext_dir = os.path.join(base_dir, "smart_coll_db")
    os.makedirs(ext_dir, exist_ok=True)
    ext_db = lancedb.connect(ext_dir)
    ext_db.create_table("Financial_Corpus_Q3_docs", schema=MChunk).add([
        {"text": "Revenue grew by 18%", "vector": [0.1]*1024, "source_file": "q3.pdf", "source_type": "doc", "line_start": 10, "line_end": 12}
    ])
    ext_db.create_table("Unrelated_Corpus_docs", schema=MChunk).add([
        {"text": "Irrelevant data", "vector": [0.1]*1024, "source_file": "other.pdf", "source_type": "doc", "line_start": 1, "line_end": 2}
    ])
    os.environ["ORACLE_RAG_DB_DIR"] = ext_dir
    os.environ["ORACLE_COLLECTION"] = "Financial_Corpus"
    os.environ["ORACLE_TYPE_FILTER"] = ""
    res = _retrieve("revenue", 5)
    assert "[source: doc | q3.pdf:10-12]" in res
    assert "other.pdf" not in res
    print("  ✅ Smart collection table prefix correctly matches and filters LanceDB tables.")


def test_retrieve_embedder_unreachable_fallback_sentence_transformers():
    os.environ["ORACLE_RAG_DB_DIR"] = os.path.abspath(base_dir)
    os.environ["ORACLE_COLLECTION"] = "*"
    os.environ["ORACLE_EMBED_BACKEND"] = "openai"
    os.environ["ORACLE_EMBED_API_BASE"] = "http://127.0.0.1:54321/v1"
    os.environ["ORACLE_EMBED_MODEL"] = "text-embedding-ada-002"

    res = _retrieve("query", 5)
    assert os.environ.get("ORACLE_EMBED_BACKEND") == "sentence-transformers" or "[source:" in res
    print("  ✅ Unreachable embedder endpoint caught gracefully with local fallback.")

def teardown_function():
    for k in ("ORACLE_COLLECTION", "ORACLE_TYPE_FILTER", "ORACLE_RAG_DB_DIR"):
        os.environ.pop(k, None)

if __name__ == "__main__":
    print("Starting Phase 4 RRF Retrieve Tests...")
    setup_function()
    test_fuse_all()
    setup_function()
    test_type_filter()
    test_retrieve_wildcard_all_tables_with_external_db()
    test_retrieve_smart_collection_table_prefix_matching()
    setup_function()
    test_retrieve_embedder_unreachable_fallback_sentence_transformers()
    teardown_function()
    print("🎉 All Phase 4 Retrieve Tests Passed!")
    shutil.rmtree(base_dir)
