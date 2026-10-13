# LanceDB Vector Database & RAG Ingestion Engine

## 1. Executive Overview & Foundational Invariants

The AI Factory Knowledge Oracle and Validation subsystems utilize **LanceDB**—a high-performance, embedded, serverless vector database built natively on **Apache Arrow** and written in **Rust**. Operating entirely in-process without requiring external daemon processes, LanceDB enables zero-copy reads, SIMD-accelerated kNN distance computations, and disk-backed vector storage across local and distributed environments.

Within the pipeline DAG, LanceDB acts as the immutable ground-truth memory store for the Knowledge Oracle (`oracle_agent.py`), the Evidence Grounding Validator (`validator.py`), and the Architect-Oracle Deliberation Engine (`deliberate.py`). It unifies heterogeneous project artifacts—including source code repositories, technical documentation, academic papers, scanned PDFs, and live web scrapes—into a consolidated vector retrieval surface.

### Foundational Invariants
- **Schema Safety Invariant**: When appending new files to an existing table (`vectordb_overwrite: false`), `rag_manager.py` verifies that `source_type` and `language` columns exist in the Arrow schema, and that the vector dimension matches the active embedding model (`table.schema.field("vector").type.list_size == _dim`). If a legacy schema or dimension mismatch is detected, ingestion safely aborts with an actionable error rather than corrupting the database.
- **Query Vector Truncation Guard**: `_MAX_EMBED_CHARS = 6000`. When retrieving via `top_k`, the query text is truncated to 6,000 characters before embedding to prevent long debate prompts or attached code context from overflowing embedding model context windows (e.g. `sentence-transformers` or `BAAI/bge-m3`) and causing VRAM out-of-memory crashes.
- **Active Working File Exclusion & Path Normalization**: Any file listed under `target_files`, `extra_editable_files`, or `context_files_job` in the active phase is automatically excluded from ingestion scanning. In `rag_manager._walk_repo()`, all repository relative paths and exclusion patterns are normalized by replacing `\\` with `/`, and directory stems use `.rstrip("/\\")`. This guarantees that active file exclusion works identically on Windows and POSIX systems, preventing self-referential retrieval of actively mutated code.
- **Zero-RAG Bypass Mode**: If a phase configuration specifies `rag.collection_name: ""` (empty string or `[]`), the pipeline bypasses LanceDB vector ingestion and retrieval entirely. Both the Programmatic Oracle and Pre-Edit debates will rely strictly on the raw text contents of the files defined in `target_files` and `context_files_job` injected directly into the prompt.
- **Ingestion Lock & Single-Execution Invariant**: Vector database ingestion runs exactly once per phase. In `run_workflow.py`, the ingestion payload is attached exclusively to the first DAG task generated for the phase. Subsequent per-document tasks establish explicit dependency edges on this owner task, ensuring tables are fully built and compacted before any retrieval or debate execution begins.
- **Deterministic Naming & Sanitization Invariant**: In `rag_manager.table_name_for(doc_or_stem)`, table names are strictly sanitized using `re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("_")`. This guarantees that table identifiers comply with LanceDB naming restrictions while maintaining exact 1:1 parity with the query routing in `run_workflow.py` and `oracle_agent.py`.

### Academic Foundations
1. **Reciprocal Rank Fusion (RRF)**:
   - Cormack, G. V., Clarke, C. L., & Buettcher, S. (2009). *Reciprocal rank fusion outperforms Condorcet and individual rank learning methods.* Proceedings of the 32nd International ACM SIGIR Conference on Research and Development in Information Retrieval (SIGIR '09), 758–759. [DOI: 10.1145/1571941.1572114](https://doi.org/10.1145/1571941.1572114).
2. **Normalized Character Error Rate (CER)**:
   - Morris, A. C., Maier, V., & Green, P. (2004). *From WER and RIL to MER and WIL: improved evaluation measures for connected speech recognition.* Interspeech 2004.
   - Levenshtein, V. I. (1966). *Binary codes capable of correcting deletions, insertions, and reversals.* Soviet Physics Doklady.
3. **Syntax-Directed Code Chunking**:
   - Tree-sitter Language Pack: Abstract Syntax Tree (AST) grammar-based parsing for function, class, and method isolation without mid-token fragmentation.

---

## 2. System Topology & Lifecycle Flowcharts

The pipeline supports two distinct storage architectures configured via the `rag.batch` YAML toggle:

```text
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

### 2.1 `batch: true` (Unified Type-Routed Architecture)
- **Table Naming**: `<collection>_docs`, `<collection>_<repo>_code`, `<collection>_<repo>_docs`.
- **Execution**: All documents in the collection directory are embedded into a single unified table.
- **Corpus Type Partitioning & Filtering**: Ingestion partitions code and documentation files into `<collection>_<repo>_code` and `<collection>_<repo>_docs`. Setting `rag.type_filter` in YAML or `--type code|docs` on the CLI filters candidate tables during search, preventing code matches from crowding out documentation (or vice versa).
- **Search Mechanics**: When querying, `oracle_agent.py` executes a single vectorized kNN search over Apache Arrow contiguous memory. Because `len(per_table) == 1`, client-side RRF fusion is bypassed directly, feeding candidates straight to the Stage 2 Cross-Encoder.
- **Best Used For**: Software documentation, manuals, API specifications, and codebase repositories where global vector distance comparison across all files is required.

### 2.2 `batch: false` (Per-Document Table Architecture)
- **Table Naming**: Sanitized document stem (e.g. `paper_2024_momentum`, `macro_rates`).
- **Execution**: Each document or paper gets its own isolated LanceDB table.
- **Search Mechanics**: Vector search runs across each table independently. Candidates are merged using **Reciprocal Rank Fusion (RRF)**:
  $$\text{RRF\_Score}(d) = \sum_{t \in \text{Tables}} \frac{1}{60 + \text{rank}_t(d)}$$
- **Dynamic Recall Scaling**: To prevent candidate starvation when querying across many tables, Stage 1 recall scales dynamically:
  - In `oracle_agent.py`:
    $$\text{recall\_k}_{\text{oracle}} = \min\left(\max(k \times 4,\, 75,\, \text{len(tables)} \times 4),\, 150\right)$$
  - In `validator.py`:
    $$\text{recall\_k}_{\text{validator}} = \min\left(\max(k \times 4,\, 30,\, \text{len(tables)} \times 4),\, 100\right)$$
- **Deterministic Composite Tie-Breaking**: RRF scores tied at identical ranks are broken deterministically by `(-score, source_file, text_prefix)`, eliminating filesystem inode traversal variance.
- **Best Used For**: Multi-paper academic literature reviews, legal contracts, or distinct books where users need per-document targeting (`oracle --collection paper_stem`) and surgical single-document updates (`oracle --rm-table <name>`).

### 2.3 Multi-Format Ingestion DAG Flowchart
```text
[Raw Input Artifacts]
       │
       ├── Code Files (.py, .R, .js, .ts, .rs, .go, .c, .cpp)
       │         │
       │         └──► Tree-Sitter AST Chunking ──► [Symbol Metadata Extraction] ──► [LanceDB Append]
       │
       ├── Digital Documents (.pdf, .docx, .pptx, .xlsx, .html, .asciidoc)
       │         │
       │         ├──► Docling Subprocess (`docling_runner.py`)
       │         │         │
       │         │         ├── Success (chars > 100) ──► [Clean Markdown + Metadata] ──► [LanceDB Append]
       │         │         └── Fallback (scan / error) ──┐
       │         │                                       │
       │         └───────────────────────────────────────┼──► Rasterize Pages to PNG (150 DPI)
       │                                                 │           │
       ├── Scanned PDFs & Images (.png, .jpg, .webp) ────┘           ▼
       │                                                     Vision OCR API Call
       │                                                             │
       │                                                             ▼
       │                                                     CER Validation Gate
       │                                                      ├─ CER <= 0.05 ──► [Save <stem>.md] ──► [LanceDB Append]
       │                                                      └─ CER > 0.05  ──► Retry (up to 2x) ──► Embedded Fallback
       │
       └── Web Endpoints & URLs (via `rag_web.py` / `aider-oracle --add-web`)
                 │
                 ├── HEAD Request Sniff ──► application/pdf? ──► Direct Binary Download (.pdf)
                 ├── llms.txt Detection  ──► Manifest Links ──► Recursive Markdown Crawl (.md)
                 ├── Trafilatura Engine ──► HTML Extraction ──► Main Text & Tables (.md)
                 └── Playwright Engine  ──► Headless Browser ──► Rendered SPA Markdown (.md)
```

### 2.4 Two-Stage Retrieval Lifecycle Flowchart
```text
[User / Architect Query Prompt]
       │
       ├── Query Truncation Guard: input[:6000]
       │
       ├── Embedding Generation (`embed_texts` via local llama-server or litellm)
       │
       ▼
[Stage 1: Vector Search over LanceDB Tables]
       │
       ├── Single Table (`batch: true` or specific collection) ──► Top `recall_k` Candidates
       │
       └── Multi-Table (`batch: false` or collection = "*")
                 │
                 ├── kNN Cosine Search across N tables
                 └── Reciprocal Rank Fusion (RRF, c=60) with deterministic tie-breaking
                           │
                           ▼
                 Combined `recall_k` Candidates (default: 30 to 150)
                           │
                           ▼
[Stage 2: Cross-Encoder / Listwise Reranking]
       │
       ├── Local Native Listwise (`jinaai/jina-reranker-v3.5` via AutoModel.rerank())
       ├── Local Pairwise Cross-Encoder (`sentence_transformers.CrossEncoder`)
       └── Remote HTTP Endpoint (`/v1/rerank` or `/rerank`)
                 │ (Fail-open fallback to vector order on error)
                 ▼
       Final Top-K Chunks (`top_k = 5` default)
                 │
                 ▼
[Injected into Knowledge Oracle / Validator Prompt Context]
```

---

## 3. Technical Mechanics & Mathematical Formulations

### 3.1 Table Schema & Data Modeling
Every LanceDB table is defined via `lancedb.pydantic.LanceModel` with strict metadata typing ensuring byte-level portability and zero-copy Apache Arrow interoperability:

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

### 3.2 Tree-Sitter AST Code Chunking & Fallback Logic
Source code ingestion uses `tree-sitter-language-pack` to maintain syntactic boundaries. Chunks represent cohesive units of logic (classes, functions, methods) rather than arbitrary byte spans.

1. **Grammar Mapping (`_lang_for_ext`)**: Supported extensions include `.r` (r), `.py` (python), `.js` (javascript), `.ts` (typescript), `.cpp`/`.cc`/`.c`/`.h`/`.hpp` (cpp/c), `.go` (go), `.rs` (rust), `.java` (java), `.rb` (ruby), `.sh` (bash), and `.sql` (sql).
2. **Recursive Node Subdivision (`_ast_chunk`)**: The parser extracts top-level and nested constructs. Nodes smaller than `code_chunk_size` (default: 2000 characters) are buffered and flushed at logical end-points.
3. **Oversized Leaf Handling (`_text_split_fallback`)**: If a single AST construct exceeds `code_chunk_size` (e.g., a massive 500-line monolithic function):
   - **Multi-line Blocks**: Splits along newline boundaries preserving `overlap_lines = 3` lines of overlapping context while retaining symbol attribution (`identifier` or `name`).
   - **Single-Line Blocks (Minified code / long strings)**: Splits at character boundaries using an overlap of $\min(\lfloor\text{max\_chars} / 5\rfloor,\, 200)$ characters.

### 3.3 Atomic Fenced Code Block Chunking
For Markdown, RMarkdown, and documentation files, `rag_manager._chunk` utilizes `MarkdownHeaderTextSplitter` on headers (`#`, `##`, `###`) followed by `RecursiveCharacterTextSplitter`. 

To prevent broken syntax highlighting and incomplete code references, fenced blocks (``` ``` ``` or `~~~`) are treated as atomic tokens:
- If a fenced block is $\le 2 \times \text{chunk\_size\_chars}$, it is preserved intact in a single chunk.
- If it exceeds $2 \times \text{chunk\_size\_chars}$, the splitter breaks the interior content across line boundaries but deterministically injects matching opening and closing fences (` ``` ` ... ` ``` `) into every resulting slice.

### 3.4 Docling Multi-Format Extraction (`docling_runner.py`)
Digital PDFs, Office formats (`.docx`, `.pptx`, `.xlsx`), HTML, and AsciiDoc are parsed via `docling_runner.py` executed out-of-process via `uv run --isolated --with docling>=2.0.0`:
- **Document Metadata Header**: Extracts Title, Authors, Creation Date, and Subject, formatting them as a standardized Markdown YAML-like header block (`# Document Metadata`).
- **Table Preservation**: Extracts embedded tables directly into Markdown grid format (`| col1 | col2 |`).
- **Scan Detection Pre-Check**: In `rag_manager._ocr_to_markdown`, if `docling_do_ocr: false` is configured, PyMuPDF (`fitz`) inspects the PDF. If the total embedded text is $\le 100$ characters across the entire file, the document is classified as a pure image scan and Docling is bypassed in favor of the Vision OCR engine.

### 3.5 Vision OCR & Character Error Rate (CER) Validation Gate
For pure scans and raw images, pages are rasterized to PNGs via PyMuPDF at $150\text{ DPI}$. Page images are processed through the configured `ocr_agent`:
- **Alphanumeric Normalization**:
  $$\text{norm}(s) = \text{regex\_replace}(s,\, \text{"[^a-z0-9]"},\, \text{""})$$
- **Normalized CER Equation**:
  $$\text{CER}(\text{ref}, \text{hyp}) = \frac{\text{LevenshteinDistance}(\text{norm}(\text{ref}),\, \text{norm}(\text{hyp}))}{\text{Length}(\text{norm}(\text{ref}))}$$
- **Retry & Recovery Logic**: If $\text{CER} > \text{cer\_threshold}$ ($0.05$), page OCR is retried up to `ocr_max_retries` (default: 2). If $\text{CER}$ remains $> 0.40$ on a PDF with an existing text layer, the engine discards the corrupted OCR output and recovers the native text layer.

### 3.6 Multimodal Trade-off: Docling vs. Vision LLMs

| Feature | Structural Parsing (`use_docling: true`) | Vision-Language Models (`use_docling: false`) |
| :--- | :--- | :--- |
| **Engine** | Docling / PyMuPDF OCR | GLM-OCR, Qwen2-VL, Gemini, Unlimited-OCR |
| **Primary Strength** | Perfect table formatting, fast extraction, zero hallucination | Translates charts, diagrams, and visual figures into text |
| **Primary Weakness** | Blind to image content (`<!-- image -->` stubs) | Slower, potential minor transcription noise on dense text |
| **Optimal Use Case** | Code manuals, specifications, financial reports | Slide decks, scanned textbooks with diagrams, architecture schematics |

### 3.7 Configuring Local Vision Models (`llama.cpp`)
The AI Factory is completely decoupled from any specific Vision model. It sends standard OpenAI-compatible image payloads to the `ocr_api_base`. To use advanced local OCR models via `llama-server`:

1. **The Vision Projector (`mmproj`)**: Local VLMs require *two* files. You must configure your `llama-server` (e.g., in `models.ini`) to load both the main model and the vision projector:
   ```ini
   [unlimited-ocr:latest]
   model = /path/to/Unlimited-OCR-Q4_K_M.gguf
   mmproj = /path/to/mmproj-Unlimited-OCR-F16.gguf
   ```
2. **Prompt Tuning**: Different models require highly specific instruction prompts. You must override the `ocr_prompt` in your `.env.yml` to match the model's training:

| Model Family | Recommended `ocr_prompt` Override in `.env.yml` |
| :--- | :--- |
| **GLM-OCR** / **Qwen2-VL** | `"Extract text, tables, math, code, and documentation into clean Markdown. Preserve all structural integrity."` (Default) |
| **Unlimited-OCR** / **DeepSeek-OCR** | `"<|grounding|>Convert the document to markdown."` |
| **Plain Text (Unlimited-OCR)** | `"Free OCR."` (Extracts raw text without layout/bounding boxes) |

### 3.8 Vector Distance Formulation & Score Calibration
LanceDB vector index queries with `metric="cosine"` compute the cosine distance between the normalized query vector $u$ and chunk vector $v$:
$$\text{\_distance}(u, v) = 1 - \frac{u \cdot v}{\|u\|_2 \|v\|_2} = 1 - \cos(\theta)$$
To maintain mathematical consistency with downstream ranking metrics, `validator.py` and `oracle_agent.py` invert distance to standard cosine similarity:
$$\text{sim}(u, v) = 1.0 - \text{\_distance}(u, v) \in [-1.0, 1.0]$$

### 3.9 Reciprocal Rank Fusion (RRF) & Dynamic Candidate Recall
When querying across multiple tables (`batch: false` or multi-corpus search), `_rrf_merge` fuses ranked candidate lists using Reciprocal Rank Fusion:
$$\text{RRF\_Score}(d) = \sum_{t \in \text{Tables}} \frac{1}{c + \text{rank}_t(d)}$$
where $c = 60$ is the standard smoothing constant, and $\text{rank}_t(d)$ is the 0-indexed rank of chunk $d$ in table $t$.

- **Deterministic Secondary Sort**: To prevent non-deterministic sorting across platforms with varying filesystem inode iteration orders, ties in $\text{RRF\_Score}$ are broken deterministically by:
  $$\text{SortKey}(d) = \left(-\text{RRF\_Score}(d),\, \text{source\_file}(d),\, \text{text}(d)[:64]\right)$$
- **Dynamic Recall Depth ($recall\_k$)**:
  - In `oracle_agent.py`:
    $$\text{recall\_k}_{\text{oracle}} = \min\left(\max(k \times 4,\, 75,\, \text{len(tables)} \times 4),\, 150\right)$$
  - In `validator.py`:
    $$\text{recall\_k}_{\text{validator}} = \min\left(\max(k \times 4,\, 30,\, \text{len(tables)} \times 4),\, 100\right)$$

### 3.10 Two-Stage Reranking Architecture
Candidates retrieved in Stage 1 ($recall\_k$) pass to Stage 2 reranking before context injection:
1. **Native Listwise Cross-Encoders (e.g. `jinaai/jina-reranker-v3.5`)**:
   - Detected automatically via `AutoConfig` inspecting `auto_map` and `architectures` for the `Ranking` keyword.
   - Loaded using `transformers.AutoModel.from_pretrained(..., trust_remote_code=True)`.
   - Scores the entire candidate pool jointly in a single forward pass via `instance.rerank(query, docs)` using the trained MLP projector.
2. **Pairwise Cross-Encoders (e.g. `BAAI/bge-reranker-large`, `ms-marco-MiniLM-L-6-v2`)**:
   - Loaded via `sentence_transformers.CrossEncoder`.
   - Evaluates pairs $[(q, d_1), (q, d_2), \dots]$ and maps output logits to relevance scores.
3. **Remote HTTP Reranker**:
   - Queries `POST {ranking_api_base}/v1/rerank` (with automatic fallback to `{ranking_api_base}/rerank` on 404).
   - If the remote server fails or returns $\ge 400$, the engine falls back seamlessly to the in-process local reranker without failing the pipeline.

### 3.11 Memory Bounds, Compaction & Indexing Thresholds
- **Buffered Chunk Ingestion (`FLUSH_CHUNK_THRESHOLD = 2000`)**: During ingestion of large codebases, chunks accumulate in memory. Once 2,000 chunks are queued, vectors are generated in batches of 8 and appended to LanceDB, bounding peak RAM and persisting progress against interruption.
- **Table Compaction (`table.optimize()`)**: LanceDB writes append-only fragments. After table flushes or row deletions (`_remove_file`), `table.optimize()` merges fragments into contiguous Arrow batches to prevent disk fragmentation and read degradation.
- **Index Threshold (`IVF_PQ_MIN_ROWS = 50000`)**:
  - Tables $\le 50,000$ rows: Flat exact kNN search via CPU SIMD/AVX-512 ($<15\text{ms}$ latency, 100% recall).
  - Tables $> 50,000$ rows: LanceDB builds an `IVF_PQ` index with cosine distance (`table.create_index(metric="cosine")`), trading marginal precision for sub-millisecond retrieval.

---

## 4. Exhaustive CLI Invocations & Command Matrix

The AI Factory provides dedicated command-line utilities for querying, maintaining, and cleaning LanceDB vector stores:

### 4.1 `aider-oracle` Command Matrix

| Invocation | Mode / Category | Description | Exit Codes |
| :--- | :--- | :--- | :--- |
| `aider-oracle "<question>"` | Direct Query | Queries the knowledge base with the question using default `top_k` retrieval. | `0`: Success |
| `aider-oracle --file <path> ["<note>"]` | File Query | Reads query text from `<path>` with optional inline note. Displays compact reference in logs. | `0`: Success, `1`: File not found |
| `aider-oracle --collection <name\|path> "<q>"` | Targeted Query | Directs search to a specific collection name or external filesystem path. | `0`: Success |
| `aider-oracle --mode no_retrieve "<q>"` | Pure LLM | Bypasses vector retrieval; queries the Oracle model directly without RAG context. | `0`: Success |
| `aider-oracle --mode full_document "<q>"` | Dump Query | Dumps the entire text of the collection table into context without vector filtering. | `0`: Success |
| `aider-oracle --type code\|docs "<q>"` | Type-Filtered | Narrows candidate tables to only `<coll>_<repo>_code` or `<coll>_<repo>_docs`. | `0`: Success |
| `aider-oracle --no-rag "<q>"` | No-RAG Override | Forces `no_retrieve` mode, bypassing all vector searches. | `0`: Success |
| `aider-oracle --no-rerank "<q>"` | Retrieval Override | Disables Stage 2 cross-encoder reranking, returning raw vector/RRF order. | `0`: Success |
| `aider-oracle --recall-k <N> "<q>"` | Retrieval Override | Sets Stage 1 candidate pool depth (e.g. `--recall-k 100`). | `0`: Success |
| `aider-oracle --claims-only "<q>"` | Validation | Validates generated response against knowledge base via `validator._run_claims_only`. | `0`: Success, `1`: Unverified claims |
| `aider-oracle --debate [code\|review] "<q>"` | Deliberation | Launches interactive Architect-Oracle debate (default: `code`). | `0`: Success, `1`: Error |
| `aider-oracle --debate --loops 5 --rounds 2 "<q>"` | Deliberation | Configures 5 loops per round across 2 debate rounds. | `0`: Success |
| `aider-oracle --debate --persist "<q>"` | Deliberation | Continues exploring audit layers even after provisional consensus is reached. | `0`: Success |
| `aider-oracle --oracle-persona <path> "<q>"` | Persona Directives | Injects custom persona guidelines into the Oracle's prompt and evaluation contract. | `0`: Success |
| `aider-oracle --architect-persona <path> "<q>"` | Persona Directives | Injects custom persona guidelines into the Architect's prompt. | `0`: Success |
| `aider-oracle --list` | Maintenance | Lists all LanceDB tables in the active database directory. | `0`: Success |
| `aider-oracle --list-files` | Maintenance | Scans all tables in collection and prints unique ingested source files and chunk counts. | `0`: Success, `1`: Error |
| `aider-oracle --add-file <path ...>` | Maintenance | Incrementally ingests one or more files into the active collection. | `0`: Success, `1`: Ingest error |
| `aider-oracle --add-file <path> --no-rag` | Maintenance | Performs OCR and generates Markdown sidecars without indexing into LanceDB. | `0`: Success |
| `aider-oracle --add-table <dir ...>` | Maintenance | Copies an entire directory and recursively ingests all code and documentation files. | `0`: Success, `1`: Ingest error |
| `aider-oracle --add-web <url ...>` | Maintenance | Fetches, converts, and indexes web URLs or sitemaps into the collection. | `0`: Success, `1`: Fetch error |
| `aider-oracle --add-web --file urls.txt -w 8` | Maintenance | Concurrently ingests URLs listed in a text file using 8 worker threads. | `0`: Success |
| `aider-oracle --rm-file <filename>` | Maintenance | Surgically deletes all chunks for `<filename>` across all tables and optimizes tables. | `0`: Success, `1`: Not found |
| `aider-oracle --rm-table <table_name>` | Maintenance | Drops `<table_name>` completely from the active database. | `0`: Success, `1`: Not found |
| `aider-oracle --rm-db` | Maintenance | Wipes the vector database directory (`lancedb/`) while preserving raw markdown and images. | `0`: Success, `1`: Error |
| `aider-oracle --clear [oracle]` | Session Reset | Wipes active session memory, cost sidecars, and debate transcripts. | `0`: Success |

### 4.2 `aider-clean-lancedb` Maintenance Utility

The `aider-clean-lancedb` script cleans ephemeral artifacts across POSIX and Windows systems:
```bash
# Clean artifacts for collection 'project_knowledge' in current working repo
aider-clean-lancedb project_knowledge

# Clean artifacts for collection targeting an explicit project path
aider-clean-lancedb project_knowledge --project-dir /home/user/workspace/repo
```

- **Deletes**: `.aider_factory/markdown/lanceDB/<collection>/images/` (page raster caches).
- **Empties**: `.aider_factory/logs/validations/` and `.aider_factory/logs/debates/`.
- **Preserves**: `.aider_factory/markdown/lanceDB/<collection>/lancedb/` (Vector tables), raw source PDFs/documents, and `.md` sidecars.

### 4.3 Smart Filesystem Collection Path Resolution
Both the CLI (`--collection <path>`) and YAML configuration (`rag.collection_name`) resolve filesystem paths dynamically:
1. **Explicit `lancedb` Directory**: If `/data/corpus/lancedb` is provided, collection resolves to `corpus` and the DB directory resolves to `/data/corpus/lancedb`.
2. **Parent Directory with `lancedb` Subfolder**: If `/data/corpus` is provided and contains a `lancedb/` directory, the subfolder is automatically bound.
3. **Local Collection Identifier**: If a bare string `my_docs` is provided, it resolves to `.aider_factory/markdown/lanceDB/my_docs/lancedb`.
4. **All paths** are normalized using POSIX-style forward slashes (`/`), guaranteeing cross-platform consistency.

---

## 5. Configuration Schema & YAML Knobs

LanceDB and RAG ingestion parameters are configured within `.env.yml` under the `endpoints`, `models`, and `rag` blocks:

```yaml
endpoints:
  embed_api_base: "http://192.168.100.2:8081/v1" # Local embedding server (or null for cloud)
  ocr_api_base: "http://192.168.100.2:8081/v1"   # Local vision server (or null for cloud)
  ranking_api_base: null                         # Remote reranker endpoint (null = local in-process)
  rag_agent_api: "http://192.168.100.2:8081/v1"  # Optional endpoint for Oracle agent

phases:
  - name: "Core_Implementation"
    enabled: true
    models:
      embed_model: "BAAI/bge-m3"                 # HuggingFace identifier or cloud model name
      embed_backend: "sentence-transformers"     # "sentence-transformers" | "openai"
      ocr_agent: "glm-ocr-f16:LATEST"            # Vision model for page OCR
      ranking_agent: "jinaai/jina-reranker-v3.5" # Listwise or cross-encoder reranker
      rag_agent: "gemini/gemini-2.5-flash"       # Oracle LLM side-agent model

    rag:
      collection_name: "project_knowledge"       # Collection directory name or absolute path
      run_ocr_rag: true                          # Trigger automated ingestion in phase DAG
      batch: true                                # true = unified table, false = per-document tables
      type_filter: null                          # Filter: null (fuse all), "code", or "docs"
      retrieval_mode: top_k                      # top_k | no_retrieve | full_document
      recall_k: 75                               # Stage 1 vector candidates before rerank
      top_k: 5                                   # Stage 2 final context chunks to inject
      chunk_size_chars: 800                      # Markdown/text chunk target size
      chunk_overlap_chars: 100                   # Overlap between consecutive text chunks
      code_chunk_size: 2000                      # Tree-Sitter AST code chunk target size
      cer_threshold: 0.05                        # Max Character Error Rate before retry
      ocr_max_retries: 2                         # OCR attempts per page
      ocr_parallel: 8                            # Concurrent OCR workers (threads)
      ocr_max_tokens: 4096                       # Max tokens in OCR LLM completion
      ocr_prompt: "Extract the text, tables, and mathematical formulas from this page into clean Markdown. Preserve all structural integrity."
      use_docling: true                          # Enable Docling digital document conversion
      docling_do_ocr: true                       # Enable Docling native OCR for embedded scans
      docling_timeout: 300                       # Timeout in seconds for Docling subprocess
      vectordb_overwrite: false                  # false = incremental cache-hit, true = full rebuild
      working_repo: "my_project"                 # Target repo name to apply code exclusions
```

### Detailed YAML Parameter Dictionary

| Key | Type | Default | Scope | Description |
| :--- | :--- | :--- | :--- | :--- |
| `embed_api_base` | `str \| null` | `null` | `endpoints` | Base URL for OpenAI-compatible embedding servers. If `null`, uses litellm or local backend. |
| `ocr_api_base` | `str \| null` | `null` | `endpoints` | Base URL for OpenAI-compatible vision OCR server. If `null`, routes via cloud provider key. |
| `ranking_api_base`| `str \| null` | `null` | `endpoints` | Base URL for remote `/v1/rerank` service. If `null`, runs reranker locally in-process. |
| `embed_model` | `str` | `"BAAI/bge-m3"` | `models` / `rag` | Embedding model identifier (HuggingFace repo or cloud identifier). |
| `embed_backend` | `str` | `"sentence-transformers"` | `rag` | Engine: `"sentence-transformers"` (local cache) or `"openai"` (HTTP/litellm). |
| `collection_name`| `str` | `"knowledge"` | `rag` | Target folder name in `.aider_factory/markdown/lanceDB/` or filesystem path. |
| `batch` | `bool` | `true` | `rag` | `true`: unified collection tables; `false`: isolated per-document tables. |
| `type_filter` | `str \| null`| `null` | `rag` | Restricts search to `"code"` (`*_code` tables) or `"docs"` (`*_docs` tables). |
| `retrieval_mode` | `str` | `"top_k"` | `rag` | Retrieval strategy: `"top_k"`, `"no_retrieve"`, or `"full_document"`. |
| `recall_k` | `int` | `30` (or `75`) | `rag` | Number of candidate chunks retrieved in Stage 1 prior to reranking. |
| `top_k` | `int` | `5` | `rag` | Number of final top-ranked chunks returned after Stage 2 reranking. |
| `chunk_size_chars`| `int` | `1500` | `rag` | Target character size for documentation chunks. |
| `chunk_overlap_chars`| `int` | `300` | `rag` | Overlap character count between consecutive document chunks. |
| `code_chunk_size` | `int` | `2000` | `rag` | Character limit for Tree-Sitter AST code block chunks. |
| `cer_threshold` | `float` | `0.05` | `rag` | Normalized Character Error Rate threshold ($5\%$ error tolerance). |
| `ocr_parallel` | `int` | `1` | `rag` | Number of concurrent threads for page OCR requests. |
| `use_docling` | `bool` | `true` | `rag` | Fast-path digital document parser (`docling>=2.0.0`). |
| `vectordb_overwrite`| `bool` | `false` | `rag` | If `false`, skips existing tables (cache hit); if `true`, rebuilds from scratch. |

---

## 6. Operational Edge Cases, Failure Modes & Telemetry

### 6.1 LanceDB Table Listing API Compatibility
LanceDB v0.4+ introduced structured table response wrappers. The pipeline ensures dual-version compatibility via attribute inspection:
```python
_names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
available_tables = list(getattr(_names, "tables", _names))
```

### 6.2 Offline-First Invariant for Embeddings & Rerankers
To prevent unexpected network failures in air-gapped or compute-cluster environments:
- `SentenceTransformer` and `CrossEncoder` instantiations attempt `local_files_only=True` first.
- Only if the local HuggingFace cache lacks the weights does it trigger a cold-start download (`local_files_only=False`).

### 6.3 Remote Reranker Fail-Open Fallback
If `ranking_api_base` is configured but the remote server is unreachable, times out, or returns HTTP 400/404/500:
1. The error is intercepted and logged to `stderr`.
2. The pipeline attempts to load the model locally in-process via `_load_local_reranker`.
3. If local loading fails, the pipeline fails open and returns candidates in raw Stage 1 vector/RRF order without halting execution.

### 6.4 Windows File Locking Workaround (`[WinError 32]`)
On Windows platforms, active Python processes hold mandatory file locks on memory-mapped Apache Arrow files. Calling `aider-oracle --rm-db` handles this by:
```python
import gc
# Dereference active table and database pointers
del tbl, db
gc.collect() # Force garbage collection of memory-mapped file handles
shutil.rmtree(db_dir)
```

### 6.5 Telemetry & Cost Tracking Integration
When cloud models are used for embeddings or OCR (e.g. `gemini/text-embedding-004` or `gemini/gemini-2.5-flash`), token consumption and monetary costs are tracked via `cost_tracker.py`:
- `litellm_cost_line()` logs prompt and completion tokens along with message and session costs directly to `stderr`.
- Output formatting matches Aider conventions: `Tokens: 12.4k sent, 0 received. Cost: $0.0012 message, $0.0450 session.`
- Logs are automatically aggregated into session run totals at pipeline completion via `aggregate_costs.py`.

### 6.6 Comprehensive Troubleshooting Matrix

| Symptom / Error Signature | Root Cause | Exact Resolution |
| :--- | :--- | :--- |
| **`[knowledge base unavailable: ...]`** | Embedding endpoint unreachable or local server model evicted. | Verify server status (`curl <embed_api_base>/v1/models`). Check if another model evicted the embedding weights. |
| **`400 Bad Request: context size exceeded`** | Query text exceeds embedding model context limit. | Fixed by `_MAX_EMBED_CHARS = 6000` truncation. Ensure custom queries do not inject oversized payloads. |
| **`ImportError: lancedb`** | Script invoked with system Python instead of package environment. | Launch using `uv run` or standard `.aider_factory/bash/oracle` wrapper script. |
| **`old-schema table ... (pre-metadata)`** | LanceDB table created before metadata schema migration. | Re-ingest with `vectordb_overwrite: true` in `.env.yml` or run `aider-oracle --rm-db`. |
| **`dim mismatch on '<table_name>'`** | Embedding model changed (e.g., from 1024-dim BGE-M3 to 768-dim model). | Table cannot store mixed vector dimensions. Drop table with `aider-oracle --rm-table <name>` and re-index. |
| **`404 Not Found on /v1/rerank`** | Reranker endpoint served at `/rerank` rather than `/v1/rerank`. | Handled automatically: engine retries at `/rerank`. Verify endpoint path if server is custom. |
| **`[rerank] warning: remote rerank failed`** | Remote reranker timed out or crashed under load. | Engine fails open and returns Stage 1 vector/RRF order. Inspect server GPU memory. |
| **Chat template ValueError (`sentence-transformers >= 3.0`)** | LLM-based reranker lacks standard query/document Jinja template. | Engine injects standard `<Query>` / `<Document>` prompt template automatically. |
| **Padding token crash during batch prediction** | Reranker tokenizer missing `pad_token`. | Engine automatically assigns `pad_token = eos_token` and synchronizes `pad_token_id`. |
| **Inverted ranking (irrelevant chunks ranked #1)** | Cross-encoder outputs 2D logits `[neg, pos]` evaluated at index 0. | `_extract_score` safely retrieves positive class at index -1 (`val[-1]`). |
| **`[WinError 32] Access denied on _remove_db()`** | Windows OS lock on open memory-mapped Arrow files. | Explicitly dereference table variables and trigger `gc.collect()` before removing directory. |
| **Docling hangs or runs slowly on scanned PDFs** | Docling attempting OCR on complex scans with low resources. | Set `docling_do_ocr: false` to allow PyMuPDF text pre-check to route scans to Vision OCR. |
| **`[sitemap] XML parse error for <url>`** | Sitemap returns non-standard or HTML error page. | Harvester automatically falls back to `robots.txt` and `llms.txt` extraction. |
