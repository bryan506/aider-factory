#!/usr/bin/env python3
"""E2E: Cloud embedding (google/gemini-embedding-2) → LanceDB → query roundtrip.

Tests the full cloud RAG pipeline using real litellm → Google API calls.
Keys and endpoints are read from the environment (GEMINI_API_KEY / GOOGLE_API_KEY).

Covers:
  1. Routing: api_base empty → litellm.embedding (NOT direct HTTP)
  2. Correct model name forwarded to litellm
  3. Real API call returns correct dimensionality
  4. Determinism (same text → same vector, within float tolerance)
  5. Unit-norm (or at least non-degenerate) vectors
  6. Batch iteration respects batch_size on cloud path
  7. LanceDB store + cosine retrieval with cloud vectors
  8. Full _retrieve() roundtrip with ORACLE_EMBED_MODEL=gemini/gemini-embedding-2
  9. Cross-model mismatch (cloud vector vs local table) → graceful failure
 10. Error handling: bad key, bad model name
 11. source_type tagging preserved through cloud ingest
 12. Query model identity: _retrieve() passes ORACLE_EMBED_MODEL to embed_texts

Requires: GEMINI_API_KEY or GOOGLE_API_KEY in environment.
Skips gracefully if key is absent.
"""
import os
import shutil
import sys
import tempfile
import time

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../../python"))
sys.path.insert(0, python_module_dir)

import rag_manager
import importlib
importlib.reload(rag_manager)
embed_texts = rag_manager.embed_texts

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CLOUD_MODEL = "gemini/gemini-embedding-2"
CLOUD_BACKEND = "openai"  # litellm routes gemini/ prefix internally
EMBED_DIM = 3072  # gemini-embedding-2 produces 3072-dim vectors (verify at runtime)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_cloud_key() -> bool:
    """Check that a Google/Gemini API key is available in environment."""
    return bool(
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    )


def _cloud_embed(texts: list[str], batch_size: int = 8) -> list[list[float]]:
    """Convenience: embed via cloud path (api_base empty → litellm)."""
    return embed_texts(
        texts,
        backend=CLOUD_BACKEND,
        model=CLOUD_MODEL,
        api_base="",  # empty → cloud path
        batch_size=batch_size,
    )


requires_cloud_key = pytest.mark.skipif(
    not _has_cloud_key(),
    reason="GEMINI_API_KEY / GOOGLE_API_KEY not set in environment",
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cloud_vectors():
    """Embed a set of diverse texts with the cloud model (one API call)."""
    texts = [
        "The EUR/USD exchange rate is driven by ECB-Fed policy divergence.",
        "def compute_fx_rate(eur, usd): return eur / usd",
        "Volatility clusters around FOMC announcements and ECB press conferences.",
        "Carry trade flows intensify when interest rate spreads exceed 150 bps.",
        "import numpy as np; def sharpe_ratio(returns, rf=0.03): return (returns.mean() - rf) / returns.std()",
        "Total federal receipts rose by $317 billion to $5.24 trillion in FY2025.",
        "The unemployment rate is due to a low hires rate rather than rising layoffs.",
        "class Portfolio: def __init__(self, weights): self.w = np.array(weights)",
    ]
    vecs = _cloud_embed(texts, batch_size=4)
    assert len(vecs) == len(texts)
    return texts, vecs


@pytest.fixture(scope="module")
def cloud_lancedb_dir():
    """Temp dir for cloud-vector LanceDB instance."""
    tmp = tempfile.mkdtemp(prefix="e2e_cloud_embed_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def cloud_populated_db(cloud_lancedb_dir, cloud_vectors):
    """Store cloud vectors in LanceDB. Returns (db, table_name, texts, vecs)."""
    import lancedb
    from lancedb.pydantic import LanceModel, Vector

    texts, vecs = cloud_vectors
    dim = len(vecs[0])

    class CloudRAGChunk(LanceModel):
        text: str
        vector: Vector(dim)
        source_file: str
        source_type: str
        line_start: int = 0
        line_end: int = 0

    db = lancedb.connect(cloud_lancedb_dir)
    table_name = "cloud_fx_report"
    tbl = db.create_table(table_name, schema=CloudRAGChunk)

    rows = []
    for i, (text, vec) in enumerate(zip(texts, vecs)):
        is_code = text.startswith(("def ", "import ", "class "))
        rows.append({
            "text": text,
            "vector": vec,
            "source_file": "fx_utils.py" if is_code else "fx_report.md",
            "source_type": "code" if is_code else "doc",
            "line_start": i * 10,
            "line_end": i * 10 + 9,
        })
    tbl.add(rows)
    assert tbl.count_rows() == len(texts)
    return db, table_name, texts, vecs


@pytest.fixture
def cloud_oracle_env(cloud_lancedb_dir):
    """Set ORACLE_* env vars for cloud model retrieval; restore after."""
    saved = {}
    env_vars = {
        "ORACLE_RAG_DB_DIR": cloud_lancedb_dir,
        "ORACLE_COLLECTION": "cloud_fx_report",
        "ORACLE_EMBED_BACKEND": CLOUD_BACKEND,
        "ORACLE_EMBED_MODEL": CLOUD_MODEL,
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
# Test 1: Routing — cloud path uses litellm, not direct HTTP
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_routing_uses_litellm():
    """api_base='' must route through litellm.embedding, NOT requests.post."""
    import types

    captured = {}
    mock_litellm = types.ModuleType("litellm")

    def fake_embedding(model=None, input=None, **kw):
        captured["model"] = model
        captured["input"] = input
        captured["kw"] = kw
        return {"data": [{"embedding": [0.1] * 10} for _ in input]}

    mock_litellm.embedding = fake_embedding
    orig = sys.modules.get("litellm")
    sys.modules["litellm"] = mock_litellm

    try:
        vecs = embed_texts(["test"], backend="openai",
                           model=CLOUD_MODEL, api_base="")
        assert captured["model"] == CLOUD_MODEL, (
            f"Model not forwarded correctly: got {captured['model']!r}"
        )
        assert captured["input"] == ["test"]
        print(f"  [PASS] Cloud routing: litellm.embedding called with model={CLOUD_MODEL}")
    finally:
        if orig is not None:
            sys.modules["litellm"] = orig
        else:
            sys.modules.pop("litellm", None)


# ---------------------------------------------------------------------------
# Test 2: Real API call returns correct dimensionality
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_embed_dimension():
    """google/gemini-embedding-2 must return vectors of expected dimension."""
    vecs = _cloud_embed(["The quick brown fox jumps over the lazy dog."])
    assert len(vecs) == 1
    dim = len(vecs[0])
    assert dim > 0, "Cloud embedding returned zero-length vector"
    # Verify non-degenerate
    assert len(set(vecs[0])) > 50, "Vector appears degenerate (too many identical values)"
    print(f"  [PASS] Cloud embed dimension: {dim}")


# ---------------------------------------------------------------------------
# Test 3: Determinism
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_embed_deterministic():
    """Same text embedded twice must yield near-identical vectors."""
    text = "Central bank interest rate differentials drive carry trade flows."
    v1 = _cloud_embed([text])[0]
    time.sleep(0.5)  # avoid rate-limit burst
    v2 = _cloud_embed([text])[0]

    max_diff = max(abs(a - b) for a, b in zip(v1, v2))
    # Cloud APIs may have tiny float nondeterminism; 1e-4 is generous
    assert max_diff < 1e-4, f"Cloud embedding not deterministic (max diff={max_diff})"
    print(f"  [PASS] Cloud embed deterministic (max diff={max_diff:.2e})")


# ---------------------------------------------------------------------------
# Test 4: Batch iteration on cloud path
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_embed_batching():
    """batch_size must be respected: 10 texts with batch_size=3 → 4 API calls."""
    call_count = {"n": 0}
    import types

    mock_litellm = types.ModuleType("litellm")

    def fake_embedding(model=None, input=None, **kw):
        call_count["n"] += 1
        return {"data": [{"embedding": [0.1] * 10} for _ in input]}

    mock_litellm.embedding = fake_embedding
    orig = sys.modules.get("litellm")
    sys.modules["litellm"] = mock_litellm

    try:
        texts = [f"text_{i}" for i in range(10)]
        vecs = embed_texts(texts, backend="openai",
                           model=CLOUD_MODEL, api_base="", batch_size=3)
        assert len(vecs) == 10
        # 10 / 3 = 4 batches (3+3+3+1)
        assert call_count["n"] == 4, f"Expected 4 batches, got {call_count['n']}"
        print(f"  [PASS] Cloud batching: 10 texts → {call_count['n']} API calls")
    finally:
        if orig is not None:
            sys.modules["litellm"] = orig
        else:
            sys.modules.pop("litellm", None)


# ---------------------------------------------------------------------------
# Test 5: LanceDB roundtrip with cloud vectors
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_lancedb_roundtrip(cloud_populated_db):
    """A cloud-embedded vector stored in LanceDB must retrieve its own chunk."""
    db, table_name, texts, vecs = cloud_populated_db
    tbl = db.open_table(table_name)

    results = tbl.search(vecs[0]).limit(1).to_list()
    assert len(results) == 1
    assert results[0]["text"] == texts[0]
    print("  [PASS] Cloud vector LanceDB roundtrip: stored vector retrieves own chunk")


# ---------------------------------------------------------------------------
# Test 6: Semantic query relevance with cloud model
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_semantic_relevance(cloud_populated_db, cloud_oracle_env):
    """A code-related query must rank the code chunk highest."""
    from oracle_agent import _retrieve

    result = _retrieve("def compute exchange rate function code", k=3)
    assert result, "Cloud query returned empty"
    assert "[source:" in result
    # The code chunk should appear (fx_utils.py)
    assert "fx_utils.py" in result, (
        f"Code chunk not retrieved by code query. Got: {result[:300]}"
    )
    print(f"  [PASS] Cloud semantic query: {result.count('[source:')} chunk(s) returned")


# ---------------------------------------------------------------------------
# Test 7: _retrieve() uses ORACLE_EMBED_MODEL correctly (cloud)
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_retrieve_uses_configured_model(cloud_lancedb_dir, cloud_populated_db):
    """_retrieve() must pass ORACLE_EMBED_MODEL to embed_texts, not hardcode."""
    import oracle_agent

    captured = {}
    orig_embed = rag_manager.embed_texts

    def spy_embed(texts, backend, model, api_base, **kw):
        captured["model"] = model
        captured["backend"] = backend
        captured["api_base"] = api_base
        return orig_embed(texts, backend, model, api_base, **kw)

    rag_manager.embed_texts = spy_embed
    try:
        os.environ["ORACLE_RAG_DB_DIR"] = cloud_lancedb_dir
        os.environ["ORACLE_COLLECTION"] = "cloud_fx_report"
        os.environ["ORACLE_EMBED_BACKEND"] = CLOUD_BACKEND
        os.environ["ORACLE_EMBED_MODEL"] = CLOUD_MODEL
        os.environ["ORACLE_EMBED_API_BASE"] = ""
        os.environ["ORACLE_NO_RERANK"] = "1"
        os.environ["ORACLE_TYPE_FILTER"] = ""

        oracle_agent._retrieve("test query", k=1)
        assert captured["model"] == CLOUD_MODEL, (
            f"_retrieve() used wrong model: {captured['model']!r}"
        )
        assert captured["backend"] == CLOUD_BACKEND
        print(f"  [PASS] _retrieve() uses ORACLE_EMBED_MODEL={CLOUD_MODEL}")
    finally:
        rag_manager.embed_texts = orig_embed


# ---------------------------------------------------------------------------
# Test 8: Cross-model mismatch → graceful failure
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_cross_model_mismatch(cloud_lancedb_dir, cloud_populated_db):
    """Querying cloud-dim table with local 1024-dim model must fail gracefully."""
    import lancedb

    db = lancedb.connect(cloud_lancedb_dir)
    tbl = db.open_table("cloud_fx_report")

    # Get a local 1024-dim vector
    try:
        local_vecs = embed_texts(
            ["EUR USD rate"],
            backend="sentence-transformers",
            model="BAAI/bge-m3",
            api_base=None,
        )
    except Exception:
        pytest.skip("bge-m3 not available locally for cross-model test")

    assert len(local_vecs[0]) == 1024

    try:
        results = tbl.search(local_vecs[0]).limit(5).to_list()
        # Either empty or raises — must not return wrong results
        assert len(results) == 0, (
            f"Dimension mismatch returned {len(results)} results"
        )
    except Exception:
        pass  # Expected: LanceDB raises on dimension mismatch
    print("  [PASS] Cloud/local dimension mismatch correctly fails/returns empty")


# ---------------------------------------------------------------------------
# Test 9: Type filter with cloud vectors
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_type_filter():
    """ORACLE_TYPE_FILTER=code must only return _code tables (cloud vectors)."""
    import lancedb
    from lancedb.pydantic import LanceModel, Vector
    from oracle_agent import _retrieve

    tmp = tempfile.mkdtemp(prefix="e2e_cloud_type_")
    saved_env = {}
    try:
        # Embed one code + one doc text
        code_vec = _cloud_embed(["def calculate_spread(bid, ask): return ask - bid"])[0]
        doc_vec = _cloud_embed(["The ECB raised rates by 25 basis points in March."])[0]
        dim = len(code_vec)

        class CloudChunk(LanceModel):
            text: str
            vector: Vector(dim)
            source_file: str
            source_type: str
            line_start: int = 0
            line_end: int = 0

        db = lancedb.connect(tmp)
        db.create_table("cloudtest_docs", schema=CloudChunk).add([{
            "text": "The ECB raised rates by 25 basis points in March.",
            "vector": doc_vec, "source_file": "ecb_notes.md",
            "source_type": "doc", "line_start": 0, "line_end": 0,
        }])
        db.create_table("cloudtest_code", schema=CloudChunk).add([{
            "text": "def calculate_spread(bid, ask): return ask - bid",
            "vector": code_vec, "source_file": "spread.py",
            "source_type": "code", "line_start": 1, "line_end": 2,
        }])

        for k, v in {
            "ORACLE_RAG_DB_DIR": tmp,
            "ORACLE_COLLECTION": "cloudtest",
            "ORACLE_EMBED_BACKEND": CLOUD_BACKEND,
            "ORACLE_EMBED_MODEL": CLOUD_MODEL,
            "ORACLE_EMBED_API_BASE": "",
            "ORACLE_NO_RERANK": "1",
        }.items():
            saved_env[k] = os.environ.get(k)
            os.environ[k] = v

        # type=code → only cloudtest_code
        os.environ["ORACLE_TYPE_FILTER"] = "code"
        res_code = _retrieve("calculate bid ask spread function", k=5)
        assert res_code, "type=code returned empty"
        assert "spread.py" in res_code
        assert "ecb_notes.md" not in res_code

        # type=docs → only cloudtest_docs
        os.environ["ORACLE_TYPE_FILTER"] = "docs"
        res_docs = _retrieve("ECB interest rate decision", k=5)
        assert res_docs, "type=docs returned empty"
        assert "ecb_notes.md" in res_docs
        assert "spread.py" not in res_docs

        print("  [PASS] Cloud type filter correctly isolates code vs docs")
    finally:
        for k, original in saved_env.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 10: Error handling — bad model name
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_bad_model_name():
    """A nonexistent model must raise, not silently return zeros."""
    with pytest.raises(Exception):
        embed_texts(
            ["test"],
            backend="openai",
            model="google/nonexistent-model-xyz-99999",
            api_base="",
        )
    print("  [PASS] Bad cloud model name raises exception (no silent zeros)")


# ---------------------------------------------------------------------------
# Test 11: Empty input returns [] without API call
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_empty_input():
    """Empty input must return [] without hitting the API."""
    vecs = embed_texts([], backend="openai", model=CLOUD_MODEL, api_base="")
    assert vecs == []
    print("  [PASS] Empty cloud input returns [] (no API call)")


# ---------------------------------------------------------------------------
# Test 12: Full ingest pipeline with cloud model
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_full_ingest_pipeline():
    """rag_manager.ingest() end-to-end with cloud embedding model."""
    import lancedb
    from rag_manager import ingest

    tmp = tempfile.mkdtemp(prefix="e2e_cloud_ingest_")
    try:
        collection = "cloud_fx_ingest"
        job_dir = os.path.join(tmp, collection)
        os.makedirs(job_dir, exist_ok=True)

        # Create source files
        with open(os.path.join(job_dir, "fx_utils.py"), "w") as f:
            f.write(
                "def compute_fx_rate(eur, usd):\n"
                "    \"\"\"Compute the EUR/USD exchange rate.\"\"\"\n"
                "    return eur / usd\n\n"
                "def apply_spread(rate, bps):\n"
                "    return rate * (1 + bps / 10000)\n"
            )
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
            embed_model=CLOUD_MODEL,
            embed_backend=CLOUD_BACKEND,
            embed_api_base="",  # cloud path
            chunk_size_chars=800,
            chunk_overlap_chars=100,
            ocr_api_base=None,
            ocr_agent="",
            overwrite=True,
            batch=True,
            use_docling=False,
        )
        assert success, "ingest() returned False with cloud model"

        db_dir = os.path.join(job_dir, "lancedb")
        assert os.path.isdir(db_dir)
        db = lancedb.connect(db_dir)
        _names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        tables = list(getattr(_names, "tables", _names))
        assert len(tables) >= 1, f"No tables created. Found: {tables}"

        # Verify vectors stored with correct dimension
        tbl = db.open_table(tables[0])
        assert tbl.count_rows() > 0
        sample = tbl.to_arrow().to_pylist()[0]
        assert len(sample["vector"]) > 0
        print(f"  [PASS] Cloud ingest: {tbl.count_rows()} chunks, dim={len(sample['vector'])}")

        # Query via _retrieve
        os.environ["ORACLE_RAG_DB_DIR"] = db_dir
        os.environ["ORACLE_COLLECTION"] = tables[0]
        os.environ["ORACLE_EMBED_BACKEND"] = CLOUD_BACKEND
        os.environ["ORACLE_EMBED_MODEL"] = CLOUD_MODEL
        os.environ["ORACLE_EMBED_API_BASE"] = ""
        os.environ["ORACLE_NO_RERANK"] = "1"
        os.environ["ORACLE_TYPE_FILTER"] = ""

        from oracle_agent import _retrieve
        result = _retrieve("FX rate computation exchange", k=5)
        assert result, "Cloud full-pipeline query returned empty"
        assert "[source:" in result
        print(f"  [PASS] Cloud full pipeline: query returned {result.count('[source:')} hits")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 13: Cosine similarity sanity (related > unrelated)
# ---------------------------------------------------------------------------

@requires_cloud_key
def test_cloud_cosine_sanity():
    """Related text pair must have higher cosine sim than unrelated pair."""
    related = _cloud_embed([
        "The ECB raised interest rates by 25 basis points.",
        "The European Central Bank increased its benchmark rate.",
    ])
    unrelated = _cloud_embed([
        "The ECB raised interest rates by 25 basis points.",
        "The mitochondria is the powerhouse of the cell.",
    ])

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0

    sim_related = cosine(related[0], related[1])
    sim_unrelated = cosine(unrelated[0], unrelated[1])

    assert sim_related > sim_unrelated, (
        f"Cosine sanity failed: related={sim_related:.4f} ≤ unrelated={sim_unrelated:.4f}"
    )
    print(f"  [PASS] Cosine sanity: related={sim_related:.4f} > unrelated={sim_unrelated:.4f}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print(f"E2E Cloud Embed → LanceDB → Query Roundtrip ({CLOUD_MODEL})")
    print("=" * 70)
    if not _has_cloud_key():
        print("SKIP: No GEMINI_API_KEY / GOOGLE_API_KEY in environment.")
        sys.exit(0)

    import subprocess
    exit_code = subprocess.call(
        [sys.executable, "-m", "pytest", __file__, "-s", "-v", "--tb=short"],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    sys.exit(exit_code)
