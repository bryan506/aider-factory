# AI Factory Web Research & Ingestion Skill (`aider-research`)

Use this skill when searching online topics, fetching literature or web documentation, and ingesting web sources into your active LanceDB collection for Knowledge Oracle querying.

## Commands

```bash
# 1. Metasearch via SearXNG (Academic mode)
/run .aider_factory/bash/research search "negative income tax labor supply" --academic --top 5

# 2. Metasearch using a file for multiline / complex citations
/run .aider_factory/bash/research search --file query.txt --academic --top 10

# 3. Metasearch returning ONLY links (useful for piping to oracle --add-web)
/run .aider_factory/bash/research search "machine learning in finance" --links-only --out temp/links.txt

# 4. Sitemap Discovery & URL Harvesting (Deterministic)
/run .aider_factory/bash/research search "https://docs.example.com" --sitemap --grep "api|guide" --grep-exclude "zh-cn" --site-depth 2 --out temp/urls.txt

# 5. Direct Oracle Web Ingestion (Direct URLs or --file line-separated input)
/run .aider_factory/bash/oracle --add-web https://example.com/article.html --collection my_collection
/run .aider_factory/bash/oracle --add-web --file urls.txt --collection my_collection
/run .aider_factory/bash/oracle --add-web --file ~/notes/urls.txt
```

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
