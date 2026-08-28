---
name: aider-research
description: Perform autonomous web searches via SearXNG, harvest documentation sitemaps, and extract clean text/links for RAG ingestion.
---

# SKILL: Web Research & Ingestion (`aider-research`)

`aider-research` provides metasearch querying via SearXNG and deterministic documentation harvesting to acquire external reference literature, API guides, and web documentation.

## Operational Contract & Invariants

1. **Deterministic Discovery**: Harvest structured URL lists and documentation trees prior to initiating RAG ingestion.
2. **Context Preservation**: Save bulk link lists and research reports to disk artifacts (`temp/links.txt`, `temp/research.md`) rather than flooding terminal context.
3. **Execution Routing**: Run via `aider-research` or `/run .aider_factory/bash/research`.

---

## Command Reference & Parameter Table

### Search & Harvesting Parameters (`aider-research`)

| Command / Flag | Argument | Default | Description |
| :--- | :--- | :--- | :--- |
| `search "<query>"` | String | *(Required)* | Natural language search query or query with search operators. |
| `--academic` | None | `False` | Routes query to academic search engines (arXiv, Google Scholar, CrossRef, CORE). |
| `--engines <list>` | String | `None` | Comma-separated search engines (e.g., `google,duckduckgo,github,bing`). |
| `--time-range <range>` | String | `None` | Filters search results by date range (`day`, `month`, or `year`). |
| `--links-only`, `-l` | None | `False` | Returns raw URL list without markdown summaries or snippets. |
| `--out <path>`, `-o` | File Path | `None` | Writes search results or harvested URLs directly to disk. |
| `--top <int>` | Integer | `10` | Number of search results to retrieve. |
| `--file <path>` | File Path | `None` | Ingests multiline query or search string from an explicit file. |
| `--sitemap` | None | `False` | Enables XML sitemap or `llms.txt` manifest traversal mode on the target URL. |
| `--site-depth <int>`, `-d` | Integer | `1` | Maximum traversal depth for nested sitemap indices. |
| `--grep <regex>`, `-g` | Pattern | `None` | Case-insensitive regex filter for including matching URLs. |
| `--grep-exclude <regex>`, `-ge` | Pattern | `None` | Case-insensitive regex filter for excluding matching URLs. |

### Downstream Web Ingestion Parameters (`aider-oracle --add-web`)

| Ingestion Flag | Argument | Default | Description |
| :--- | :--- | :--- | :--- |
| `--add-web <urls...>` | URLs / Paths | *(Required)* | Ingests web pages, XML sitemaps, `llms.txt` manifests, or PDF links. |
| `--file <path>` | File Path | `None` | Loads a line-delimited list of URLs from an explicit file. |
| `--no-rag` | None | `False` | Headless scraping: extracts clean Markdown to disk without indexing into LanceDB. |
| `--workers <int>`, `-w` | Integer | `1` | Number of concurrent worker threads for parallel URL fetching. |

---

## Core Operational Workflows

### 1. General & Academic Metasearch

```bash
# General search with result count limit
aider-research search "distributed consensus raft edge cases" --top 5

# Academic literature search writing report to disk
aider-research search "zero knowledge proof batch verification" --academic --top 10 -o temp/zkp_research.md

# Targeted engine selection and time-range filtering
aider-research search "python 3.12 release notes" --engines "google,github" --time-range month --top 5

# Search using natural operators (site, filetype)
aider-research search "site:docs.example.org/api json schema" --top 10

# Extract clean link list for automated batch processing
aider-research search "site:docs.example.org/v2" -l -o temp/doc_urls.txt
```

### 2. Deterministic Sitemap & llms.txt Harvesting

```bash
# Harvest all documentation URLs from root sitemap
aider-research search "https://docs.example.org/sitemap.xml" --sitemap -o temp/sitemap_urls.txt

# Harvest documentation URLs with include and exclude regex filtering
aider-research search "https://docs.example.org" --sitemap -g "api|guides" -ge "legacy|archive" -d 2 -o temp/filtered_urls.txt

# Harvest clean documentation manifest directly from llms.txt
aider-research search "https://docs.example.org/llms.txt" --sitemap -o temp/llms_urls.txt
```

---

## Canonical Web Ingestion Pipelines

```bash
# Pipeline A: Sitemap Harvesting -> Batch Vector Database Ingestion
# 1. Harvest target documentation URLs
aider-research search "https://docs.example.org" --sitemap -g "v1/api" -o temp/api_urls.txt
# 2. Ingest harvested URLs into LanceDB vector collection with parallel workers
aider-oracle --collection api_docs --add-web --file temp/api_urls.txt --workers 4

# Pipeline B: Headless Ingestion & Standalone Extraction (No RAG Vector Indexing)
# 1. Extract markdown directly to disk without vector embedding overhead
aider-oracle --collection api_docs --add-web "https://docs.example.org/spec.html" --no-rag
# 2. Consume generated markdown directly in agent session
# Markdown saved to: .aider_factory/markdown/lanceDB/api_docs/docs_example_org_spec.md

# Pipeline C: Targeted Domain Search -> Selective Vector Ingestion
# 1. Extract links matching specific component
aider-research search "site:docs.example.org/guides authentication" -l -o temp/auth_urls.txt
# 2. Ingest discovered links into vector store
aider-oracle --collection auth_knowledge --add-web --file temp/auth_urls.txt

# Pipeline D: Querying Ingested Knowledge Base
aider-oracle --collection api_docs "What is the token expiration parameter?"
```

---

## Execution Checklist

- [ ] Check if SearXNG local service is running before initiating bulk web queries.
- [ ] Direct multi-URL output to `--out <path>` (`-o`) to prevent terminal context flooding.
- [ ] Use `--engines` and `--time-range` to narrow search scope and eliminate outdated results.
- [ ] Apply `--grep` (`-g`) and `--grep-exclude` (`-ge`) filters when harvesting sitemaps or `llms.txt` endpoints.
- [ ] Use `--no-rag` with `aider-oracle --add-web` when you only require raw Markdown on disk without vector indexing.
- [ ] Pass `--workers <int>` (`-w`) for parallel concurrent URL fetching during batch ingestion.
