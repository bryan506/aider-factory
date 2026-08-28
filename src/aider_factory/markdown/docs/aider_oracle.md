# `aider-oracle` — Knowledge Oracle & RAG Retrieval Engine

## 1. Executive Overview & Foundational Invariants

`aider-oracle` is the Tier-2a Knowledge Oracle side-agent for the AI Factory. It provides grounded, verbatim evidence and strategic domain knowledge to the Architect and Editor agents without polluting their primary conversation contexts or VRAM with massive, unindexed document dumps.

### Core Architectural Roles
1. **Interactive RAG Side-Agent**: Executed via `/run aider-oracle "<question>"` inside Aider sessions or pair-programming prompts to answer focused domain or code queries on demand.
2. **Programmatic Document Synthesizer (`start_job: true`)**: Runs autonomously outside Aider sessions to fill Markdown templates straight from ingested literature collections (e.g., generating automated paper reviews or specification summaries).
3. **Refereed Debate Opponent (`--debate`)**: Acts as a strict, evidence-grounded critic during pre-edit and post-test escalation debates, evaluating Architect proposals against retrieved source material.

### Foundational Invariants
* **Strict Stream Separation**: The final answer is printed exclusively to `stdout` so that Aider folds a clean message into its chat context. All library logging (LiteLLM, HuggingFace, PyTorch), progress bars, retrieved chunk citations, and cost accounting lines are piped strictly to `stderr`.
* **Reactive Judge**: The Oracle is a reactive judge and evidence retriever; it is not a whole-document auditor. It evaluates Architect proposals against retrieved chunks and cites verbatim text.
* **Offline-First Reranking**: Local rerankers strictly attempt `local_files_only=True` first to guarantee zero network calls and prevent HuggingFace telemetry leaks, falling back to network downloads only during initial cold-start model provisioning.
* **Zero-RAG Bypass**: When `ORACLE_COLLECTION` or `rag.collection_name` is set to an empty string (`""`), vector search is completely bypassed. The Oracle relies solely on the provided prompt text or injected context files.

---

## 2. System Topology & Lifecycle Flowcharts

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   AIDER-ORACLE DATA FLOW                                        │
│                                                                                                 │
│  [Node 1: Input & CLI Parsing]                                                                  │
│  • Parses query, --file, or maintenance commands (--add-web, --rm-file, --list-files)          │
│  • Resolves ORACLE_* environment variables from active phase in .env.yml                        │
│                                                                                                 │
│                                           │                                                     │
│                                           ▼                                                     │
│  [Node 2: Context Retrieval & RRF Fusion]                                                       │
│  • Truncates query to 6,000 chars (_MAX_EMBED_CHARS) to prevent VRAM OOM                        │
│  • Embeds query via sentence-transformers or OpenAI-compatible API                              │
│  • Searches LanceDB tables (batch=true fuses code & doc tables via Reciprocal Rank Fusion)      │
│  • Reranks candidates via Cross-Encoder or Native Listwise reranker (e.g., jina-reranker-v3.5)  │
│                                                                                                 │
│                                           │                                                     │
│                                           ▼                                                     │
│  [Node 3: LLM Generation & Telemetry]                                                           │
│  • Formats prompt with <knowledge_base> and <question> XML blocks                               │
│  • Calls rag_agent model (e.g., openai/qwen3.6-27b or gemini/gemini-2.5-flash)                 │
│  • Emits final answer to stdout; logs token counts, costs, and citations to stderr              │
│  • Optional: If --claims-only, instantly validates output via validator.py                      │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### Reciprocal Rank Fusion (RRF)
When `batch: true` is enabled, the Oracle queries multiple LanceDB tables simultaneously (e.g., `<coll>_<repo>_code`, `<coll>_<repo>_docs`, `<coll>_docs`). To merge these disparate vector search result lists into a single deterministic top-$k$ candidate list, it applies Reciprocal Rank Fusion:

$$RRF\_Score(chunk) = \sum_{t \in Tables} \frac{1}{60 + rank_t(chunk)}$$

Chunk deduplication uses a composite key of `(source_file, text[:64])`. Secondary sort keys `(source_file, text_prefix)` break ties deterministically, eliminating filesystem ordering variance across operating systems.

### Two-Stage Reranking Engine
Candidates retrieved via vector search ($k_{recall} = \text{ORACLE\_RECALL\_K}$, default 30) are passed to a two-stage reranking engine (`_rerank_chunks`). The Oracle automatically detects and routes to two distinct model families:

1. **Native Listwise Rerankers** (e.g., `jinaai/jina-reranker-v3.5`):
   - **Detection**: Checks model configuration for custom `JinaForRanking` architectures (`AutoConfig.auto_map`).
   - **Execution**: Loaded via `transformers.AutoModel(trust_remote_code=True)` and scored jointly in a single forward pass using the vendor's native `.rerank(query, documents)` method.
   - **Safety Invariant**: Native listwise rerankers are *never* loaded through `sentence_transformers.CrossEncoder`, which forces `AutoModelForSequenceClassification` and silently discards the MLP projector head, yielding non-deterministic random scores.
2. **Pairwise Cross-Encoders** (e.g., `BAAI/bge-reranker-large`, `cross-encoder/ms-marco-MiniLM-L-6-v2`):
   - **Execution**: Loaded via `sentence_transformers.CrossEncoder` and scored via `predict([[query, doc], ...])`.

### Query Truncation Safeguard (`_MAX_EMBED_CHARS`)
During multi-turn debates or when `--file` attaches large context blocks, prompt strings can exceed 30,000+ characters. Passing these directly to local embedding models (e.g., `BAAI/bge-m3` or `sentence-transformers`) can exceed context windows and trigger Out-Of-Memory (OOM) GPU crashes. The Oracle strictly truncates the input string used for vector embedding:

```python
_MAX_EMBED_CHARS = 6000
embed_input = prefix + query[:_MAX_EMBED_CHARS]
```

This preserves the structural core of the query while staying well within embedding model context limits.

---

## 4. Exhaustive CLI Invocations & Command Matrix

The Knowledge Oracle provides both a search/query interface and a full-featured LanceDB database maintenance suite via `aider-oracle` (or `.aider_factory/bash/oracle`).

### Standard Query & Debate Interface

| Command / Flag | Argument | Description |
| :--- | :--- | :--- |
| `aider-oracle "<q>"` | Positional string | Standard interactive query using the active phase's collection and retrieval mode. |
| `--file` | `<path> ["note"]` | Reads message payload directly from a file on disk (bypasses OS command-line buffer limits). |
| `--collection` | `<table>` | Targets a specific LanceDB table (e.g., a single paper's table when `batch: false`). Supports global paths. |
| `--db` | `<dir>` | Overrides `ORACLE_RAG_DB_DIR` path to target an alternate LanceDB directory. |
| `--mode` | `top_k` \| `no_retrieve` \| `full_document` | Overrides the phase's retrieval mode for this single invocation. |
| `--type` | `code` \| `docs` | Filters RRF fusion to narrow retrieval strictly to `*_code` or `*_docs` tables. |
| `--no-rag` | None | Bypasses LanceDB vector retrieval entirely and queries the LLM directly over the prompt context. |
| `--claims-only` | None | Runs instant post-generation claim validation on the Oracle's generated response via `validator.py`. |
| `--no-print` | None | Suppresses stdout output during `--claims-only` validation; writes report to disk only. |
| `--debate` | `code` \| `review` | Triggers an interactive CLI-driven debate between the Architect and Oracle. |
| `--loops` | `<int>` | Sets max turns per debate round (default: 3). |
| `--rounds` | `<int>` | Sets max escalation rounds for debate reflexion (default: 1). |
| `--clear` | None | Wipes active session files (`.oracle_session.json`, `.oracle_debate_session.json`, transcripts). |
| `--list` | None | Lists all available LanceDB tables in the active `ORACLE_RAG_DB_DIR`. |

> **Auto-Validation Trigger:** While `--claims-only` can be invoked manually as a flag, the Oracle also runs this validation *automatically* on every standard generation if the `ORACLE_CLAIMS_ONLY=1` environment variable is exported.

### LanceDB Database Maintenance Interface

| Maintenance Flag | Arguments | Operational Behavior |
| :--- | :--- | :--- |
| `--list-files` | None | Scans all tables in the active collection and prints a list of all unique ingested source files. |
| `--add-file` | `<path1> [path2...]` | Copies target file(s) into `.aider_factory/markdown/lanceDB/<coll>/` and incrementally ingests them. |
| `--add-file ... --no-rag` | `<path1>...` | Converts files to Markdown (via OCR/Docling) in the collection folder but skips LanceDB vector indexing. |
| `--add-table` | `<dir1> [dir2...]` | Recursively copies folder(s) into the collection directory and incrementally ingests all files inside. |
| `--add-web` | `<url1> [url2...]` | Downloads web URLs or PDFs (via `rag_web.py`), converts to Markdown, and ingests into LanceDB. |
| `--add-web --file` | `<urls.txt>` | Ingests a line-separated file of URLs (supports `~/` and relative paths). |
| `--add-web ... --workers` | `<int>` | Sets parallel worker thread count for concurrent web downloads (default: 1). |
| `--rm-file` | `<filename>` | Surgically deletes all vector chunks belonging to `<filename>` across all collection tables. Drops empty tables. |
| `--rm-table` | `<table_name>` | Drops a specific LanceDB table directly from the database. |
| `--rm-db` | None | Wipes the entire `lancedb/` vector store directory while preserving raw Markdown text and OCR image caches. |

---

## 5. Configuration Schema & YAML Knobs

The Oracle's behavior is controlled per-phase in `.env.yml` via the `oracle:`, `rag:`, and `escalation_debate:` blocks:

```yaml
phases:
  - name: "Implementation Phase"
    enabled: true

    models:
      rag_agent: "openai/qwen3.6-27b-90k:latest" # Oracle reasoning model
      ocr_agent: "glm-ocr-f16:LATEST"             # Vision OCR model
      embed_model: "BAAI/bge-m3"                   # Vector embedding model
      ranking_agent: "jinaai/jina-reranker-v3.5"   # Reranker model

    rag:
      collection_name: "knowledge"
      batch: true                 # true: RRF multi-table fuse; false: per-doc tables
      retrieval_mode: "top_k"     # top_k | no_retrieve | full_document
      top_k: 5                    # Number of reranked chunks returned to context
      recall_k: 30                # Initial vector candidate pool before reranking
      chunk_size_chars: 800
      chunk_overlap_chars: 100
      code_chunk_size: 2000
      vectordb_overwrite: false   # true: force rebuild; false: incremental append
      run_ocr_rag: false          # true: trigger ingestion pass at phase start

    oracle:
      start_job: false            # false: Code mode (no auto-generate); true: Review mode
      template: "src/aider_factory/markdown/internal/analyze_bugs.md"
      job_debate_template: "src/aider_factory/markdown/templates/job_debate.md"
      full_document: false        # true: dump entire table context; false: top_k retrieval
      pre_edit_debate:
        enabled: true
        insert_debate: [1, 0, 0]  # Trigger pre-edit debate before Job 1

    escalation_debate:
      loops: 4                    # Max architect/oracle turns per debate
      rounds: 2                   # Escalation cycles after test-fix loop exhausts
      pass_round_history: true    # true: persist debate context across rounds
```

---

## 6. Operational Edge Cases, Failure Modes & Telemetry

### Session File Isolation
To prevent cross-phase context contamination and preserve debate history during apply-phase cleanups, the Oracle maintains isolated session sidecars in `.aider_factory/`:

- `.oracle_session.json`: Stores interactive multi-turn `/run aider-oracle` conversation history. Cleared automatically between Aider tasks.
- `.oracle_debate_session.json`: Stores debate back-and-forth turns. Configured via `ORACLE_SESSION_FILE`. Cleared between rounds only when `pass_round_history: false`.
- `.oracle_chat.history.md`: Human-readable transcript containing questions, answers, and collapsible `<details>` blocks holding raw retrieved LanceDB chunks.

### `E2BIG` Linux Kernel Safeguard
During deep escalation debates, full prompts containing multi-file code context, failure stack traces, and proposal diffs can exceed several megabytes. Passing these directly as CLI string arguments to child processes triggers the Linux kernel `E2BIG` error (`Argument list too long`). 

The orchestrator (`orchestrate.py`) detects large debate prompts, writes them to temporary files under `.aider_factory/.oracle_prompt_<tmp>.txt`, and invokes the Oracle via the `--file` flag:

```python
args = [oracle_bin, "--mode", mode, "--file", prompt_file.name]
```

The temporary prompt file is safely unlinked immediately after the Oracle process completes.
