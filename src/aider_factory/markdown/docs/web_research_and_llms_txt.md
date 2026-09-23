# Web Research, Sitemap Harvesting & `llms.txt` Ingestion

## 1. Executive Overview & Foundational Invariants

`aider-factory` provides a private, automated web research and ingestion subsystem composed of `research_agent.py` (metasearch & sitemap harvesting) and `rag_web.py` (multi-stage URL extraction & `llms.txt` discovery). This subsystem enables agents to query live web data, harvest documentation manifests, and ingest external HTML/PDFs into LanceDB without relying on commercial search APIs.

### SearXNG Service Auto-Provisioning & OS Boundary (`ensure_searxng_service`)

The pipeline automatically provisions and probes the local SearXNG service (`http://localhost:8088`) via `cli.py`:

1.  **Health Check Probe (All Platforms):** Attempts a fast 1-second `GET http://localhost:8088/healthz` probe. If healthy (`200 OK`), execution continues immediately.
2.  **Linux Systemd Auto-Provisioning:** If the service is not running and `sys.platform == "linux"`:
    - **Container Engine Precedence (Podman-First):** Checks for rootless `podman` first; falls back to `docker` if podman is unavailable.
    - **Configuration & Systemd Unit Synthesis:** Auto-generates `~/.config/searxng/settings.yml` (enabling JSON format) and writes a user-space systemd unit at `~/.config/systemd/user/searxng.service`.
    - **Daemon Launch:** Executes `systemctl --user enable --now searxng.service` without requiring `sudo` privileges.
3.  **Windows & macOS Fallback:** On non-Linux platforms (`win32`, `darwin`), systemd is unavailable. The CLI outputs an informational notice advising the user to start SearXNG manually (e.g., via Docker Desktop or a remote container) or configure `SEARXNG_BASE_URL`.

### Foundational Invariants

1. **Strict Privacy & Zero-Tracking**: Queries are routed through a local, user-level SearXNG container (`port 8088`). Queries never leave the infrastructure unless falling back to public instances.
2. **Deterministic Fallback**: If the local SearXNG instance is rate-limited (e.g., CAPTCHAs), the system automatically falls back to the top 5 healthiest public instances from `searx.space`.
3. **Cheapest-First Extraction**: URL conversion follows a strict waterfall, attempting low-overhead extraction (HEAD sniff, direct text) before escalating to expensive methods (Trafilatura, Headless Playwright).
4. **JIT Browser Provisioning**: If Headless Chromium is required but missing, the pipeline automatically provisions it via `playwright install chromium` in the background.

---

## 2. System Topology & Lifecycle Flowcharts

### Web Research & Sitemap Harvesting Pipeline

```text
[User / Agent Query] ──▶ `aider-research search`
                            │
    ┌───────────────────────┴───────────────────────┐
    │                 Query Type?                   │
    └─────────┬───────────────────────────┬─────────┘
              │                           │
        [Metasearch]                 [Sitemap]
              │                           │
    ┌─────────▼─────────┐       ┌─────────▼─────────┐
    │ Query SearXNG API │       │ Fetch sitemap.xml │
    │ (Local or Public) │       │ -> robots.txt     │
    └─────────┬─────────┘       │ -> llms.txt       │
                                └─────────┬─────────┘
              │                           │
              ▼                           ▼
    [Filter & Format]           [Regex Grep Filter]
              │                           │
              └─────────────┬─────────────┘
                            ▼
                    [Output URLs / Report]
```

### URL Conversion Waterfall (`rag_web.py`)

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 URL CONVERSION WATERFALL                                        │
│                                                                                                 │
│  [Target URL]                                                                                   │
│       │                                                                                         │
│       ▼                                                                                         │
│  [Step A: HEAD Content-Type Sniff]                                                              │
│  • application/pdf or .pdf -> Direct Binary PDF Download (saved as <stem>.pdf)                  │
│       │ (If not PDF)                                                                            │
│       ▼                                                                                         │
│  [Step B: Direct Plain Text / Markdown Fast-Path]                                               │
│  • .md, .txt, .rst, .json, .csv, .tsv, llms-full.txt, text/markdown -> Direct text download      │
│       │ (If HTML)                                                                               │
│       ▼                                                                                         │
│  [Step C: Trafilatura Main-Text Extraction]                                                     │
│  • Spoofs User-Agent (Mozilla/5.0) to bypass basic WAFs                                         │
│  • Extracts clean article Markdown and table structures                                         │
│       │ (If Trafilatura fails or yields < 100 bytes e.g. SPA)                                   │
│       ▼                                                                                         │
│  [Step D: Headless Playwright Chromium Fallback]                                                │
│  • Launches headless browser, evaluates JS, and extracts rendered DOM Markdown                  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### Dynamic Public Instance Fallback

To mitigate upstream rate limits (e.g., Google serving CAPTCHAs to the local SearXNG instance), `research_agent.py` implements a dynamic fallback mechanism:

1. Fetches `https://searx.space/data/instances.json`.
2. Filters for instances with `network_type == "normal"`, `uptimeMonth >= 99`, `grade` in `["A", "A+", "V"]`, and Google error rate `< 50`.
3. Sorts by highest uptime and lowest latency.
4. Caches the top 5 URLs in `.aider_factory/logs/cache/searxng_fallbacks.json` for 24 hours.

### Sitemap Discovery & Fallback Chain

When harvesting a domain, if the default `sitemap.xml` endpoint fails or returns 404 at depth 1, the pipeline automatically falls back to fetching `robots.txt` to parse official `Sitemap:` directives. If no directives are found, it performs a final probe for an `llms.txt` manifest.

### Multi-Line Query Collapse

When passing complex prompts via `--file <query.txt>`, the research agent deterministically collapses multi-line inputs into a single-line query using `re.sub(r"\s+", " ", query).strip()` before dispatching to the SearXNG API.

### `llms.txt` Discovery & Regex Parsing

When harvesting an `llms.txt` manifest, the pipeline extracts valid Markdown link targets using the following regular expression:

```python
re.findall(r'\[.*?\]\((https?://[^\s\)]+|/[^\s\)]+|[^\s\)]+\.md|[^\s\)]+\.html|[^\s\)]+\.txt)\)', text)
```

Relative URLs are automatically resolved against the manifest's base URL using `urllib.parse.urljoin`.

### Sitemap Regex Filtering (`--grep`)

When harvesting URLs via `--sitemap`, the pipeline supports powerful pre-ingestion filtering using `--grep` and `--grep-exclude`. These flags compile the provided strings as case-insensitive regular expressions (`re.IGNORECASE`), allowing flexible, pattern-based inclusion or exclusion of massive sitemaps before they reach the ingestion engine.

### Headless Playwright JIT Provisioning

For Single-Page Applications (SPAs) where Trafilatura yields $< 100$ bytes, `rag_web.py` falls back to Playwright. If the Chromium binary is missing, it catches the `Executable doesn't exist` exception and executes:

```python
subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
```

This downloads the ~150MB binary to `~/.cache/ms-playwright` transparently.

### Concurrent Web Fetching

When `aider-oracle --add-web` is invoked with multiple URLs, `rag_web.fetch_urls_batch()` utilizes a `ThreadPoolExecutor`. The concurrency level is controlled by the `--workers` flag (or `ORACLE_WEB_WORKERS`), allowing rapid ingestion of large documentation sites.

---

## 4. Exhaustive CLI Invocations & Command Matrix

| Command / Flag                                                  | Context           | Description & Operational Behavior                                                 |
| :-------------------------------------------------------------- | :---------------- | :--------------------------------------------------------------------------------- |
| `aider-research search "<query>" --top 10`                      | Metasearch        | Queries SearXNG and returns the top 10 results as a Markdown report.               |
| `aider-research search "<query>" --academic`                    | Academic Search   | Filters SearXNG engines to `arxiv,google_scholar,crossref,core`.                   |
| `aider-research search "<query>" --engines e1,e2`               | Metasearch        | Queries specific SearXNG engines (e.g., `google,bing`).                            |
| `aider-research search "<query>" --time-range day\|month\|year` | Metasearch        | Restricts search results to a specific time range.                                 |
| `aider-research search --file <query.txt>`                      | Metasearch        | Reads a multi-line query from a file and collapses it into a single search string. |
| `aider-research search "<query>" --links-only`                  | URL Extraction    | Returns only a raw list of URLs (useful for piping into `--add-web`).              |
| `aider-research search "<url>" --sitemap`                       | Sitemap Harvest   | Recursively parses `sitemap.xml` or `llms.txt` for URLs up to `--site-depth`.      |
| `aider-research search "<url>" --sitemap --site-depth N`        | Sitemap Harvest   | Recursively parses sitemaps up to depth `N` (default: 1).                          |
| `aider-research search ... --grep "<regex>"`                    | URL Filtering     | Applies case-insensitive regex inclusion filtering to harvested URLs.              |
| `aider-research search ... --grep-exclude "<regex>"`            | URL Filtering     | Applies case-insensitive regex exclusion filtering to harvested URLs.              |
| `aider-oracle --add-web <url>`                                  | Single URL Ingest | Downloads, converts to Markdown/PDF, and incrementally ingests into LanceDB.       |
| `aider-oracle --add-web --file <urls.txt>`                      | Batch URL Ingest  | Reads line-separated URLs and ingests them sequentially.                           |
| `aider-oracle --add-web --file:<urls.txt>`                      | Batch URL Ingest  | Explicit inline syntax for URL list files, avoiding positional ambiguity.          |
| `aider-oracle --add-web ... --workers 8`                        | Concurrent Ingest | Processes batch URL ingestion using 8 parallel worker threads.                     |
| `aider-oracle --add-web ... --no-rag`                           | Conversion Only   | Downloads and converts URLs to Markdown, but skips LanceDB vector indexing.        |

---

## 5. Configuration Schema & YAML Knobs

Web research and ingestion parameters are controlled via environment variables and `.env.yml` settings:

```yaml
endpoints:
  # Optional: Override the default local SearXNG endpoint
  # Environment Variable: SEARXNG_BASE_URL
  searxng_api_base: "http://localhost:8088"

phases:
  - name: "Web Ingestion Phase"
    rag:
      chunk_size_chars: 800 # Chunk size for ingested web Markdown
      chunk_overlap_chars: 100 # Overlap for ingested web Markdown
      code_chunk_size: 2000 # Chunk size for code snippets in web docs
      ocr_parallel: 1 # Concurrency for OCR (if web PDF is scanned)
```

**Environment Variables**:

- `SEARXNG_BASE_URL`: Defines the primary SearXNG endpoint (Default: `http://localhost:8088`).
- `ORACLE_WEB_WORKERS`: Defines the ThreadPoolExecutor worker count for `--add-web` (Default: `1`).
- `ORACLE_NO_RAG_INGEST`: If `1`, bypasses LanceDB indexing during `--add-web` (Markdown conversion only).

---

## 6. Operational Edge Cases, Failure Modes & Telemetry

| Edge Case / Failure Mode            | Root Cause / Symptom                                                                     | Mitigation & System Recovery                                                                                               |
| :---------------------------------- | :--------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------- |
| **SearXNG Rate Limit (CAPTCHA)**    | Local SearXNG returns 0 results or `unresponsive_engines`.                               | `research_agent.py` automatically fetches healthy public instances from `searx.space` and retries the query.               |
| **SearXNG on Windows / macOS**      | `ensure_searxng_service()` emits notice; service is offline.                             | Run SearXNG via Docker Desktop (`docker run -d -p 8088:8080 searxng/searxng`) or point `SEARXNG_BASE_URL` to an external host. |
| **Playwright Provisioning Blocked** | `playwright install chromium` fails due to corporate firewall or air-gapped environment. | Exception is caught safely. Extraction fails gracefully without crashing the pipeline, logging a warning to `stderr`.      |
| **Sitemap 404 Not Found**           | Target domain does not expose `/sitemap.xml`.                                            | Pipeline automatically fetches `/robots.txt` to parse `Sitemap:` directives. If absent, falls back to probing `/llms.txt`. |
| **SPA Yields Empty Markdown**       | Target URL is a React/Vue SPA; Trafilatura extracts $< 100$ bytes.                       | Pipeline detects low byte count and escalates to the Headless Playwright fallback to render the DOM before extraction.     |
| **Invalid Regex Filter**            | User provides malformed regex to `--grep` or `--grep-exclude`.                           | `re.compile` catches the error, logs a clear message to `stderr`, and exits with code 1.                                   |
