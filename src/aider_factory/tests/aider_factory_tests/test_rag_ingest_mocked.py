import os
import shutil
import sys

sys.path.insert(0, ".aider_factory/python")
import rag_manager

# --- MONKEYPATCH FOR OFFLINE TESTING ---
def mock_rasterize(src_path, out_dir, dpi=150):
    # raw_text is the CER *reference* only (deliberately unlike the OCR output below),
    # so the OCR path must actually run for the PDF to be captured.
    return [("dummy.png", f"reference text layer for {os.path.basename(src_path)}")]

# Spy: count real invocations so the DOC_EXTS bypass regression cannot hide.
_OCR_CALLS = {"n": 0, "paths": []}
def mock_ocr(png_path, model_id, api_base, prompt_text, max_tokens=2048, timeout=300, retries=1):
    _OCR_CALLS["n"] += 1
    _OCR_CALLS["paths"].append(png_path)
    return f"VISION_OCR_OUTPUT::{os.path.basename(png_path)}"

def mock_ast_chunk(source, language, max_chars=2000):
    return [(source, 1, source.count('\n')+1, "mock_symbol")]

rag_manager._rasterize = mock_rasterize
rag_manager._ocr_image = mock_ocr
rag_manager._ast_chunk = mock_ast_chunk
# ---------------------------------------

base_dir = "temp/mock_rag_phase34"
job_dir = os.path.join(base_dir, "test_col")
if os.path.isdir(base_dir):
    shutil.rmtree(base_dir)
os.makedirs(job_dir, exist_ok=True)
repo_dir = os.path.join(job_dir, "myrepo")
os.makedirs(repo_dir, exist_ok=True)

with open(os.path.join(job_dir, "loose.txt"), "w") as f: f.write("Loose text doc")
with open(os.path.join(job_dir, "paper.pdf"), "w") as f: f.write("Mock PDF")
with open(os.path.join(repo_dir, "code.py"), "w") as f: f.write("print('hello')\n")

print("--- Test 1: Full multi-table build ---")
# Force IVF_PQ_MIN_ROWS to 1 so the hook triggers and we verify it doesn't crash ingestion.
rag_manager.IVF_PQ_MIN_ROWS = 1
rag_manager.ingest(context_root=base_dir, collection_name="test_col", embed_model="BAAI/bge-m3",
                   embed_backend="sentence-transformers", ocr_api_base="mock", ocr_agent="mock", batch=True)

import lancedb
db = lancedb.connect(os.path.join(job_dir, "lancedb"))
tables = db.table_names()

print(f"\n✅ Tables created: {tables}")
assert "test_col_docs" in tables, "Top-level docs table missing"
assert "test_col_myrepo_code" in tables, "Repo code table missing"

tbl_docs = db.open_table("test_col_docs")
files_docs = set(tbl_docs.to_arrow()['source_file'].to_pylist())
docs_text = " ".join(tbl_docs.to_arrow()['text'].to_pylist())
print(f"✅ Docs table files: {files_docs}")
assert "paper.md" not in files_docs, "Data loss bug failed! paper.md sidecar was ingested."
assert "loose.txt" in files_docs, ".txt bug failed! standalone txt was dropped."
assert "paper.pdf" in files_docs, "PDF was not ingested into the docs table."

# --- Bug B guard: the PDF MUST go through vision-OCR, not the raw text layer ---
assert _OCR_CALLS["n"] > 0, "REGRESSION: _ocr_image was never called for the PDF (DOC_EXTS bypass?)."
assert "VISION_OCR_OUTPUT::" in docs_text, "REGRESSION: docs table holds raw text layer, not vision-OCR output."
assert "reference text layer" not in docs_text, "REGRESSION: raw PyMuPDF text layer leaked into the DB."
print(f"✅ OCR path exercised: _ocr_image called {_OCR_CALLS['n']}x; vision output stored (bypass fixed).")

tbl_code = db.open_table("test_col_myrepo_code")
code_files = set(tbl_code.to_arrow()['source_file'].to_pylist())
print(f"✅ Code table files: {code_files}")
assert "myrepo/code.py" in code_files, "Code file missing from repo table"

schema_fields = [f.name for f in tbl_code.schema]
assert "source_type" in schema_fields and "language" in schema_fields, "New metadata schema failed!"

print("\n--- Test 2: Incremental Append on Multi-Table ---")
_ocr_before = _OCR_CALLS["n"]
with open(os.path.join(repo_dir, "code2.py"), "w") as f: f.write("print('world')\n")
rag_manager.ingest(context_root=base_dir, collection_name="test_col", embed_model="BAAI/bge-m3",
                   embed_backend="sentence-transformers", ocr_api_base="mock", ocr_agent="mock", batch=True)

code_files_updated = set(db.open_table("test_col_myrepo_code").to_arrow()['source_file'].to_pylist())
print(f"✅ Updated Code table files: {code_files_updated}")
assert "myrepo/code2.py" in code_files_updated
# Incremental: the already-embedded PDF must be skipped -> no new OCR calls this run.
assert _OCR_CALLS["n"] == _ocr_before, "Incremental append re-OCR'd an already-embedded document."
print(f"✅ Incremental append skipped OCR for embedded docs (calls stayed at {_OCR_CALLS['n']}).")

print("\n--- Test 2b: Reuse Existing OCR Markdown Sidecar ---")
_ocr_before_reuse = _OCR_CALLS["n"]
reuse_job_dir = os.path.join(base_dir, "reuse_col")
os.makedirs(reuse_job_dir, exist_ok=True)
with open(os.path.join(reuse_job_dir, "cached.pdf"), "w") as f: f.write("Dummy PDF")
with open(os.path.join(reuse_job_dir, "cached.md"), "w") as f: f.write("# Pre-computed OCR Content")

rag_manager.ingest(context_root=base_dir, collection_name="reuse_col", embed_model="BAAI/bge-m3",
                   embed_backend="sentence-transformers", ocr_api_base="mock", ocr_agent="mock", batch=True)

assert _OCR_CALLS["n"] == _ocr_before_reuse, "Failed: _ocr_image was called despite existing .md sidecar."
print("✅ Existing OCR markdown sidecar successfully reused without re-running vision OCR.")

print("\n--- Test 3: Old-schema guard ---")
import pyarrow as pa

# 1. Setup a fresh collection directory
legacy_job_dir = os.path.join(base_dir, "legacy_col")
os.makedirs(legacy_job_dir, exist_ok=True)
with open(os.path.join(legacy_job_dir, "doc.txt"), "w") as f: 
    f.write("Legacy doc content")

# 2. Pre-create the table with the EXACT name the ingest loop will target ("legacy_col_docs")
legacy_db = lancedb.connect(os.path.join(legacy_job_dir, "lancedb"))
old_schema = pa.schema([
    pa.field("vector", pa.list_(pa.float32(), 1024)),
    pa.field("text", pa.string()),
    pa.field("source_file", pa.string())
])
legacy_db.create_table("legacy_col_docs", schema=old_schema)

# 3. Call ingest without overwrite=True on the new collection
rag_manager.ingest(context_root=base_dir, collection_name="legacy_col", embed_model="BAAI/bge-m3",
                   embed_backend="sentence-transformers", ocr_api_base="mock", ocr_agent="mock", batch=True)

# 4. Assert the table remains untouched because the guard fired
legacy_tbl = legacy_db.open_table("legacy_col_docs")
assert legacy_tbl.count_rows() == 0, "Failed: old-schema guard was bypassed and rows were added."
print("✅ Old-schema guard successfully prevented appends on the target table.")

shutil.rmtree(base_dir)
print("\n🎉 All Phase 3+4 ingest integration tests passed!")
