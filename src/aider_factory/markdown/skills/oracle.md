---
name: aider-oracle
description: Query and maintain LanceDB vector stores for RAG side-agent retrieval, fact verification, and multi-turn architectural debates.
---

# SKILL: Knowledge Oracle (`aider-oracle`)

`aider-oracle` is a read-only retrieval side-agent backed by a local LanceDB vector database. It returns grounded, source-cited context (definitions, formulas, schemas, requirements) and synthesized reasoning.

## Operational Contract & Invariants

1. **Read-Only Invariant**: The Oracle queries and reasons over indexed knowledge; it does not write or modify workspace code files.
2. **Deterministic Invocation**: Invoke via the global CLI `aider-oracle` or the local wrapper `/run .aider_factory/bash/oracle`.
3. **Source-Anchored Factuality**: Treat returned answers as source-cited reference context to guide implementation and design decisions.

---

## Command Reference & Mode Selection

### 1. Retrieval Modes & Operational Flags

#### Retrieval Modes (`--mode`)

| Mode | Syntax Flag | Optimal Use Case | Behavior |
| :--- | :--- | :--- | :--- |
| **Top-K (Default)** | `--mode top_k` | Multi-document codebases and large reference sets. | Retrieves top relevant chunks using dense search and listwise reranking. |
| **No-Retrieve** | `--mode no_retrieve` | Direct file reasoning without vector store lookup. | Loads `--file` content directly into context without database queries. |
| **Full-Document** | `--mode full_document` | Isolated single-document analysis (e.g., individual paper or spec). | Ingests the full document text into reasoning context. |

#### Filtering, Reranking & Ingestion Flags

| Flag | Argument | Description |
| :--- | :--- | :--- |
| `--no-rag` | *(None)* | Standalone conversion / query mode. With `--add-web` or `--add-file`, converts content to clean Markdown on disk while bypassing LanceDB indexing. For queries, bypasses vector search. |
| `--type` | `code` \| `docs` | Constrains fused search strictly to code (`*_code`) or documentation (`*_docs`) tables. |
| `--no-rerank` | *(None)* | Disables Stage 2 cross-encoder/listwise reranking; returns raw vector similarity results. |
| `--recall-k` | `<int>` | Sets candidate pool depth retrieved in Stage 1 prior to reranking. |
| `--db` | `<dir_path>` | Overrides the LanceDB storage directory path explicitly. |
| `--no-print` | *(None)* | Suppresses stdout output when running `--claims-only` verification. |

### 2. Query & Refereed Debate Invocations

```bash
# Query active collection with natural language question
aider-oracle "What is the token bucket rate limiter formula?"

# Query with explicit file context payload
aider-oracle --file docs/specification.md "Summarize the error recovery lifecycle"

# Query a specific table/collection
aider-oracle --collection project_knowledge "List all exported API endpoints"

# Query strictly over code tables (ignoring docs) with custom recall pool
aider-oracle --type code --recall-k 50 "Find all AST parser visitors"

# Query bypassing Stage 2 reranker
aider-oracle --no-rerank "Explain the session vault isolation mechanism"

# Direct model query bypassing RAG retrieval
aider-oracle --no-rag "Draft a unit test skeleton for JWT token decoding"

# Execute multi-turn refereed debate (Architect vs. Oracle)
aider-oracle --debate code --loops 3 "Evaluate locking strategy in src/service.py"
aider-oracle --debate review --loops 4 --rounds 2 "Verify claim accuracy in report.md"

# Automated self-validation against database before output
aider-oracle --claims-only "What are the retention bounds for user sessions?"
aider-oracle --claims-only --no-print "What are the retention bounds for user sessions?"

# Clear debate and query session KV-cache history
aider-oracle --clear
```

### 3. Database Maintenance Operations

```bash
# List all ingested tables or unique files
aider-oracle --list
aider-oracle --list-files

# Incrementally ingest local files or folders into LanceDB
aider-oracle --add-file docs/architecture.pdf docs/specs.md
aider-oracle --add-table data/knowledge_base/

# Standalone OCR / Document conversion without LanceDB indexing
aider-oracle --add-file docs/architecture.pdf --no-rag

# Ingest web documentation into LanceDB (Trafilatura/Playwright + Vector indexing)
aider-oracle --add-web https://docs.example.org/api.html
aider-oracle --add-web --file temp/doc_urls.txt --workers 4

# Standalone Web-to-Markdown extraction (bypasses LanceDB vector store)
aider-oracle --add-web https://docs.example.org/api.html --no-rag
aider-oracle --add-web --file temp/doc_urls.txt --no-rag --workers 4

# Explicit collection targeting during ingestion
aider-oracle --collection external_sdk --add-web https://sdk.example.com/docs/

# Remove specific file chunks, tables, or reset database
aider-oracle --rm-file legacy_spec.pdf
aider-oracle --rm-table legacy_knowledge_table
aider-oracle --rm-db
```

---

## Canonical Usage Examples

```bash
# Example 1: Grounding architecture decisions before writing code
aider-oracle --collection api_docs "What headers are required for authentication?"

# Example 2: Verifying a technical specification without database lookup
aider-oracle --mode no_retrieve --file docs/rfc.md "Identify missing edge case handlers"

# Example 3: Running a multi-turn adversarial debate to settle technical consensus
aider-oracle --debate code --loops 3 "Should we use optimistic concurrency or row locks?"

# Example 4: Tool-Chaining Web Research -> Standalone Extraction -> File Read
# 1. Search URLs via aider-research
aider-research search "site:docs.rs/tokio/latest" --links-only --out temp/tokio_urls.txt
# 2. Extract clean Markdown to disk without bloating vector DB
aider-oracle --add-web --file temp/tokio_urls.txt --no-rag --workers 4
# 3. Architect reads extracted markdown files directly via workspace tools
```

---

## Execution Checklist

- [ ] Check available collections using `aider-oracle --list` before running targeted queries.
- [ ] Select `--mode top_k` for vector lookups, `--type code|docs` to constrain corpus, or `--mode no_retrieve` when providing a direct `--file`.
- [ ] Use `--add-web <URL> --no-rag` or `--add-file <path> --no-rag` when only needing clean Markdown documents on disk without vector indexing.
- [ ] Clear stale session cache with `aider-oracle --clear` when beginning an unrelated task.
- [ ] Verify claims with `aider-oracle --claims-only "<query>"` before incorporating unfamiliar constraints into plans.
