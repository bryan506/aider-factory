# `aider-oracle` — Knowledge Oracle & RAG Retrieval Engine

## 1. Executive Overview & Foundational Invariants

`aider-oracle` serves as the Tier-2a Knowledge Oracle and retrieval-augmented verification side-agent in the AI Factory DAG pipeline. Designed to eliminate context bloat and prevent model hallucination during code editing, literature reviews, and system planning, `aider-oracle` retrieves, reranks, and synthesizes domain knowledge on demand while enforcing strict evidence grounding.

### Core Architectural Role & Execution Modalities

Within the pipeline DAG, `aider-oracle` decouples dense knowledge retrieval from generative execution. Rather than overloading primary code-editing models (the Architect and Editor) with multi-megabyte document context or raw AST libraries, the Oracle acts as an external expert memory and adversarial referee.
For multi-turn adversarial deliberation, consensus arbitration, and technical specification formulation, see [Knowledge Oracle Deliberation & Debate](aider_oracle_debate.md).

The subsystem operates under three distinct execution modalities:

1. **Interactive RAG Side-Agent (`/run aider-oracle "<question>"`)**:
   - Executed inside active Aider coding sessions by human engineers or autonomously by the Architect via `--suggest-shell-commands`.
   - Resolves mathematical formulas, domain definitions, algorithm contracts, and framework patterns on demand.
   - Preserves primary Aider token budgets by returning concise, grounded answers rather than injecting entire files.
2. **Programmatic Document Synthesizer (`start_job: true` / `--auto` / `--job`)**:
   - Executes autonomously outside of Aider sessions to ingest literature collections, query templates, and generate comprehensive research documents or reviews directly to disk.
   - Evaluates either entire LanceDB tables (`full_document: true`) or semantic sub-regions (`top_k: N`).
3. **Knowledge Base Maintenance Suite (`--add-file`, `--add-table`, `--add-web`, `--rm-*`, `--list*`)**:
   - Manages LanceDB vector databases directly from the command line.
   - Executes incremental vector embeddings, performs surgical file and table chunk deletions, crawls XML sitemaps and `llms.txt` manifests, and orchestrates multi-worker web ingestion.

### Foundational Invariants

The runtime architecture of `aider-oracle` enforces six non-negotiable guarantees:

* **Strict Stream Separation (Stdout Cleanliness)**:
  - Generated answers, database table listings, and final synthesized outputs are printed exclusively to standard output (`stdout`).
  - All library logging (LiteLLM, HuggingFace, PyTorch, LanceDB), progress bars, source chunk citations (`[source: doc | file:lines]`), and token/cost accounting summaries are piped strictly to standard error (`stderr`).
  - *Invariant Target*: Prevents outer agents running under Aider `/run` from ingesting telemetry tokens, chunk metadata, or HTTP progress output into their primary conversation contexts.
* **Reactive Judge Contract**:
  - The Oracle acts strictly as an evidence-grounded critic, synthesizer, and information retrieval specialist; it never modifies repository source files or commits code changes directly.
  - The Oracle provides source-grounded critiques and evaluations on demand without writing code changes directly.
* **KV-Cache Prefix Conservation**:
  - Deliberation prompts inject static context files and LanceDB knowledge base chunks strictly on Turn 0.
  - Turns $1 \dots N$ append only delta proposals and critique end-lines, maintaining immutable byte-parity prefixes across multi-turn interactions to guarantee high LiteLLM and hardware KV-cache hit rates.
* **Offline-First Local Reranking**:
  - Local rerankers strictly attempt `local_files_only=True` first, guaranteeing zero external network calls and preventing HuggingFace telemetry transmission during offline execution. Network downloads are permitted only during initial cold-start model provisioning.
* **Zero-RAG Bypass**:
  - Setting `ORACLE_COLLECTION=""` or passing `--no-rag` completely bypasses LanceDB vector retrieval. The Oracle operates as a pure LLM reasoning engine over prompt context without vector search overhead.
* **Isolated State Decoupling**:
  - Ephemeral session artifacts (`.oracle_session.json`, `.oracle_debate_session.json`) are decoupled from persistent repository state and isolated per pipeline run via session sidecars, eliminating cross-turn and cross-phase state contamination.

---

## 2. System Topology & Lifecycle Flowcharts

### End-to-End Query & Retrieval Lifecycle

The following diagram illustrates the execution flow of an `aider-oracle` invocation, from CLI argument resolution through two-stage retrieval, prompt formatting, LLM completion, and stream separation:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              AIDER-ORACLE QUERY LIFECYCLE                              │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                         [CLI Invocations / /run hook]
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ Parameter & Env Discovery │
                        │  (_ensure_oracle_config)  │
                        └───────────────────────────┘
                                      │
                        ┌─────────────┴─────────────┐
                        ▼                           ▼
              [--no-rag / Pure LLM]       [RAG Vector Search]
                        │                           │
                        │           ┌───────────────┴───────────────┐
                        │           ▼                               ▼
                        │   [Single Collection]            [batch: true (RRF)]
                        │   Target single table           Query *_code & *_docs
                        │           │                               │
                        │           └───────────────┬───────────────┘
                        │                           │
                        │                           ▼
                        │               ┌───────────────────────┐
                        │               │ Candidate Pool Recall │
                        │               │  (k_recall = 75-150)  │
                        │               └───────────────────────┘
                        │                           │
                        │                           ▼
                        │               ┌───────────────────────┐
                        │               │   Two-Stage Rerank    │
                        │               │ (Jina / CrossEncoder) │
                        │               └───────────────────────┘
                        │                           │
                        │                           ▼
                        │               ┌───────────────────────┐
                        │               │ Top-K Chunks Selected │
                        │               └───────────────────────┘
                        │                           │
                        └─────────────┬─────────────┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ XML Prompt Assembly       │
                        │ <knowledge_base>+<question│
                        └───────────────────────────┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ LiteLLM Model Completion  │
                        │  (Streaming / Reasoning)  │
                        └───────────────────────────┘
                                      │
                        ┌─────────────┴─────────────┐
                        ▼                           ▼
               [stdout (Clean)]            [stderr (Telemetry)]
               • Answer Content            • Source Citations
               • Output JSON               • Token & Cost Line
               • Clean Table Lists         • Execution Timers
```

### Knowledge Base Ingestion & Maintenance Flow

The maintenance pipeline supports document rasterization, web scraping, and vector database modification:

```text
                     KNOWLEDGE BASE MAINTENANCE PIPELINE
                                      │
      ┌───────────────────────────────┼───────────────────────────────┐
      ▼                               ▼                               ▼
[--add-file / --add-table]       [--add-web]                     [--rm-* Subcommands]
Target local PDFs, MD, Code     Fetch URLs, sitemaps, llms.txt  Surgical deletions
      │                               │                               │
      ▼                               ▼                               ▼
[Format Sniffing]               [Trafilatura / Playwright]       [LanceDB Table Ops]
PDF -> PyMuPDF / Docling        Extracts Markdown & clean text   tbl.delete(where=...)
Code -> Tree-Sitter AST               │                          db.drop_table(...)
Text -> LangChain Markdown            │                          rmtree(lancedb/)
      │                               │                               │
      └───────────────────────┬───────┘                               ▼
                              │                               [Database Cleaned]
                              ▼
                 [Dense Vector Embedding]
                 sentence-transformers / OpenAI
                              │
                              ▼
                 [LanceDB Table Append]
                 Optimized table append
                 Auto ANN Index (>50k rows)
```

---

## 3. Technical Mechanics & Mathematical Formulations

### Reciprocal Rank Fusion (RRF) Formulation

When multi-table batch querying is enabled (`batch: true`), the Oracle retrieves candidates across code tables (`<coll>_<repo>_code`), documentation tables (`<coll>_<repo>_docs`), and general top-level doc tables (`<coll>_docs`). To deterministically interleave and rank these independent hit lists without score normalization artifacts, `aider-oracle` applies Reciprocal Rank Fusion:

$$RRF(d) = \sum_{t \in T} \frac{1}{c + rank_t(d)}$$

Where:
- $T$ is the set of queried LanceDB tables.
- $rank_t(d)$ is the 0-indexed ordinal rank of chunk $d$ within table $t$.
- $c = 60$ is the constant damping factor designed to reduce sensitivity to outlier high rankings in small candidate lists.

#### Deterministic Deduplication & Tie-Breaking
Chunks across tables are identified by a composite deduplication key:

$$\text{Key}(d) = \left( \text{source\_file}, \; \text{text}[:64] \right)$$

To eliminate non-deterministic ordering caused by differing filesystem traversal or floating-point variance across platforms, secondary and tertiary sort keys are strictly enforced:

$$\text{SortOrder}(d) = \left( -RRF(d), \; \text{source\_file}, \; \text{text}[:64] \right)$$

---

### Vector Space Similarity & Retrieval Metrics

LanceDB tables store dense embeddings generated via `embed_texts` ($d$-dimensional vectors normalized to unit length). The cosine similarity metric between the query vector $q$ and document chunk vector $v$ is calculated as:

$$Sim_{\cos}(q, v) = \frac{q \cdot v}{\|q\|_2 \|v\|_2} = 1 - Dist_{\cos}(q, v)$$

When dense vectors are $L_2$-normalized prior to storage, the distance metric simplifies to Euclidean dot product:

$$Dist_{\cos}(q, v) = 1 - q^T v$$

The candidate recall pool depth $k_{recall}$ is dynamically calculated based on the requested top-$k$ and the number of active tables:

$$k_{recall} = \max \left( k \times 4, \; \min(75, \; |T| \times 4), \; 150 \right)$$

---

### Two-Stage Reranking Engine

Candidates retrieved from vector search ($k_{recall}$ items) pass through a cross-encoder reranking stage (`_rerank_chunks`). `aider-oracle` dynamically inspects model architecture metadata to route between two distinct reranking paradigms:

#### 1. Native Listwise Rerankers (`JinaForRanking`)
Models in the Jina v3 family (e.g., `jinaai/jina-reranker-v3.5`) employ custom architectures registered via `AutoConfig.auto_map`:
- **Execution Mechanism**: Instantiated using `transformers.AutoModel.from_pretrained(model, trust_remote_code=True)`.
- **Mathematical Operation**: Unlike standard classification heads, listwise models pass the query and all candidate documents through shared transformer representations and an MLP projection head to compute a joint listwise ranking matrix in a single forward pass:

$$\hat{y} = \text{Softmax}\left(\text{MLP}\left(\mathbf{H}_{query} \otimes \mathbf{H}_{docs}\right)\right)$$

- **Safety Invariant**: Native listwise rerankers are strictly barred from being loaded via `sentence_transformers.CrossEncoder`. Loading via `CrossEncoder` forces `AutoModelForSequenceClassification`, discarding the MLP projection layers and initializing a random classification head, resulting in completely corrupted scoring.

#### 2. Pairwise Cross-Encoders
Standard cross-encoders (e.g., `BAAI/bge-reranker-large`, `cross-encoder/ms-marco-MiniLM-L-6-v2`) process query-document pairs individually:
- **Execution Mechanism**: Instantiated via `sentence_transformers.CrossEncoder`.
- **Scoring**: Computes pairwise scalar logits:

$$Score(q, d_i) = \sigma\left(\mathbf{W}^T \text{BERT}([CLS] \circ q \circ [SEP] \circ d_i \circ [SEP])\right)$$

#### 3. Remote HTTP Reranker Protocol
When `ORACLE_RANKING_API_BASE` is defined, the Oracle dispatches a JSON POST payload to `${ORACLE_RANKING_API_BASE}/v1/rerank` (falling back to `/rerank`):

```json
{
  "model": "jina-reranker-v3.5",
  "query": "query string",
  "documents": ["chunk text 1", "chunk text 2"],
  "top_n": 5
}
```

If the remote HTTP endpoint is unreachable or returns a non-200 status code, execution automatically falls through to the in-process local reranker without failing the pipeline.

---

### Query Truncation Mechanics (`_MAX_EMBED_CHARS`)

When executed in debate mode or with large `--file` payloads, prompts frequently contain multi-file source code, test failure traces, and architect proposals exceeding 30,000 characters. Passing such payloads directly to local embedding models (e.g., `BAAI/bge-m3` or local `llama-server` endpoints) causes context overflow or CUDA Out-Of-Memory (OOM) faults.

The Oracle strictly enforces a 6,000-character ceiling prior to vector embedding:

$$\text{query}_{\text{embed}} = \text{prefix} + \text{query}[:6000]$$

This captures the directive and primary structural code while staying well within the embedding model's context capacity.

---

### Claim Grounding Verification Mechanics (`validator.py` / `--claims-only`)

When `--claims-only` is active or `ORACLE_CLAIMS_ONLY=1` is exported, generated Oracle answers undergo immediate claim validation against LanceDB chunks:

1. **Paragraph Extraction**: Strips code blocks, HTML tags, and markdown headers, splitting output into discrete claims $C = \{c_1, c_2, \dots, c_m\}$.
2. **Candidate Retrieval**: For each paragraph $c_i$, queries LanceDB for top-$k$ contextual chunks $D_i$.
3. **Entailment Scoring**:
   - If `GROUNDING_AGENT_MODEL` is configured (e.g., MiniCheck via `minicheck_server.py`), computes sentence-level factual entailment probability:
     $$P(Supported \mid c_i, D_i) \ge \tau_{entail} \quad (\text{default: } 0.5)$$
   - Otherwise, computes vector cosine similarity between claim and retrieved chunks:
     $$Sim_{\cos}(c_i, D_i) \ge \tau_{region} \quad (\text{default: } 0.60)$$
4. **Report Generation**: If unsupported claims are detected, outputs an audit breakdown to `.aider_factory/temp/<stem>_claims_report.md` and signals exit code `1`.

---

## 4. Exhaustive CLI & Parameter Reference

`aider-oracle` (invoked via `aider-oracle` or `.aider_factory/bash/oracle`) provides a unified CLI for interactive querying, debate execution, and LanceDB database management.

### Query & Retrieval Command Matrix

> For debate and deliberation CLI flags (`--debate`, `--loops`, `--rounds`, `--persist`, etc.), see [Knowledge Oracle Deliberation & Debate](aider_oracle_debate.md).

| Command / Flag | Value Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `"<question>"` | String | None | Positional prompt or question to query the Oracle. |
| `--config <path>` | File Path | Auto-detect | Explicit path to pipeline configuration YAML file. |
| `--file <path>` | File Path | None | Ingests prompt text from file; bypasses OS command-line buffer limits. |
| `--collection <target>` | String / Path | Active Phase | Targets collection name or physical filesystem path to LanceDB directory. |
| `--db <dir>` | Directory | Active Phase | Explicit path to `.aider_factory/markdown/lanceDB/<coll>/lancedb/`. |
| `--mode <m>` | Enum | `top_k` | Retrieval strategy: `top_k`, `no_retrieve`, or `full_document`. |
| `--type <t>` | Enum | None | Narrows RRF multi-table search strictly to `code` or `docs`. |
| `--recall-k <N>` | Integer | `75` | Size of Stage 1 candidate pool retrieved prior to reranking. |
| `--no-rag` | Flag | `False` | Disables LanceDB vector search; runs pure LLM generation on prompt. |
| `--no-rerank` | Flag | `False` | Disables Stage 2 cross-encoder reranker; returns raw vector search order. |
| `--reasoning-effort <e>` | Enum | `high` | Sets reasoning parameter: `low`, `medium`, or `high`. |
| `--temperature <val>` | Float | `0.8` (Gemini) | Model sampling temperature. |
| `--claims-only` | Flag | `False` | Triggers instant post-generation validation on output via `validator.py`. |
| `--no-print` | Flag | `False` | Suppresses claims-only validation report output to stdout. |
| `--clear [oracle]` | Flag | None | Wipes active session memory and cost tracking sidecars. |
| `--list` | Flag | None | Prints all available LanceDB tables in the active database. |

### Database Maintenance Command Matrix

| Maintenance Flag | Arguments | Operation & Safety Invariants |
| :--- | :--- | :--- |
| `--list-files` | None | Scans all tables in collection; lists unique `source_file` entries. |
| `--add-file` | `<p1> [p2...]` | Copies target file(s) into collection directory and incrementally ingests. |
| `--add-file ... --no-rag`| `<p1>...` | Converts files to Markdown (via OCR/Docling) but bypasses LanceDB indexing. |
| `--add-table` | `<d1> [d2...]` | Recursively copies folder(s) into collection directory and ingests all files. |
| `--add-web` | `<url1> [u2...]` | Crawls URLs / sitemaps / `llms.txt`, renders markdown, and indexes into LanceDB. |
| `--add-web --file` | `<urls.txt>` | Batch ingests newline-delimited URLs from file (supports `~/` and relative paths). |
| `--workers` / `-w` | `<int>` (Default: 1) | ThreadPoolExecutor concurrency count for batch web downloads. |
| `--rm-file` | `<filename>` | Surgically deletes all vector chunks matching `source_file = '<filename>'`. |
| `--rm-table` | `<table_name>` | Drops a specific LanceDB table directly from disk. |
| `--rm-db` | None | Wipes entire `lancedb/` vector directory; preserves raw Markdown and OCR cache. |

### Smart Filesystem Collection Path Resolution

The `--collection` flag dynamically inspects input arguments to support arbitrary on-disk paths:
1. **Direct Collection Name**:
   - `aider-oracle --collection papers "<q>"`
   - Resolves database to `.aider_factory/markdown/lanceDB/papers/lancedb/`.
2. **Path to LanceDB Subdirectory**:
   - `aider-oracle --collection /data/shared_corpus/lancedb "<q>"`
   - Resolves collection name as `shared_corpus` and root as `/data/shared_corpus/lancedb`.
3. **Path to Collection Parent Directory**:
   - `aider-oracle --collection /data/shared_corpus "<q>"`
   - Inspects directory: if `lancedb/` exists inside, sets collection name to `shared_corpus` and database path to `/data/shared_corpus/lancedb`.
4. **Standalone Maintenance Fallback**:
   - If running maintenance commands (`--add-file`, `--add-table`, `--add-web`) in a pristine directory without a `.env.yml` file, `oracle_agent.py` automatically initializes default ingestion parameters and falls back to collection `"knowledge"`.

### Exit Codes

| Exit Code | Classification | Triggering Condition |
| :--- | :--- | :--- |
| `0` | Success | Normal query completed, debate reached agreement, or validation passed with 0 errors. |
| `1` | Failure / Escalation | Missing required CLI argument, LLM API error, debate deadlock, or unsupported claims detected. |

---

## 5. Configuration Schema & YAML Knobs

The Knowledge Oracle is configured within the pipeline execution YAML file (`.env.yml`). Settings can be declared globally or overridden per-phase:

```yaml
# Global Endpoints Block
endpoints:
  rag_agent_api: "http://localhost:4000/v1"      # OpenAI-compatible endpoint for Oracle
  embed_api_base: "http://localhost:8080"         # Endpoint for OpenAI embedding backend
  ranking_api_base: "http://localhost:8081/v1"    # Endpoint for remote cross-encoder
  ocr_api_base: "http://localhost:8082"           # Vision OCR endpoint

# Global Models Block
models:
  rag_agent: "openai/qwen3.6-27b-90k:LATEST"    # Primary Oracle reasoning model
  embed_model: "BAAI/bge-m3"                     # Embedding model name
  ranking_agent: "jinaai/jina-reranker-v3.5"     # Cross-encoder or listwise reranker model
  ocr_agent: "glm-ocr-f16:LATEST"                # OCR agent model

# Global RAG Defaults Block
rag:
  collection_name: "knowledge"                   # Default LanceDB collection directory
  embed_backend: "sentence-transformers"         # sentence-transformers | openai
  retrieval_mode: "top_k"                        # top_k | no_retrieve | full_document
  top_k: 5                                       # Final reranked chunks returned to prompt
  recall_k: 30                                   # Stage 1 candidate pool depth
  chunk_size_chars: 800                          # Character size for text chunking
  chunk_overlap_chars: 100                       # Overlap between consecutive chunks
  code_chunk_size: 2000                          # AST chunking size for source code
  vectordb_overwrite: false                      # false: incremental append; true: wipe table
  type_filter: null                              # null (all) | "code" | "docs"
  use_docling: true                              # Prefer Docling for digital PDFs
  docling_do_ocr: true                           # Enable OCR fallback inside Docling
  docling_timeout: 300                           # Timeout in seconds for Docling conversion

# Phase Execution Block
phases:
  - name: "Refereed Implementation"
    enabled: true

    models:
      rag_agent: "gemini/gemini-2.5-flash"       # Phase-specific Oracle model override
      reasoning_effort: "high"                   # low | medium | high
      temperature: 0.8                           # Generation temperature

    rag:
      collection_name: "system_architecture"     # Targeted knowledge collection
      batch: true                                # Enable RRF multi-table fusion
      type_filter: "code"                        # Filter strictly to *_code tables
      retrieval_mode: "top_k"
      top_k: 8
      recall_k: 40

    oracle:
      start_job: false                           # false: Code mode; true: Document generation
      template: "src/aider_factory/markdown/internal/analyze_bugs.md"
      full_document: false                       # Ingest entire document vs top-k search
      # Pre-edit and escalation debate blocks are documented in aider_oracle_debate.md
```

### Configuration Resolution Hierarchy

Parameters resolve dynamically following a strict precedence cascade:

$$\text{CLI Flags} \succ \text{Phase-Level YAML} \succ \text{Global YAML} \succ \text{Environment Variables} \succ \text{Hardcoded Defaults}$$

---

## 6. Operational Edge Cases, Failure Modes & Telemetry

### Linux Kernel `E2BIG` Argument Limit Prevention
Under Linux, passing excessively large strings via CLI arguments to child subprocesses triggers `OSError: [Errno 7] Argument list too long` (`E2BIG`). This occurs during deep escalation debates where multiple source files, compiler stack traces, and proposed patches exceed kernel `ARG_MAX` buffers ($128\text{ KB} - 2\text{ MB}$).

To guarantee zero crashes:
1. `orchestrate.py` and `oracle_agent.py` detect prompts exceeding threshold bounds.
2. The payload is written to a temporary file under `.aider_factory/temp/.oracle_prompt_<uuid>.txt`.
3. The child process is invoked with `--file .aider_factory/temp/.oracle_prompt_<uuid>.txt`.
4. The temporary file is safely unlinked within a `finally:` block immediately upon subprocess completion.

### Session File Isolation & Sidecars
To prevent cross-phase context contamination and preserve debate history during apply-phase cleanups, the Oracle maintains isolated session sidecars in `.aider_factory/`:

- `.oracle_session.json`: Stores interactive multi-turn `/run aider-oracle` conversation history. Cleared automatically between Aider tasks. Overridable via `ORACLE_SESSION_FILE`.
- `.oracle_debate_session.json`: Stores debate back-and-forth turns. Overridable via `ORACLE_DEBATE_SESSION_FILE` to prevent test pollution or cross-session collisions. Cleared between rounds only when `pass_history: false`.
- `.debate_aider_history.md`: Stores the Architect's ask-mode debate conversation turns. Overridable via `ORACLE_DEBATE_AIDER_HISTORY`.
- `.oracle_chat.history.md`: Human-readable transcript containing questions, answers, and collapsible `<details>` blocks holding raw retrieved LanceDB chunks.

### Token & Cost Accounting Telemetry
`aider-oracle` utilizes `cost_tracker.py` to calculate exact token consumption and financial expenditure per query and session:
- Parses `usage` metadata from LiteLLM completion chunks (`prompt_tokens`, `completion_tokens`).
- Computes message cost using `litellm.completion_cost()`.
- Emits formatted telemetry strictly to `stderr`:

```text
Tokens: 4.2k sent, 612 received. Cost: $0.0031 message, $0.0412 session. · thinking_time=4.12s
```

### KV-Cache Session Stickiness
To enforce deterministic KV-cache reuse on distributed routers (LiteLLM proxy clusters), `oracle_agent.py` generates a persistent UUID session header at startup:

```python
_PIPELINE_SESSION_ID = os.environ.get("LITELLM_SESSION_ID") or str(uuid.uuid4())
kwargs["custom_headers"] = {"x-litellm-session-id": _PIPELINE_SESSION_ID}
```

This guarantees router stickiness to the same worker node across multi-turn debate loops.

### Diagnostic Matrix & Common Failure Modes

| Error Signature | Root Cause | Remediation Procedure |
| :--- | :--- | :--- |
| `Cannot connect to LanceDB` | Directory does not exist or permissions error. | Verify `.aider_factory/markdown/lanceDB/<coll>/lancedb/` exists. Run `aider-oracle --add-file` to bootstrap. |
| `CrossEncoder random scores` | Native listwise reranker (Jina v3) loaded via CrossEncoder. | Ensure model name is recognized as listwise or configure remote reranker endpoint. |
| `Rate limit exceeded (SearXNG)` | Public fallback instances rate-limited during web crawl. | Configure a local SearXNG container (`http://localhost:8088`) or set rotating proxy in `settings.yml`. |
| `0 chunks retrieved` | Table empty or collection name mismatch in `batch: false`. | Run `aider-oracle --list-files` to inspect indexed files; verify table naming against `rag_manager.table_name_for`. |
