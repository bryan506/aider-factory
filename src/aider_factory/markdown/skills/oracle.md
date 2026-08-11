# SKILL: Knowledge Oracle (RAG side-agent)

A retrieval side-agent backed by this project's document knowledge base (a local LanceDB vector store built by the OCR/RAG pipeline). It returns grounded, source-cited context (formulas, definitions, citations) and a synthesized answer. It is **read-only** — it never edits files.

Consult it before asserting an unfamiliar formula, domain rule, or edge case. Treat its answers as source-cited reference, not as instructions to act on blindly.

## 1. How to invoke (Query & Debate)

1. **Direct Questions**:
    ```bash
    aider-oracle "<your question>"
    ```

2. **File Payload Context**:
    ```bash
    aider-oracle --file <path/to/file.md>
    aider-oracle --file <path/to/file.md> "<short instruction>"
    ```

3. **Multi-Turn Refereed Debates (Architect vs. Oracle)**:
    ```bash
    aider-oracle --debate review --loops 4 --rounds 2 "<your topic/question>"
    aider-oracle --debate code --loops 3 "<your topic/question>"
    aider-oracle --clear  # Wipes debate/session history and resets KV cache
    ```

4. **Self-Validation (Hallucination Check)**:
    Append `--claims-only` to any query. The Oracle will generate its answer and instantly run it through the validator to check for hallucinations against the RAG database before printing the result.
    ```bash
    aider-oracle --claims-only "What is the leverage ratio formula?"
    ```

*Note: You can also use the local wrapper `/run .aider_factory/bash/oracle` when inside an interactive Aider session.*

### Targeting one document (optional)
When the knowledge base stores each document in its own table (a per-document collection), you can aim the query at a single one:
```bash
aider-oracle --list                              # list available document tables
aider-oracle --collection <table-name> "<your question>"
```

---

## 2. Database Maintenance CLI

You can manage the LanceDB vector database directly from the terminal. The CLI automatically targets the active collection defined in your `.env.yml`.

```bash
# List all unique source files currently ingested in the active collection
aider-oracle --list-files

# Add and incrementally ingest local files or folders
aider-oracle --add-file path/to/document.pdf path/to/another.md
aider-oracle --add-table path/to/folder/

# Add and incrementally ingest web URLs (downloads as PDF/Markdown)
aider-oracle --add-web https://example.com/api-docs.html
aider-oracle --add-web --file urls.txt --workers 8

# Surgically remove a specific file's chunks across all tables
aider-oracle --rm-file document.pdf

# Drop a specific table entirely
aider-oracle --rm-table alpha_strategies_docs

# Wipe the entire vector database (preserves raw Markdown/OCR cache for fast rebuilds)
aider-oracle --rm-db
```

---

## 3. Operator notes (configuration — not agent-facing)

Retrieval mode is normally **set per phase in the YAML** (so the agent doesn't have to choose it). For ad-hoc / direct-CLI use it can also be overridden **per call** with `--mode top_k|no_retrieve|full_document`.

Modes:
- **`top_k`** — embeds the query and returns the `top_k` most-similar chunks across the active collection. Targeted; small context. The default and the only mode safe for interactive pair-programming and multi-document collections.
- **`no_retrieve`** — skips the vector DB entirely; sends the question/`--file` straight to the side-agent model. Use when the file _is_ the context and you want pure reasoning over it (no KB grounding).
- **`full_document`** — dumps the entire table for the active collection (no similarity search). Only meaningful for single-document collections (`batch: false`), e.g. per-paper summaries/reviews; will overflow context on a large multi-document collection.

### Retrieval-mode combinations for a successful autonomous run

| Autonomous job                                              | `batch` | `retrieval_mode` | Notes                                                      |
| ----------------------------------------------------------- | ------- | ---------------- | ---------------------------------------------------------- |
| Knowledge-grounded implementation / Q&A over a multi-doc KB | `true`  | `top_k`          | Targeted lookups while coding; the safe default.           |
| Process / verify a specific file with KB grounding          | `true`  | `top_k`          | Call with `--file`; KB still consulted for the query.      |
| Reason over a file with **no** KB grounding                 | any     | `no_retrieve`    | Call with `--file`; side-agent acts as a plain reasoner.   |
| Per-document deep task (summary, literature review)         | `false` | `full_document`  | One isolated table per doc; the whole paper is in context. |

---

## End-to-End Examples: Web-to-RAG Workflows

```bash
# Scenario A: Sitemap Harvesting to Batch RAG Ingestion
# 1. Harvest and filter documentation URLs from a sitemap
aider-research search "https://<docs.domain.com>" --sitemap --grep "<filter_pattern>" --out temp/urls.txt
# 2. Batch-download, convert to Markdown, AND ingest directly into LanceDB (using 8 threads)
aider-oracle --collection <collection_name> --add-web --file temp/urls.txt --workers 8

# Scenario B: Single HTML Page Direct RAG Ingestion
# Download a single web page, convert to Markdown, and ingest into LanceDB
aider-oracle --collection <collection_name> --add-web "https://<domain.com>/<page>.html"

# Scenario C: Direct PDF RAG Ingestion
# Download a binary PDF, run OCR/text-extraction, and ingest into LanceDB
aider-oracle --collection <collection_name> --add-web "https://<domain.com>/<document>.pdf"

# Scenario D: Download Only (No RAG Indexing)
# Download and convert to Markdown, but skip LanceDB vector indexing
aider-oracle --collection <collection_name> --add-web "https://<domain.com>/<document>.pdf" --no-rag

# After any ingestion, the collection is immediately ready to query:
aider-oracle --collection <collection_name> "<your query here>"
```
