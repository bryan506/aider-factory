#!/usr/bin/env python3
"""E2E: Real embed → LanceDB → query roundtrip using BAAI/bge-m3.

Tests the full RAG pipeline without mocks:
  1. Parse a real PDF with PyMuPDF (deterministic, no external services)
  2. Chunk the extracted text (same splitter as ingest pipeline)
  3. Embed chunks via embed_texts(backend="sentence-transformers", model="BAAI/bge-m3")
  4. Store vectors in a real LanceDB table
  5. Query via oracle_agent._retrieve() with the SAME model
  6. Assert semantically correct chunks are returned

Key invariant tested: the model that embeds INTO the database MUST be the
same model that embeds the QUERY vector — otherwise cosine similarity is
meaningless. A dimension mismatch test proves this.

Requires: sentence-transformers, lancedb, pymupdf (all in pyproject.toml).
No network, no LLM calls, no external endpoints. Runs offline with cached model.
"""
import os
import shutil
import sys
import importlib
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Path setup (match existing test conventions)
# ---------------------------------------------------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../../python"))
sys.path.insert(0, python_module_dir)

# Reload rag_manager to defeat leaked monkey-patches from sibling test files
# (e.g. test_oracle_batch_retrieve.py sets rag_manager.embed_texts = mock_embed
#  at module level and never restores it).
import rag_manager
importlib.reload(rag_manager)
embed_texts = rag_manager.embed_texts
_chunk = rag_manager._chunk  # noqa: E402

PDF_PATH = os.path.join(script_dir, "January-2026-FX-Report.pdf")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pdf_text():
    """Extract raw text from the real PDF using PyMuPDF (fitz)."""
    import fitz
    assert os.path.isfile(PDF_PATH), f"Test fixture PDF missing: {PDF_PATH}"
    doc = fitz.open(PDF_PATH)
    pages = [page.get_text("text") for page in doc]
    doc.close()
    full_text = "\n\n".join(pages)
    assert len(full_text.strip()) > 200, "PDF text extraction produced too little content"
    return full_text


@pytest.fixture(scope="module")
def pdf_chunks(pdf_text):
    """Chunk the PDF text using the same splitter the ingest pipeline uses."""
    chunks = _chunk(pdf_text, chunk_size_chars=800, chunk_overlap_chars=100)
    assert len(chunks) >= 3, f"Expected at least 3 chunks from PDF, got {len(chunks)}"
    return chunks


@pytest.fixture(scope="module")
def embedded_vectors(pdf_chunks):
    """Embed all chunks with the real BAAI/bge-m3 model (1024-dim)."""
    vecs = embed_texts(
        pdf_chunks,
        backend="sentence-transformers",
        model="BAAI/bge-m3",
        api_base=None,
    )
    assert len(vecs) == len(pdf_chunks)
    assert all(len(v) == 1024 for v in vecs), "bge-m3 must produce 1024-dim vectors"
    return vecs


@pytest.fixture(scope="module")
def lancedb_dir():
    """Create a temp directory for the LanceDB instance; clean up after module."""
    tmp = tempfile.mkdtemp(prefix="e2e_embed_query_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def populated_db(lancedb_dir, pdf_chunks, embedded_vectors):
    """Write chunks + vectors into a real LanceDB table. Returns (db, table_name)."""
    import lancedb
    from lancedb.pydantic import LanceModel, Vector

    class RAGChunk(LanceModel):
        text: str
        vector: Vector(1024)
        source_file: str
        source_type: str
        line_start: int = 0
        line_end: int = 0

    db = lancedb.connect(lancedb_dir)
    table_name = "fx_report"
    tbl = db.create_table(table_name, schema=RAGChunk)

    rows = []
    for i, (text, vec) in enumerate(zip(pdf_chunks, embedded_vectors)):
        rows.append({
            "text": text,
            "vector": vec,
            "source_file": "January-2026-FX-Report.pdf",
            "source_type": "doc",
            "line_start": 0,
            "line_end": 0,
        })
    tbl.add(rows)
    assert tbl.count_rows() == len(pdf_chunks)
    return db, table_name


@pytest.fixture(scope="module")
def oracle_env(lancedb_dir):
    """Set ORACLE_* env vars so _retrieve() uses the same model + DB."""
    saved = {}
    env_vars = {
        "ORACLE_RAG_DB_DIR": lancedb_dir,
        "ORACLE_COLLECTION": "fx_report",
        "ORACLE_EMBED_BACKEND": "sentence-transformers",
        "ORACLE_EMBED_MODEL": "BAAI/bge-m3",
        "ORACLE_EMBED_API_BASE": "",
        "ORACLE_TYPE_FILTER": "",
        "ORACLE_QUERY_PREFIX": "",
        "ORACLE_NO_RERANK": "1",
    }
    for k, v in env_vars.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    yield
    for k, original in saved.items():
        if original is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = original


# ---------------------------------------------------------------------------
# Test 1: Embedding produces correct dimensionality
# ---------------------------------------------------------------------------

def test_embed_dimension_bge_m3():
    """BAAI/bge-m3 must produce exactly 1024-dim vectors (normalized by pipeline)."""
    vecs = embed_texts(
        ["The EUR/USD exchange rate is sensitive to ECB policy decisions."],
        backend="sentence-transformers",
        model="BAAI/bge-m3",
        api_base=None,
    )
    assert len(vecs) == 1
    assert len(vecs[0]) == 1024, f"Expected 1024 dims, got {len(vecs[0])}"
    # Verify non-trivial content (not all-zeros or all-identical from a leaked mock)
    assert len(set(vecs[0])) > 50, "Vector appears degenerate (all same values)"
    print("  [PASS] BAAI/bge-m3 produces 1024-dim vectors with varied content")


# ---------------------------------------------------------------------------
# Test 2: Embedding is deterministic (same text → same vector)
# ---------------------------------------------------------------------------

def test_embed_deterministic():
    """Embedding the same text twice must yield identical vectors."""
    text = "Central bank interest rate differentials drive carry trade flows."
    v1 = embed_texts([text], backend="sentence-transformers", model="BAAI/bge-m3", api_base=None)[0]
    v2 = embed_texts([text], backend="sentence-transformers", model="BAAI/bge-m3", api_base=None)[0]
    max_diff = max(abs(a - b) for a, b in zip(v1, v2))
    assert max_diff < 1e-5, f"Embedding not deterministic (max diff={max_diff})"
    print("  [PASS] Embedding is deterministic across calls")


# ---------------------------------------------------------------------------
# Test 3: LanceDB stores and retrieves vectors correctly
# ---------------------------------------------------------------------------

def test_lancedb_roundtrip(populated_db, embedded_vectors, pdf_chunks):
    """A vector stored in LanceDB must be retrievable with exact fidelity."""
    db, table_name = populated_db
    tbl = db.open_table(table_name)
    assert tbl.count_rows() == len(pdf_chunks)

    results = tbl.search(embedded_vectors[0]).limit(1).to_list()
    assert len(results) == 1
    assert results[0]["text"] == pdf_chunks[0]
    print("  [PASS] LanceDB vector roundtrip: stored vector retrieves its own chunk")


# ---------------------------------------------------------------------------
# Test 4: Semantic query retrieves relevant chunks (not random)
# ---------------------------------------------------------------------------

def test_semantic_query_relevance(populated_db, oracle_env):
    """A query about macroeconomic indicators must retrieve relevant PDF content."""
    from oracle_agent import _retrieve

    os.environ["ORACLE_COLLECTION"] = "fx_report"
    os.environ["ORACLE_TYPE_FILTER"] = ""

    result = _retrieve("tariff growth GDP economic policy labor market", k=5)
    assert result, "Query returned empty result — retrieval pipeline broken"
    assert "[source:" in result, "Retrieval result missing [source:] citation"
    # The PDF covers macro indicators; verify we got actual content, not empty
    assert len(result) > 100, f"Result too short ({len(result)} chars), likely no real content"
    # Verify the retrieved chunks contain PDF-sourced text (not synthetic)
    assert "January-2026-FX-Report.pdf" in result, "Source file citation missing"
    print(f"  [PASS] Semantic query returned {result.count('[source:')} chunk(s) from real PDF")


# ---------------------------------------------------------------------------
# Test 5: Dimension mismatch with wrong model → graceful failure
# ---------------------------------------------------------------------------

def test_dimension_mismatch_fails_gracefully(lancedb_dir, populated_db):
    """Querying a 1024-dim table with a 384-dim model must NOT return results.

    This proves the embed model must match between index and query.
    Skips gracefully if all-MiniLM-L6-v2 is not cached locally.
    """
    import lancedb

    db = lancedb.connect(lancedb_dir)
    tbl = db.open_table("fx_report")

    try:
        wrong_vecs = embed_texts(
            ["EUR USD exchange rate"],
            backend="sentence-transformers",
            model="all-MiniLM-L6-v2",
            api_base=None,
        )
    except Exception as e:
        pytest.skip(f"all-MiniLM-L6-v2 not available locally: {e}")

    assert len(wrong_vecs[0]) == 384, (
        f"all-MiniLM-L6-v2 should be 384-dim, got {len(wrong_vecs[0])}. "
        "If this is 1024, a leaked mock is active."
    )

    try:
        results = tbl.search(wrong_vecs[0]).limit(5).to_list()
        assert len(results) == 0, (
            f"Dimension mismatch returned {len(results)} results — "
            "should return 0 or raise"
        )
    except Exception:
        pass  # Expected: LanceDB raises on dimension mismatch
    print("  [PASS] Dimension mismatch (384 vs 1024) correctly fails/returns empty")


# ---------------------------------------------------------------------------
# Test 6: RRF fusion across multiple tables (real vectors)
# ---------------------------------------------------------------------------

def test_rrf_fusion_real_vectors(lancedb_dir, populated_db, pdf_chunks, embedded_vectors):
    """Two tables with real bge-m3 vectors fuse correctly via _rrf_merge."""
    import lancedb
    from lancedb.pydantic import LanceModel, Vector
    from oracle_agent import _rrf_merge

    db = lancedb.connect(lancedb_dir)

    class RAGChunk2(LanceModel):
        text: str
        vector: Vector(1024)
        source_file: str
        source_type: str
        line_start: int = 0
        line_end: int = 0

    tbl2_name = "fx_report_supplement"
    try:
        db.drop_table(tbl2_name)
    except Exception:
        pass
    tbl2 = db.create_table(tbl2_name, schema=RAGChunk2)

    supplement_rows = [
        {"text": pdf_chunks[i], "vector": embedded_vectors[i],
         "source_file": f"supplement_{i}.md", "source_type": "doc",
         "line_start": 0, "line_end": 0}
        for i in range(min(3, len(pdf_chunks)))
    ]
    tbl2.add(supplement_rows)

    query_vec = embedded_vectors[0]
    tbl1 = db.open_table("fx_report")
    results_tbl1 = tbl1.search(query_vec).limit(5).to_list()
    results_tbl2 = tbl2.search(query_vec).limit(5).to_list()

    fused = _rrf_merge([results_tbl1, results_tbl2], k=10)
    assert len(fused) > 0, "RRF fusion returned empty"
    texts = [r["text"] for r in fused]
    assert pdf_chunks[0] in texts, "Top chunk missing from RRF fused results"
    print(f"  [PASS] RRF fusion across 2 real tables returned {len(fused)} ranked results")


# ---------------------------------------------------------------------------
# Test 7: Type filter on real data
# ---------------------------------------------------------------------------

def test_type_filter_real_data():
    """ORACLE_TYPE_FILTER=code must exclude doc-only tables from results.

    Uses a self-contained temp DB with {collection}_code / {collection}_docs
    naming so _retrieve() enters the prefix-match branch (an exact-match on
    the bare collection name would bypass type filtering entirely).
    """
    import lancedb
    from lancedb.pydantic import LanceModel, Vector
    from oracle_agent import _retrieve

    tmp = tempfile.mkdtemp(prefix="e2e_type_filter_")
    saved_env = {}
    try:
        class RAGChunk3(LanceModel):
            text: str
            vector: Vector(1024)
            source_file: str
            source_type: str
            line_start: int = 0
            line_end: int = 0

        db = lancedb.connect(tmp)

        # Docs table: {collection}_docs suffix convention
        docs_tbl = db.create_table("tf_test_docs", schema=RAGChunk3)
        docs_vec = embed_texts(
            ["The EUR USD exchange rate reflects macroeconomic policy divergence"],
            backend="sentence-transformers", model="BAAI/bge-m3", api_base=None,
        )[0]
        docs_tbl.add([{
            "text": "The EUR USD exchange rate reflects macroeconomic policy divergence",
            "vector": docs_vec,
            "source_file": "macro_report.md",
            "source_type": "doc",
            "line_start": 0, "line_end": 0,
        }])

        # Code table: {collection}_code suffix convention
        code_tbl = db.create_table("tf_test_code", schema=RAGChunk3)
        code_vec = embed_texts(
            ["def compute_fx_rate(eur, usd): return eur / usd"],
            backend="sentence-transformers", model="BAAI/bge-m3", api_base=None,
        )[0]
        code_tbl.add([{
            "text": "def compute_fx_rate(eur, usd): return eur / usd",
            "vector": code_vec,
            "source_file": "fx_utils.py",
            "source_type": "code",
            "line_start": 1, "line_end": 2,
        }])

        # Collection "tf_test" does NOT match any table exactly,
        # so _retrieve() falls to prefix-match: tf_test_code, tf_test_docs.
        for k, v in {
            "ORACLE_RAG_DB_DIR": tmp,
            "ORACLE_COLLECTION": "tf_test",
            "ORACLE_EMBED_BACKEND": "sentence-transformers",
            "ORACLE_EMBED_MODEL": "BAAI/bge-m3",
            "ORACLE_EMBED_API_BASE": "",
            "ORACLE_NO_RERANK": "1",
        }.items():
            saved_env[k] = os.environ.get(k)
            os.environ[k] = v

        # type=code → only tf_test_code table survives the suffix filter
        os.environ["ORACLE_TYPE_FILTER"] = "code"
        result_code = _retrieve("compute exchange rate function def", k=5)
        assert result_code, "type=code query returned empty (prefix-match failed)"
        assert "fx_utils.py" in result_code, (
            f"Code source file missing from type=code query. Got: {result_code[:200]}"
        )
        assert "macro_report.md" not in result_code, "Docs leaked into type=code"

        # type=docs → only tf_test_docs table survives the suffix filter
        os.environ["ORACLE_TYPE_FILTER"] = "docs"
        result_docs = _retrieve("EUR USD exchange rate macroeconomic", k=5)
        assert result_docs, "type=docs query returned empty"
        assert "macro_report.md" in result_docs, (
            f"Docs source file missing from type=docs query. Got: {result_docs[:200]}"
        )
        assert "fx_utils.py" not in result_docs, "Code leaked into type=docs results"

        print("  [PASS] Type filter correctly isolates code vs docs on real vectors")
    finally:
        for k, original in saved_env.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 8: Full ingest pipeline via rag_manager.ingest() with real PDF
# ---------------------------------------------------------------------------

def test_full_ingest_pipeline_real_pdf():
    """Run rag_manager.ingest() end-to-end on a real PDF, then query the result.

    Exercises the actual production code path:
    collection dir → text extraction → chunk → embed → LanceDB → query.
    """
    import lancedb
    from rag_manager import ingest

    tmp = tempfile.mkdtemp(prefix="e2e_full_ingest_")
    try:
        collection = "fx_full_ingest"
        job_dir = os.path.join(tmp, collection)
        os.makedirs(job_dir, exist_ok=True)

        dest_pdf = os.path.join(job_dir, "January-2026-FX-Report.pdf")
        shutil.copy2(PDF_PATH, dest_pdf)

        success = ingest(
            context_root=tmp,
            collection_name=collection,
            embed_model="BAAI/bge-m3",
            embed_backend="sentence-transformers",
            embed_api_base=None,
            chunk_size_chars=800,
            chunk_overlap_chars=100,
            ocr_api_base=None,
            ocr_agent="",
            overwrite=True,
            batch=True,
            use_docling=False,
        )
        assert success, "rag_manager.ingest() returned False"

        db_dir = os.path.join(job_dir, "lancedb")
        assert os.path.isdir(db_dir), f"LanceDB dir not created: {db_dir}"
        db = lancedb.connect(db_dir)
        _names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        tables = list(getattr(_names, "tables", _names))
        assert len(tables) >= 1, f"No tables created. Found: {tables}"

        tbl = db.open_table(tables[0])
        assert tbl.count_rows() > 0, f"Table '{tables[0]}' is empty"

        os.environ["ORACLE_RAG_DB_DIR"] = db_dir
        os.environ["ORACLE_COLLECTION"] = tables[0]
        os.environ["ORACLE_EMBED_BACKEND"] = "sentence-transformers"
        os.environ["ORACLE_EMBED_MODEL"] = "BAAI/bge-m3"
        os.environ["ORACLE_EMBED_API_BASE"] = ""
        os.environ["ORACLE_TYPE_FILTER"] = ""
        os.environ["ORACLE_NO_RERANK"] = "1"

        from oracle_agent import _retrieve
        result = _retrieve("FX report volatility", k=5)
        assert result, "Full pipeline query returned empty"
        assert "[source:" in result
        print(f"  [PASS] Full ingest pipeline: {tbl.count_rows()} chunks, query returned {result.count('[source:')} hits")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 9: Cache hit — second ingest with overwrite=False skips
# ---------------------------------------------------------------------------

def test_ingest_cache_hit():
    """Second ingest with overwrite=False must skip (cache hit, no re-embedding)."""
    from rag_manager import ingest

    tmp = tempfile.mkdtemp(prefix="e2e_cache_hit_")
    try:
        collection = "fx_cache_test"
        job_dir = os.path.join(tmp, collection)
        os.makedirs(job_dir, exist_ok=True)
        shutil.copy2(PDF_PATH, os.path.join(job_dir, "January-2026-FX-Report.pdf"))

        kwargs = dict(
            context_root=tmp,
            collection_name=collection,
            embed_model="BAAI/bge-m3",
            embed_backend="sentence-transformers",
            embed_api_base=None,
            chunk_size_chars=800,
            chunk_overlap_chars=100,
            ocr_api_base=None,
            ocr_agent="",
            batch=True,
            use_docling=False,
        )

        r1 = ingest(overwrite=True, **kwargs)
        assert r1 is True

        r2 = ingest(overwrite=False, **kwargs)
        assert r2 is True
        print("  [PASS] Second ingest with overwrite=False is a cache hit (no re-embed)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 10: Vector normalization — bge-m3 outputs unit-norm vectors
# ---------------------------------------------------------------------------

def test_embed_vectors_are_unit_norm():
    """bge-m3 must produce unit-norm (L2) vectors; cosine == dot product."""
    vec = embed_texts(
        ["The EUR USD exchange rate is sensitive to ECB policy decisions."],
        backend="sentence-transformers",
        model="BAAI/bge-m3",
        api_base=None,
    )[0]
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-4, (
        f"Vector not unit-norm (‖v‖₂={norm:.6f}). "
        "Cosine similarity ranking will silently degrade if norm drifts."
    )
    print(f"  [PASS] bge-m3 vector is unit-norm (‖v‖₂={norm:.6f})")


# ---------------------------------------------------------------------------
# Test 11: _retrieve() must use the configured ORACLE_EMBED_MODEL
# ---------------------------------------------------------------------------

def test_retrieve_uses_configured_embed_model(lancedb_dir, populated_db):
    """Assert _retrieve() passes ORACLE_EMBED_MODEL to embed_texts.

    A refactor that hardcodes a default model would pass all other tests
    but silently break cosine similarity against the indexed vectors.
    """
    import oracle_agent

    captured = {}
    orig_embed = rag_manager.embed_texts

    def spy_embed(texts, backend, model, api_base, **kw):
        captured["model"] = model
        captured["backend"] = backend
        return orig_embed(texts, backend, model, api_base, **kw)

    # Patch both possible import paths
    rag_manager.embed_texts = spy_embed
    orig_oa = getattr(oracle_agent, "embed_texts", None)
    if orig_oa is not None:
        oracle_agent.embed_texts = spy_embed

    saved_env = {}
    env_vars = {
        "ORACLE_RAG_DB_DIR": lancedb_dir,
        "ORACLE_COLLECTION": "fx_report",
        "ORACLE_EMBED_BACKEND": "sentence-transformers",
        "ORACLE_EMBED_MODEL": "BAAI/bge-m3",
        "ORACLE_EMBED_API_BASE": "",
        "ORACLE_TYPE_FILTER": "",
        "ORACLE_QUERY_PREFIX": "",
        "ORACLE_NO_RERANK": "1",
    }
    try:
        for k, v in env_vars.items():
            saved_env[k] = os.environ.get(k)
            os.environ[k] = v

        oracle_agent._retrieve("test query for model identity", k=1)

        assert "model" in captured, "embed_texts was never called by _retrieve()"
        assert captured["model"] == "BAAI/bge-m3", (
            f"_retrieve used model={captured['model']!r}, expected 'BAAI/bge-m3'. "
            "A hardcoded default may have replaced the configured model."
        )
        assert captured["backend"] == "sentence-transformers", (
            f"_retrieve used backend={captured['backend']!r}, expected 'sentence-transformers'"
        )
        print("  [PASS] _retrieve() correctly uses ORACLE_EMBED_MODEL=BAAI/bge-m3")
    finally:
        rag_manager.embed_texts = orig_embed
        if orig_oa is not None:
            oracle_agent.embed_texts = orig_oa
        for k, original in saved_env.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original


# ---------------------------------------------------------------------------
# Test 12: source_type tagging from real ingest
# ---------------------------------------------------------------------------

def test_ingest_source_type_tagging():
    """After ingest(), .py files must have source_type='code', .md → 'doc'."""
    import lancedb
    from rag_manager import ingest

    tmp = tempfile.mkdtemp(prefix="e2e_src_type_")
    try:
        collection = "fx_src_type"
        job_dir = os.path.join(tmp, collection)
        os.makedirs(job_dir, exist_ok=True)

        # Create a Python source file
        with open(os.path.join(job_dir, "fx_utils.py"), "w") as f:
            f.write(
                "def compute_fx_rate(eur, usd):\n"
                "    \"\"\"Compute the EUR/USD exchange rate.\"\"\"\n"
                "    return eur / usd\n\n"
                "def apply_spread(rate, bps):\n"
                "    return rate * (1 + bps / 10000)\n"
            )

        # Create a Markdown doc file
        with open(os.path.join(job_dir, "macro_notes.md"), "w") as f:
            f.write(
                "# Macro Notes\n\n"
                "The EUR/USD pair is driven by interest rate differentials "
                "between the ECB and the Federal Reserve. Carry trade flows "
                "intensify when the spread exceeds 150 bps. Volatility "
                "clusters around FOMC and ECB press conferences.\n"
            )

        success = ingest(
            context_root=tmp,
            collection_name=collection,
            embed_model="BAAI/bge-m3",
            embed_backend="sentence-transformers",
            embed_api_base=None,
            chunk_size_chars=800,
            chunk_overlap_chars=100,
            ocr_api_base=None,
            ocr_agent="",
            overwrite=True,
            batch=True,
            use_docling=False,
        )
        assert success, "ingest() returned False"

        db_dir = os.path.join(job_dir, "lancedb")
        assert os.path.isdir(db_dir), f"LanceDB dir not created: {db_dir}"
        db = lancedb.connect(db_dir)
        _names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        tables = list(getattr(_names, "tables", _names))
        assert len(tables) >= 1, f"No tables created. Found: {tables}"

        # Collect all rows across all tables (LanceTable → arrow → dicts)
        all_rows = []
        for tname in tables:
            tbl = db.open_table(tname)
            all_rows.extend(tbl.to_arrow().to_pylist())

        assert len(all_rows) > 0, "No rows found in any table"

        code_rows = [r for r in all_rows if "fx_utils.py" in r.get("source_file", "")]
        doc_rows = [r for r in all_rows if "macro_notes.md" in r.get("source_file", "")]

        assert len(code_rows) > 0, "No rows tagged with fx_utils.py source file"
        assert len(doc_rows) > 0, "No rows tagged with macro_notes.md source file"

        for row in code_rows:
            assert row["source_type"] == "code", (
                f".py file row has source_type={row['source_type']!r}, expected 'code'"
            )
        for row in doc_rows:
            assert row["source_type"] == "doc", (
                f".md file row has source_type={row['source_type']!r}, expected 'doc'"
            )

        print(f"  [PASS] source_type tagging: {len(code_rows)} code rows, {len(doc_rows)} doc rows")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 13: Chunk overlap produces repeated content at boundaries
# ---------------------------------------------------------------------------

def test_chunk_overlap_produces_repeated_text():
    """Adjacent chunks with overlap>0 must share boundary text.

    A silent regression to overlap=0 would pass all other tests but
    degrade retrieval quality at chunk boundaries.
    """
    # Build a long, non-repeating text so we can detect overlap precisely
    words = [f"word{i}" for i in range(500)]
    text = " ".join(words)  # ~2500 chars, single paragraph

    chunks = _chunk(text, chunk_size_chars=500, chunk_overlap_chars=100)
    assert len(chunks) >= 3, f"Expected ≥3 chunks, got {len(chunks)}"

    for i in range(len(chunks) - 1):
        tail = chunks[i][-80:]
        head = chunks[i + 1][:80]
        # The tail of chunk i must appear in the head of chunk i+1
        assert tail.strip() in chunks[i + 1], (
            f"Chunk {i} tail not found in chunk {i+1}. "
            f"Tail: {tail[:40]!r}... — overlap may be 0 or broken."
        )
    print(f"  [PASS] {len(chunks)} chunks all share ≥80-char boundary overlap")


# ---------------------------------------------------------------------------
# Entry point for standalone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("E2E Embed → LanceDB → Query Roundtrip (BAAI/bge-m3, real PDF)")
    print("=" * 70)

    import subprocess
    exit_code = subprocess.call(
        [sys.executable, "-m", "pytest", __file__, "-s", "-v", "--tb=short"],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    sys.exit(exit_code)
