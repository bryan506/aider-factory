import os
import sys
import shutil

sys.path.insert(0, ".aider_factory/python")
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

if __name__ == "__main__":
    print("Starting Phase 4 RRF Retrieve Tests...")
    test_fuse_all()
    test_type_filter()
    print("🎉 All Phase 4 Retrieve Tests Passed!")
    shutil.rmtree(base_dir)
