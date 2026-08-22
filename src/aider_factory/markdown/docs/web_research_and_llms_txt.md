# Web Research, Sitemap Harvesting & `llms.txt` Ingestion

`aider-factory` provides a private, automated web research and ingestion subsystem composed of `research_agent.py` (metasearch & sitemap harvesting) and `rag_web.py` (multi-stage URL extraction & `llms.txt` discovery).

---

## 1. Private Metasearch CLI (`aider-research`)

`aider-research` interfaces with a local, user-level SearXNG container on port **8088** to perform private, zero-tracking web searches.

### Invocations
```bash
# General query (top 10 results)
aider-research search "quantum computing error correction" --top 10

# Academic search mode (filters to arXiv, Google Scholar, Crossref, CORE)
aider-research search "liquidity adjusted volatility" --academic --time-range month

# Read complex query from a text file
aider-research search --file query_prompt.txt --academic

# Return ONLY a list of URLs (supports search operators like site:, filetype:)
aider-research search "site:lemonade-server.ai/docs" --links-only --out temp/urls.txt
```

### CAPTCHA & Rate Limit Resilience (Dynamic Public Fallback)
If local SearXNG hits upstream rate limits (returning 0 results), `research_agent.py` fetches the top 5 healthiest public SearXNG instances from `searx.space` (cached locally for 24 hours) and retries the query seamlessly.

---

## 2. Deterministic Sitemap & `llms.txt` Harvesting

Extract and filter URLs from domain sitemaps or AI documentation manifests (`llms.txt`) with zero LLM token costs.

```bash
# 1. Recursive sitemap harvesting with regex filtering
aider-research search "https://docs.example.com" --sitemap \
  --grep "api|guide" \
  --grep-exclude "zh-cn|de|ja" \
  --site-depth 2 \
  --out temp/docs_urls.txt

# 2. Direct llms.txt manifest harvesting
aider-research search "https://docs.example.com/llms.txt" --sitemap --out temp/llms_urls.txt
```

### Harvesting Pipeline Algorithm
1. **Direct `llms.txt` Check**: If the target URL contains `/llms.txt`, `fetch_llms_txt_urls()` parses all Markdown link targets (`[Title](url)`), resolves relative URLs, and applies regex filters.
2. **Sitemap XML Parsing**: Fetches `/sitemap.xml`. If it is a `<sitemapindex>`, recursively follows child `<sitemap>` tags up to `--site-depth`.
3. **Robots.txt Fallback**: If `/sitemap.xml` returns 404, fetches `/robots.txt` and parses `Sitemap:` directives.
4. **`robots.txt` $\to$ `llms.txt` Fallback**: If no sitemap is declared in `robots.txt`, attempts to discover `{domain}/llms.txt`.

---

## 3. Multi-Stage URL Ingestion Engine (`rag_web.py`)

When URLs are processed via `aider-oracle --add-web`, `rag_web.py` classifies the content type and converts the page into clean Markdown using a 4-tier waterfall:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 URL CONVERSION WATERFALL                                        │
│                                                                                                 │
│  [Target URL]                                                                                   │
│       │                                                                                         │
│       ▼                                                                                         │
│  [Step A: HEAD Content-Type Sniff]                                                              │
│  • application/pdf or .pdf -> Direct Binary PDF Download (saved as <stem>.pdf)                 │
│       │ (If not PDF)                                                                            │
│       ▼                                                                                         │
│  [Step B: Direct Plain Text / Markdown Fast-Path]                                              │
│  • .md, .txt, .rst, .json, .csv, llms-full.txt, text/markdown -> Direct text download          │
│       │ (If HTML)                                                                               │
│       ▼                                                                                         │
│  [Step C: Trafilatura Main-Text Extraction]                                                     │
│  • Spoofs User-Agent (Mozilla/5.0) to bypass basic WAFs                                         │
│  • Extracts clean article Markdown and table structures                                         │
│       │ (If Trafilatura fails or yields < 100 bytes e.g. SPA)                                   │
│       ▼                                                                                         │
│  [Step D: Headless Playwright Chromium Fallback]                                                │
│  • Launches headless browser, evaluates JS, and extracts rendered DOM Markdown                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. End-to-End Ingestion Examples

```bash
# Scenario A: Batch Ingest Documentation URLs using 8 Threads
aider-oracle --collection my_docs --add-web --file temp/docs_urls.txt --workers 8

# Scenario B: Single Page Direct RAG Ingestion
aider-oracle --collection my_docs --add-web "https://example.com/guide.html"

# Scenario C: Direct PDF Download & OCR Ingestion
aider-oracle --collection my_docs --add-web "https://example.com/whitepaper.pdf"

# Scenario D: Direct Markdown Download (No RAG Indexing)
aider-oracle --collection my_docs --add-web "https://example.com/llms-full.txt" --no-rag
```
