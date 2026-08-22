# LanceDB Vector Database & RAG Ingestion Engine

The AI Factory Knowledge Oracle and Validation systems leverage **LanceDB**—a high-performance, embedded, serverless vector database built directly on **Apache Arrow** and written in **Rust**.

This document is the master architectural and operational specification for LanceDB storage, multi-format document ingestion, AST code chunking, indexing thresholds, Reciprocal Rank Fusion (RRF), table compaction, and database maintenance CLI tooling.

---

## 1. Storage Topologies: Unified Corpus vs. Per-Document Tables

The pipeline supports two distinct storage architectures configured via the `rag.batch` YAML toggle:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   LANCEDB STORAGE TOPOLOGIES                                    │
├───────────────────────────────────────────────┬─────────────────────────────────────────────────┤
│          `batch: true` (Unified Table)        │        `batch: false` (Per-Document Tables)     │
├───────────────────────────────────────────────┼─────────────────────────────────────────────────┤
│ • Tables: `<collection>_docs`,                │ • Tables: `<doc_stem_1>`, `<doc_stem_2>`, ...   │
│           `<collection>_<repo>_code`          │ • 1 isolated LanceDB table per document         │
│ • Unified vector space across entire corpus   │ • Multi-table Reciprocal Rank Fusion (RRF)      │
│ • Bypasses client-side fusion (Single Search) │ • Dynamic candidate recall scaling              │
│ • Optimal for: Software Docs & Code Repos     │ • Optimal for: Multi-Paper Literature Reviews   │
└───────────────────────────────────────────────┴─────────────────────────────────────────────────┘
```

### 1.1 `batch: true` (Unified Type-Routed Architecture)
- **Table Naming**: `<collection>_docs`, `<collection>_<repo>_code`, `<collection>_<repo>_docs`.
- **Execution**: All documents in the collection directory are embedded into a single unified table.
- **Search Mechanics**: When querying, `oracle_agent.py` executes a single vectorized kNN search over Apache Arrow contiguous memory. Because `len(per_table) == 1`, client-side RRF fusion is bypassed directly, feeding candidates straight to the Stage 2 Cross-Encoder.
- **Best Used For**: Software documentation, manuals, API specifications, and codebase repositories where global vector distance comparison across all files is required.

### 1.2 `batch: false` (Per-Document Table Architecture)
- **Table Naming**: Sanitized document stem (e.g. `paper_2024_momentum`, `macro_rates`).
- **Execution**: Each document or paper gets its own isolated LanceDB table.
- **Search Mechanics**: Vector search runs across each table independently. Candidates are merged using **Reciprocal Rank Fusion (RRF)**:
  $$\text{RRF\_Score}(d) = \sum_{t \in \text{Tables}} \frac{1}{60 + \text{rank}_t(d)}$$
- **Dynamic Recall Scaling**: To prevent candidate starvation when querying across many tables, Stage 1 recall scales dynamically:
  $$\text{recall\_k} = \min(\max(k \times 4,\, 30,\, \text{len(tables)} \times 4),\, 100)$$
- **Deterministic Composite Tie-Breaking**: RRF scores tied at identical ranks are broken deterministically by `(-score, source_file, text_prefix)`, eliminating filesystem inode traversal variance.
- **Best Used For**: Multi-paper academic literature reviews, legal contracts, or distinct books where users need per-document targeting (`oracle --collection paper_stem`) and surgical single-document updates (`oracle --rm-table <name>`).

---

## 2. Table Schema & Data Modeling

Every LanceDB table is defined via `lancedb.pydantic.LanceModel` with strict metadata typing:

```python
class RAGChunk(LanceModel):
    text: str                       # Passage chunk content
    vector: Vector(_dim)            # Embedding vector (e.g., 1024 for bge-m3, 4096 for qwen)
    source_file: str                # Relative file path (e.g., "manuals/risk.md")
    source_type: str                # "code" | "doc"
    language: str = ""              # Programming language ("python", "r", "rust", etc.)
    symbol: str = ""                # AST Symbol name (function, class, or method)
    line_start: int = 0             # 1-indexed source start line
    line_end: int = 0               # 1-indexed source end line
```

### Schema Safety Invariant
When appending new files to an existing table (`overwrite: false`), `rag_manager.py` verifies:
1. `source_type` and `language` columns exist in the Arrow schema.
2. Vector dimension matches the active embedding model (`table.schema.field("vector").type.list_size == _dim`).
If a legacy schema or dimension mismatch is detected, ingestion safely aborts with an actionable error rather than corrupting the database.

---

## 3. Ingestion Engines & Multi-Format Processing

The ingestion pipeline (`rag_manager.py`) automatically routes and processes different file types:

```
[Raw Files]
     │
     ├── Code Files (.py, .R, .js, .rs, .go) ──► Tree-Sitter AST Chunking (Functions/Classes)
     │
     ├── Office & Digital Docs (.pdf, .docx, .html) ──► Docling High-Fidelity Markdown Extraction
     │                                                         │ (Fallback on scan/error)
     │                                                         ▼
     └── Scanned PDFs & Images (.png, .jpg) ──────────► Vision OCR (GLM-OCR / Gemini) + CER Gate
```

### 3.1 AST-Aware Code Chunking
- Code files are parsed using `tree-sitter-language-pack`.
- AST nodes are chunked by structural boundaries (functions, classes, methods).
- **Oversized Leaf Fallback (`_text_split_fallback`)**: If a single AST node (e.g. a huge array or multiline string) exceeds `code_chunk_size` (default: 2000 chars), the engine falls back to line-level splitting with 3-line overlap while preserving the AST symbol metadata.

### 3.2 Docling Multi-Format Extraction
- Digital PDFs, Office files (`.docx`, `.pptx`, `.xlsx`), HTML, and AsciiDoc are processed via `docling_runner.py` in an isolated subprocess (`uv run --isolated --with docling>=2.0.0`).
- Preserves document structural headers (`# Document Metadata`), author attribution, and embedded Markdown tables.

### 3.3 Vision OCR with CER-Gated Retries
- Scanned documents and raw images are rasterized to PNGs via PyMuPDF (`fitz`) at 150 DPI.
- OCR vision requests run sequentially or in parallel (`ocr_parallel: 8`).
- **Character Error Rate (CER) Gate**: Normalized edit distance is computed on alphanumeric text:
  $$\text{CER}(\text{ref}, \text{hyp}) = \frac{\text{LevenshteinDistance}(\text{ref}_{\text{alphanumeric}}, \text{hyp}_{\text{alphanumeric}})}{\text{Length}(\text{ref}_{\text{alphanumeric}})}$$
- If CER $> \text{cer\_threshold}$ (0.05), page OCR is retried up to `ocr_max_retries` (default: 2). If CER remains $> 0.40$ on digital PDFs, the engine falls back to the embedded PDF text layer.

### 3.4 Multi-Stage URL & Web Conversion Pipeline (`rag_web.py`)
When web URLs or lists of URLs (`--add-web <url>...` or `--add-web --file <urls.txt>`) are passed to the ingestion engine:
1. **Content-Type HEAD Sniff**: Executes a fast `HEAD` request. If `application/pdf` or a `.pdf` extension is detected, it directly downloads the binary PDF.
2. **`llms.txt` Discovery**: Checks `{domain}/llms.txt`. If present ($>50$ bytes), it extracts the structured AI-friendly Markdown documentation.
3. **Trafilatura HTML Extraction**: Fetches HTML using a spoofed `Mozilla/5.0` User-Agent to bypass basic WAFs and bot-checks, converting main body text into clean Markdown with embedded table structures.
4. **Headless Playwright Fallback**: If Trafilatura fails or yields $<100$ bytes (e.g. JavaScript Single-Page Applications), it launches headless Chromium via Playwright to render the page and extract Markdown.
5. **Deterministic Naming**: Output files are written to `.aider_factory/markdown/lanceDB/<collection>/<domain>_<path_stem>.md` (or `.pdf`) and incrementally indexed.

### 3.5 Atomic Fenced Code Block Chunking
Documents and OCR sidecars are processed via a semantic chunker that preserves the opening and closing fences of oversized Markdown code blocks (` ``` ` or `~~~`), preventing mid-block fracturing that confuses language models.

---

## 4. Ingestion Memory Bounds & Compaction

### 4.1 Buffered Streaming Ingestion (`FLUSH_CHUNK_THRESHOLD`)
To cap RAM usage during large codebase builds, chunks are buffered in memory and flushed to LanceDB once the queue reaches `FLUSH_CHUNK_THRESHOLD = 2000` chunks. This writes partial progress to disk so unexpected interruptions do not lose previously processed documents.

### 4.2 Automated Table Compaction (`table.optimize()`)
LanceDB uses append-only fragment writes and soft-deletes. To maintain peak read performance and reclaim disk space:
- **Post-Ingestion**: `rag_manager._build_table` calls `table.optimize()` after chunk flushes to compact small fragment files into unified Arrow batches.
- **Post-Deletion**: `oracle_agent._remove_file` calls `tbl.optimize()` after deleting a file's chunks from a table.

---

## 5. Search Engine & Indexing Invariants

### 5.1 Flat Exact kNN vs. `IVF_PQ` Index Threshold (`IVF_PQ_MIN_ROWS`)
- **Tables $\le 50,000$ rows**: LanceDB uses exact brute-force kNN search via SIMD/AVX-512. At this scale, flat search executes in $< 15\text{ms}$ with 100% precision and zero quantization loss.
- **Tables $> 50,000$ rows (`IVF_PQ_MIN_ROWS = 50000`)**: `rag_manager.py` automatically builds an `IVF_PQ` Approximate Nearest Neighbor (ANN) index with cosine distance.

### 5.2 Cosine Distance Mathematics & Score Calibration
In LanceDB, vector similarity search with `metric="cosine"` returns the `_distance` column representing:
$$\text{\_distance} = 1 - \frac{u \cdot v}{\|u\|_2 \|v\|_2} = 1 - \cos(\theta)$$
In `validator.py`, semantic similarity is calibrated directly:
```python
sim = 1.0 - float(rows[0].get("_distance", 1.0))
```
This maps LanceDB distance back to standard cosine similarity $\in [-1.0, 1.0]$ (and $[0.0, 1.0]$ for non-negative text embeddings).

---

## 6. Operational Invariants & Safeguards

### 6.1 LanceDB Table Retrieval API Compatibility
LanceDB 0.4+ changed how `list_tables()` returns data. The Oracle and Validator handle both legacy lists and modern `ListTablesResponse` objects:
```python
_names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
available_tables = list(getattr(_names, "tables", _names))
```

### 6.2 Query Vector Truncation Guard (`_MAX_EMBED_CHARS = 6000`)
When retrieving via `top_k`, the query text is truncated to 6,000 characters before embedding (`_MAX_EMBED_CHARS = 6000`). This prevents long debate prompts or attached code context from overflowing embedding model context windows (e.g. `sentence-transformers` or `BAAI/bge-m3`) and causing VRAM OOMs.

### 6.3 Active Working File Exclusion
Any file listed under `target_files`, `extra_editable_files`, or `context_files_job` in the active phase is automatically excluded from ingestion scanning. The `working_repo` is auto-derived from `os.path.basename(working_directory)`. This prevents stale code copies from polluting vector retrieval during active refactoring.

### 6.4 Zero-RAG Bypass Mode (`collection_name: ""`)
If a phase configuration specifies `rag.collection_name: ""` (empty string or `[]`), the pipeline bypasses LanceDB vector ingestion and retrieval entirely. Both the Programmatic Oracle and Pre-Edit debates will rely strictly on the raw text contents of the files defined in `target_files` and `context_files_job` injected directly into the prompt.

### 6.5 Smart Global Path Resolution
The `--collection` flag accepts global filesystem paths (e.g., `--collection ~/projects/alpha/.aider_factory/markdown/lanceDB/alpha_docs`). The CLI automatically extracts `alpha_docs` as the collection name and auto-derives the `--db` path, eliminating the need to pass `--db` manually for cross-project queries.

---

## 7. Database Maintenance CLI Reference (`aider-oracle`)

The Oracle CLI provides a complete administrative suite for managing LanceDB collections:

```bash
# 1. List all tables in the active collection directory
aider-oracle --list

# 2. List all unique source files ingested across all tables
aider-oracle --list-files

# 3. Incrementally add and ingest one or more files
aider-oracle --add-file docs/architecture.pdf notes/specs.md

# 4. OCR files to Markdown ONLY (skip LanceDB vector indexing)
aider-oracle --add-file docs/paper.pdf --no-rag

# 5. Recursively copy and ingest an entire directory of documents
aider-oracle --add-table /path/to/reference_library/

# 6. Fetch URLs, convert to Markdown, and ingest into LanceDB
aider-oracle --add-web https://example.com/docs https://example.com/api.pdf
aider-oracle --add-web --file urls.txt --workers 8

# 7. Surgically delete all chunks for a specific file across all tables
aider-oracle --rm-file specs.md

# 8. Drop a specific table completely
aider-oracle --rm-table alpha_strategies_docs

# 9. Wipe the vector database (lancedb/) while preserving raw markdown and OCR caches
aider-oracle --rm-db
```

---

## 8. Troubleshooting & Common Errors

| Issue | Root Cause | Solution |
| :--- | :--- | :--- |
| **`[knowledge base unavailable: ...]`** | Embedding endpoint is unreachable or model was evicted on `--models-max 1` servers. | Verify embedding server health (`curl <embed_api_base>/v1/models`). Check if another model evicted the embedder. |
| **`400 Bad Request: context size exceeded`** | Input tokens exceed per-slot context on llama-server (`ctx-size / parallel`). | Increase `ctx-size` in `models.ini` or verify query truncation to $\le 6000$ chars. |
| **`ImportError: lancedb`** | Script was executed with system Python instead of Aider's venv. | Run using `uv run` or `.aider_factory/bash/oracle`. |
| **`old-schema table ... (pre-metadata)`** | Table was created with legacy schema lacking `source_type` / `language`. | Set `vectordb_overwrite: true` in YAML to rebuild tables with the modern schema. |

---

## 9. Configuration Reference (`.env.yml`)

Configure LanceDB and RAG ingestion under the `rag` and `endpoints` blocks:

```yaml
endpoints:
  embed_api_base: "http://192.168.100.2:8081/v1" # Local embedding server (or null for cloud)
  ocr_api_base: "http://192.168.100.2:8081/v1"   # Vision OCR server (or null for cloud)
  ranking_api_base: null                         # null = local in-process cross-encoder

phases:
  - name: "Implementation"
    models:
      embed_model: "BAAI/bge-m3"                 # HuggingFace or cloud model name
      ocr_agent: "glm-ocr-f16:LATEST"            # Vision OCR model identifier
      ranking_agent: "jinaai/jina-reranker-v3.5" # Cross-Encoder reranker

    rag:
      collection_name: "project_knowledge"       # Folder under .aider_factory/markdown/lanceDB/
      batch: true                                # true = unified table, false = per-doc tables
      retrieval_mode: top_k                      # top_k | no_retrieve | full_document
      recall_k: 30                               # Stage 1 vector candidates (before rerank)
      top_k: 5                                   # Stage 2 final context chunks (after rerank)
      chunk_size_chars: 800                      # Text chunk size
      chunk_overlap_chars: 100                   # Chunk overlap
      code_chunk_size: 2000                      # AST code chunk size
      cer_threshold: 0.05                        # OCR Character Error Rate threshold
      ocr_max_retries: 2                         # OCR retry count
      ocr_parallel: 8                            # Parallel OCR workers
      use_docling: true                          # Fast-path digital document extraction
      docling_do_ocr: true                       # Docling internal OCR for scanned pages
      vectordb_overwrite: false                  # false = incremental cache-hit, true = rebuild
```

---

## 10. Troubleshooting & Runtime Diagnostics

| Symptom | Cause | Resolution |
| :--- | :--- | :--- |
| **`404 Not Found` on `/v1/rerank`** | Server serves endpoints at `/rerank` instead of `/v1/rerank`. | Engine automatically catches 404 and retries at `/rerank`. |
| **`[rerank] warning: remote rerank failed`** | Remote endpoint timed out or returned an error. | Engine logs warning to `stderr` and safely falls back to Stage 1 vector/RRF order (fail-open). |
| **Chat template ValueError with `sentence-transformers >= 3.0`** | LLM-based reranker lacks standard query/document template in tokenizer config. | Engine automatically injects standard `<Query>` / `<Document>` Jinja template. |
| **Padding token crash during batch prediction** | Tokenizer missing `pad_token`. | Engine automatically binds `pad_token = eos_token` and syncs `pad_token_id`. |
| **Inverted ranking (irrelevant chunks ranked top)** | Model outputs 2D classification logits `[neg, pos]`, evaluated at index 0. | `_extract_score` safely retrieves positive relevance class (`val[-1]`). |

---

## 11. Academic Foundations & Literature References

1. **Reciprocal Rank Fusion (RRF)**:
   - Cormack, G. V., Clarke, C. L., & Buettcher, S. (2009). *Reciprocal rank fusion outperforms Condorcet and individual rank learning methods.* Proceedings of the 32nd International ACM SIGIR Conference on Research and Development in Information Retrieval (SIGIR '09), 758–759. [DOI: 10.1145/1571941.1572114](https://doi.org/10.1145/1571941.1572114).
2. **Normalized Character Error Rate (CER)**:
   - Morris, A. C., Maier, V., & Green, P. (2004). *From WER and RIL to MER and WIL: improved evaluation measures for connected speech recognition.* Interspeech 2004.
   - Levenshtein, V. I. (1966). *Binary codes capable of correcting deletions, insertions, and reversals.* Soviet Physics Doklady.
