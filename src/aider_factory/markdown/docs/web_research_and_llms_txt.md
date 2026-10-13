# Web Research, Sitemap Harvesting & `llms.txt` Ingestion

## 1. Executive Overview & Foundational Invariants

`aider-factory` provides an autonomous, zero-tracking web research, sitemap discovery, and web ingestion subsystem implemented across `research_agent.py` and `rag_web.py`. The subsystem bridges the pipeline DAG with live online documentation, technical repositories, and academic papers without requiring proprietary web-search APIs or exposing user queries to external advertising networks.

### SearXNG Service Auto-Provisioning & OS Boundary (`ensure_searxng_service`)

The pipeline provisions and monitors the local SearXNG metasearch instance (`http://localhost:8088`) via `cli.py`:

1. **Health Check Probe (All Platforms)**: Executes an HTTP `GET http://localhost:8088/healthz` probe with a strict 1.0-second timeout. If the endpoint returns `200 OK`, execution proceeds immediately without service reinitialization.
2. **Linux Systemd Auto-Provisioning**: If the service is inactive and `sys.platform == "linux"`:
   - **Container Engine Resolution (Podman-First)**: Probes for rootless `podman` first; falls back to rootless `docker` if `podman` is not detected in `$PATH`.
   - **Configuration Synthesis**: Automatically generates `~/.config/searxng/settings.yml` (binding the internal server to `0.0.0.0:8080`, generating a dynamic cryptographic `secret_key`, and enabling JSON output formatting).
   - **Systemd User Unit Deployment**: Writes a user-level systemd service file at `~/.config/systemd/user/searxng.service` mapping host port `8088` to container port `8080`.
   - **Daemon Launch**: Executes `systemctl --user daemon-reload` followed by `systemctl --user enable --now searxng.service` without requiring root or `sudo` privileges.
3. **Windows & macOS Operational Boundary**: `systemd` user units are unsupported on `win32` and `darwin`. The CLI issues an operational notice instructing the user to launch SearXNG via Docker Desktop (`docker run -d -p 8088:8080 searxng/searxng`) or configure the `SEARXNG_BASE_URL` environment variable to point to a remote instance.

### Foundational Invariants

1. **Zero-Tracking Privacy Invariant**: Search traffic routes strictly through a local rootless SearXNG container. Queries never touch public networks unless local engines are exhausted, down, or rate-limited.
2. **Deterministic Fallback Invariant**: When local engines trigger anti-bot measures (e.g., CAPTCHAs) or return zero results, the subsystem deterministically fails over to the top 5 public SearXNG instances dynamically ranked via `searx.space` telemetry.
3. **Cheapest-First Extraction Invariant**: Web ingestion follows a strict descending complexity waterfall: HTTP HEAD header sniff $\to$ raw text/markdown stream $\to$ Trafilatura DOM extraction $\to$ Headless Playwright Chromium evaluation.
4. **JIT Browser Provisioning Invariant**: If JavaScript rendering is required on single-page applications (SPAs) and Playwright's Chromium binary is missing, the subsystem auto-installs it just-in-time (`playwright install chromium`) without terminating the active DAG run.

---

## 2. System Topology & Lifecycle Flowcharts

### Research & Sitemap Harvesting Lifecycle

```text
+-----------------------+
|  User / Agent Prompt  |
+-----------+-----------+
            |
            v
+-------------------------------+
| research_agent.py CLI Router  |
+-------+---------------+-------+
        |               |
        | [search]      | [--sitemap]
        v               v
+---------------+  +---------------------------------------------+
| Query Parser  |  | Sitemap Harvester                           |
| - Collapse WS |  | 1. Try target URL (direct XML)               |
| - Parse Engine|  | 2. Fallback: GET /robots.txt -> Sitemap:    |
+-------+-------+  | 3. Fallback: GET /llms.txt link extraction  |
        |          +----------------------+----------------------+
        v                                 |
+------------------------------+          v
| SearXNG Query Pipeline       |  +-------------------------------+
| 1. Local http://localhost:8088| | Regex Filter Stage            |
| 2. Cached Top 5 Fallbacks    |  | - Inclusion: --grep <regex>   |
| 3. Live searx.space Fetch    |  | - Exclusion: --grep-exclude   |
| 4. Hardcoded Fallbacks       |  +---------------+---------------+
+---------------+--------------+                  |
        |                                         v
        v                                 +-------------------------------+
+------------------------------+          | Output URL List               |
| Markdown Report Generation   |          | .aider_factory/markdown/      |
| .aider_factory/markdown/     |          | research/<domain>_sitemap.txt |
| research/<slug>_<stamp>.md   |          +-------------------------------+
+------------------------------+
```

### 4-Tier Ingestion Waterfall (`rag_web.py` -> `rag_manager.py`)

```text
[Input Target URL]
       |
       v
+-------------------------------------------------------------+
| Stage 1: Fast HTTP HEAD Request Sniff                       |
| Content-Type check & URL extension classification           |
+------+------------------------------------------------------+
       |
       +---> [application/pdf or *.pdf]
       |     |
       |     v
       |   +--------------------------------------------------+
       |   | Tier A: Streaming Binary PDF Download            |
       |   | - 8192-byte chunked streaming write              |
       |   | - Saved to: <job_dir>/<base_stem>.pdf            |
       |   +--------------------------------------------------+
       |
       +---> [text/markdown, text/plain, *.md, *.txt, *.rst, *.json, *.csv, *.tsv, llms*.txt]
       |     |
       |     v
       |   +--------------------------------------------------+
       |   | Tier B: Direct Text / Markdown Fast-Path         |
       |   | - Direct GET request (timeout 20s)               |
       |   | - Prepends: "# Source: <url>\n\n"                |
       |   | - Saved to: <job_dir>/<base_stem>.md             |
       |   +--------------------------------------------------+
       |
       +---> [HTML / Unknown MIME Type]
             |
             v
           +--------------------------------------------------+
           | Tier C: Trafilatura Main-Text Extraction         |
           | - GET request with User-Agent: Mozilla/5.0       |
           | - trafilatura.extract(include_tables=True)       |
           | - Check: extracted length >= 100 characters      |
           +-----+--------------------------------------------+
                 |
                 +---> [Success >= 100 chars]
                 |     |
                 |     v
                 |   +----------------------------------------+
                 |   | Save Extracted Markdown Document       |
                 |   | Saved to: <job_dir>/<base_stem>.md     |
                 |   +----------------------------------------+
                 |
                 +---> [Failure or < 100 chars (JS SPA detected)]
                       |
                       v
                     +----------------------------------------+
                     | Tier D: Headless Playwright Fallback   |
                     | - Launch headless Chromium (15s limit) |
                     | - Catch missing binary -> JIT install  |
                     | - Render DOM -> Trafilatura extraction |
                     | - Check: extracted length > 50 chars   |
                     | - Saved to: <job_dir>/<base_stem>.md   |
                     +----------------------------------------+
```

---

## 3. Technical Mechanics & Mathematical Formulations

### Dynamic SearXNG Fallback Ranking & Cache Math

When the local SearXNG endpoint (`http://localhost:8088`) fails or encounters engine CAPTCHAs, `research_agent.py` queries `https://searx.space/data/instances.json`. Candidate public instances $\mathcal{I}$ are filtered according to:

$$\mathcal{I}_{\text{valid}} = \left\{ i \in \mathcal{I} \;\middle|\; \text{net}(i) = \text{"normal"} \;\land\; U_{\text{month}}(i) \ge 99 \;\land\; \text{grade}(i) \in \{A, A^+, V\} \;\land\; E_{\text{google}}(i) < 50 \right\}$$

where:
- $U_{\text{month}}(i)$ is the rolling monthly uptime percentage.
- $\text{grade}(i)$ is the TLS/security audit score.
- $E_{\text{google}}(i)$ is the Google engine error rate percentage.

Filtered instances are sorted lexicographically by:

$$\text{rank}(i) = \left( -U_{\text{month}}(i), \; T_{\text{median}}(i) \right)$$

where $T_{\text{median}}(i)$ is the median search latency in milliseconds. The top $K = 5$ instances are persisted to `.aider_factory/logs/cache/searxng_fallbacks.json` with a cache expiration window:

$$\Delta t = t_{\text{now}} - t_{\text{mtime}} < 86{,}400 \text{ seconds (24 hours)}$$

If the cache file is present and $\Delta t < 86{,}400$, cached instances are loaded directly from disk without network access. If `searx.space` cannot be reached and no cache exists, the system defaults to:

$$\mathcal{I}_{\text{emergency}} = \left[ \texttt{"https://searx.tiekoetter.com"}, \; \texttt{"https://search.mdosch.de"} \right]$$

### Multi-Line Query Sanitization

Search queries provided via `--file <query.txt>` undergo whitespace normalization before submission to the SearXNG REST API:

$$Q' = \text{regex\_sub}\left( \texttt{r"\textbackslash s+"}, \; \texttt{" "}, \; Q \right).\text{strip}()$$

This converts multi-line architect prompts, error logs, or markdown notes into a contiguous single-line query string.

### Sitemap XML & `robots.txt` Recursive Traversal

The harvester resolves a target domain $D$ through a three-stage discovery hierarchy:

1. **Direct Sitemap Probe**:
   Attempts retrieval of $U_{\text{sitemap}} = \texttt{"https://" } \cup D \cup \texttt{"/sitemap.xml"}$.
2. **Robots.txt Fallback**:
   If $U_{\text{sitemap}}$ yields HTTP $\ne 200$ and recursion depth $d = 1$, the harvester requests $\texttt{"https://" } \cup D \cup \texttt{"/robots.txt"}$ and extracts all directives matching:
   $$\mathcal{S}_{\text{directives}} = \{ \text{line}.\text{split}(\texttt{":"}, 1)[1].\text{strip}() \mid \text{line}.\text{lower}().\text{startswith}(\texttt{"sitemap:"}) \}$$
3. **`llms.txt` Fallback**:
   If no sitemap directives are declared in `robots.txt`, the harvester probes $\texttt{"https://" } \cup D \cup \texttt{"/llms.txt"}$.

XML tags are parsed by stripping the namespace container:

$$\text{tag}_{\text{clean}} = \begin{cases} 
\text{tag}.\text{split}(\texttt{"}"}, 1)[1] & \text{if } \texttt{"}"} \in \text{tag} \\
\text{tag} & \text{otherwise}
\end{cases}$$

Child sitemaps (URLs ending in `.xml` or containing `sitemap`) are crawled recursively up to depth $d \le d_{\text{max}}$ (default $d_{\text{max}} = 1$) bounded by a hard cycle guard $|V| \le 50$ visited sitemaps.

### `llms.txt` Link Target Extraction

Manifest links within `/llms.txt` are parsed using the regular expression:

```python
re.findall(
    r'\[.*?\]\((https?://[^\s\)]+|/[^\s\)]+|[^\s\)]+\.md|[^\s\)]+\.html|[^\s\)]+\.txt)\)',
    text
)
```

Anchor fragments (`#...`) are removed, and relative links are converted to absolute URLs:

$$U_{\text{abs}} = \text{urljoin}(U_{\text{manifest}}, \; U_{\text{clean}})$$

Discovered URLs are deduplicated while preserving discovery order:

$$L_{\text{unique}} = \text{list}(\text{dict.fromkeys}(L_{\text{raw}}))$$

### Sitemap Regex Filtering (`--grep` & `--grep-exclude`)

Harvested URLs are filtered against inclusion regex $R_{\text{in}}$ and exclusion regex $R_{\text{ex}}$ compiled with `re.IGNORECASE`:

$$L_{\text{filtered}} = \left\{ u \in L_{\text{unique}} \;\middle|\; (R_{\text{in}} = \emptyset \lor R_{\text{in}}.\text{search}(u)) \;\land\; (R_{\text{ex}} = \emptyset \lor \neg R_{\text{ex}}.\text{search}(u)) \right\}$$

### Deterministic LanceDB Naming & Path Mapping

Downloaded web assets are mapped into local storage within `.aider_factory/markdown/lanceDB/<collection>/`:

$$\begin{aligned}
\text{domain} &= \text{urlparse}(u).\text{netloc}.\text{replace}(\texttt{":"}, \texttt{"_"}) \\
\text{raw\_stem} &= \text{basename}(\text{urlparse}(u).\text{path}.\text{rstrip}(\texttt{"/"})) \lor \texttt{"index"} \\
\text{path\_stem} &= \text{table\_name\_for}(\text{raw\_stem}) \\
\text{base\_stem} &= (\text{domain} \cup \texttt{"_"} \cup \text{path\_stem}).\text{strip}(\texttt{"_"})
\end{aligned}$$

where `table_name_for` sanitizes non-alphanumeric tokens:

$$\text{table\_name\_for}(s) = \text{regex\_sub}\left(\texttt{r"[^0-9A-Za-z._-]+"}, \;\texttt{"_"}, \; s\right).\text{strip}(\texttt{"_"}) \lor \texttt{"doc"}$$

Files are saved as `<base_stem>.md` (text/HTML) or `<base_stem>.pdf` (binary PDF).

### Extraction Waterfall Length Gating

For HTML targets, extraction evaluates two length thresholds:
- **Trafilatura Gate**: Content accepted if $L_{\text{text}} \ge 100$ characters.
- **Playwright Gate**: Content accepted if rendered DOM yields $L_{\text{text}} > 50$ characters.

If both extraction gates fail, the asset is reported as unextractable and skipped.

### LanceDB Ingestion & Chunking Parameters

Extracted Markdown files are vectorized and indexed into LanceDB tables matching the active collection:
- **Text Document Chunking**: $C_{\text{size}} = 1{,}500$ characters with $C_{\text{overlap}} = 300$ characters (fenced code blocks within markdown documents remain atomic and unsplit).
- **Code Chunking**: $C_{\text{code}} = 2{,}000$ characters via Tree-Sitter AST parser chunking.
- **Vector Dimension Probe**: Probed dynamically via the active embedding model ($\dim = 1536$ default probe).

---

## 4. Exhaustive CLI & Parameter Reference

### `aider-research` Command Matrix

`aider-research` operates as the primary metasearch client, report generator, and sitemap harvester.

```bash
# General Syntax
aider-research [search] "<query>" [options]
aider-research [search] --file <query.txt> [options]
aider-research [search] "<url>" --sitemap [options]
```

| Command / Flag | Argument Type | Default Value | Target Scope | Description & Operational Behavior |
| :--- | :--- | :--- | :--- | :--- |
| `search` | Positional keyword | *None* | CLI Router | Optional subcommand keyword (passed through or stripped transparently). |
| `<query>` | Positional string | *None* | Metasearch | Search query string. All whitespace is collapsed into a single line. |
| `--file` | `<path>` | *None* | Metasearch | Reads multi-line search query from a text file and sanitizes whitespace. |
| `--academic` | Boolean flag | `False` | Metasearch | Restricts engines to `arxiv,google_scholar,crossref,core` under category `science`. |
| `--engines` | Comma-separated | *All active* | Metasearch | Selects explicit engines (e.g., `google,bing,duckduckgo`). |
| `--top` | Integer | `10` | Metasearch | Maximum number of ranked results returned in the report. |
| `--time-range` | Enum string | *None* | Metasearch | Filters results by recency: `day`, `month`, or `year`. |
| `--links-only`, `-l` | Boolean flag | `False` | Metasearch | Suppresses report formatting; outputs clean raw URLs (one per line) to stdout. |
| `--out`, `-o` | `<path>` | *Auto-generated* | Output | Custom destination path for generated Markdown report or URL list. |
| `--sitemap` | Positional URL | *None* | Sitemap | Triggers sitemap / `llms.txt` harvesting mode for the specified domain or URL. |
| `--site-depth`, `-d` | Integer | `1` | Sitemap | Maximum recursion depth for parsing linked XML sub-sitemaps. |
| `--grep`, `-g` | `<regex>` | *None* | Sitemap | Case-insensitive regex filter. Only matching URLs are retained in output. |
| `--grep-exclude`, `-ge` | `<regex>` | *None* | Sitemap | Case-insensitive regex filter. Matching URLs are pruned from output. |
| `--help`, `-h` | Boolean flag | *None* | Global | Prints CLI usage summary and exits immediately with code `0`. |

### `aider-oracle --add-web` Command Matrix

`aider-oracle` provides the incremental ingestion entrypoint for downloading, converting, and indexing web assets into LanceDB.

```bash
# General Syntax
aider-oracle --add-web <url...> [options]
aider-oracle --add-web --file <urls.txt> [options]
aider-oracle --add-web --file:<urls.txt> [options]
```

| Flag / Option | Argument Type | Default Value | Description & Operational Behavior |
| :--- | :--- | :--- | :--- |
| `--add-web`, `--web-url` | Space-separated URLs | *None* | One or more URLs to fetch, convert, and incrementally ingest. |
| `--file` | `<path>` | *None* | Text file containing line-separated URLs. Blank lines and `#` comments are ignored. |
| `--file:<path>` | String token | *None* | Inline prefix syntax for file paths, preventing positional flag collisions. |
| `--workers`, `-w` | Integer | `1` | Number of concurrent worker threads for `ThreadPoolExecutor` during batch fetching. |
| `--no-rag` | Boolean flag | `False` | Bypasses LanceDB vector indexing (downloads and converts assets to Markdown only). |
| `--collection` | `<name>` or `<path>` | Active YAML | Explicitly targets an existing or new LanceDB collection directory. |

### Exit Codes & Stream Protocols

- **Exit Code 0**: Search succeeded, sitemap discovery finished with matches, or web ingestion completed without fatal errors.
- **Exit Code 1**: Invalid CLI flags, missing required query/URL, malformed regex pattern (`re.error`), or zero extractable URLs found.
- **stdout Contract**:
  - `aider-research`: Emits the formatted Markdown report or line-delimited raw URLs (when `--links-only` is set).
  - `aider-oracle --add-web`: Emits pure LLM responses; all maintenance logs route to `stderr`.
- **stderr Contract**: Emits progress telemetry (`[rag-web]`, `[research]`, `[sitemap]`), fallback notices, worker status, and network error traces.

---

## 5. Configuration Schema & YAML Knobs

Pipeline configurations in `.aider_factory/.env.yml` expose settings governing web research, extraction, and vector indexing:

```yaml
# ==============================================================================
# AI FACTORY PIPELINE CONFIGURATION: WEB RESEARCH & RAG
# ==============================================================================

endpoints:
  # Base URL for the primary local or remote SearXNG metasearch instance
  searxng_api_base: "http://localhost:8088"
  
  # Endpoint for LanceDB vector embeddings
  embed_api_base: "http://localhost:8000/v1"

models:
  # Model used for generating embeddings during LanceDB ingestion
  embed_model: "BAAI/bge-m3"

phases:
  - name: "Web Knowledge Ingestion"
    enabled: true
    rag:
      # Target collection name within .aider_factory/markdown/lanceDB/<collection>/
      collection_name: "external_docs"
      
      # Vector database overwrite toggle (false = incremental append)
      vectordb_overwrite: false
      
      # Chunking parameters for extracted web Markdown
      chunk_size_chars: 1500
      chunk_overlap_chars: 300
      code_chunk_size: 2000
      
      # Embedding model backend: 'openai' or 'sentence-transformers'
      embed_backend: "sentence-transformers"
      
      # Batch ingestion toggle
      batch: true
      
      # Optional: Docling document conversion integration for digital PDFs
      use_docling: true
      docling_do_ocr: true
      docling_timeout: 300
```

### Environment Variable Bindings

| Environment Variable | Target Component | Default Value | Resolution Scope & Description |
| :--- | :--- | :--- | :--- |
| `SEARXNG_BASE_URL` | `research_agent.py` | `http://localhost:8088` | Base URL for the SearXNG metasearch service. |
| `ORACLE_WEB_WORKERS` | `oracle_agent.py`, `rag_web.py` | `1` | Worker thread count for concurrent URL downloading via ThreadPoolExecutor. |
| `ORACLE_NO_RAG_INGEST` | `oracle_agent.py`, `rag_web.py` | `0` | If set to `1`, disables LanceDB indexing during web fetching (Markdown conversion only). |
| `ORACLE_COLLECTION` | `oracle_agent.py`, `rag_manager.py` | `knowledge` | Active vector database collection name. |
| `ORACLE_RAG_DB_DIR` | `oracle_agent.py`, `rag_manager.py` | *Auto-resolved* | Absolute filesystem path to active `lancedb/` directory. |
| `ORACLE_EMBED_MODEL` | `oracle_agent.py`, `rag_manager.py` | `BAAI/bge-m3` | Embedding model identifier for vector indexing. |
| `ORACLE_EMBED_BACKEND` | `oracle_agent.py`, `rag_manager.py` | `sentence-transformers`| Embedding backend: `openai` (remote HTTP) or `sentence-transformers` (local). |

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

### Diagnostic Error Matrix

| Symptom / Error Signature | Root Cause | Automated Recovery Procedure | Manual Mitigation Workflow |
| :--- | :--- | :--- | :--- |
| `CRITICAL: Rate limit exceeded across local and all public fallback instances` | Local SearXNG instance and public fallback proxies received IP blocks / CAPTCHAs from upstream search engines. | Queries `searx.space` for fresh instances and retries across the top 5 candidates. | Configure paid rotating residential proxies in `~/.config/searxng/settings.yml` under `outgoing.proxies`. |
| `[research] Search failed on http://localhost:8088` | Local SearXNG service is inactive, stopped, or uninitialized. | Emits diagnostic instruction to inspect user systemd service. | Execute `systemctl --user restart searxng.service` or check container logs via `podman logs searxng`. |
| `Executable doesn't exist` or `playwright install` in stderr | Headless Chromium binary missing in local Python environment. | JIT provisioner catches exception and executes `playwright install chromium`. | Pre-install browser binaries manually: `uv run playwright install chromium`. |
| `Error: Invalid --grep regex pattern '<pattern>'` | User provided malformed regular expression to `--grep` or `--grep-exclude`. | Execution halts immediately with exit code 1 to avoid writing unverified files. | Correct regex syntax; escape shell-sensitive or regex metacharacters (`\.`, `\[`, `\]`). |
| `[rag-web] Trafilatura extraction failed ...` | Target website relies on client-side JS rendering (SPA) or anti-bot headers. | Pipeline automatically falls back to Stage D (Headless Playwright Chromium DOM evaluation). | If Playwright is blocked, harvest raw documentation URLs via `--sitemap` to find markdown or `llms.txt`. |
| `[rag-web] Worker error for <url>: ...` | Individual worker thread encountered an HTTP 403, SSL error, or connection timeout. | Thread logs failure to `stderr` and increments skipped count; batch execution continues. | Verify URL accessibility via `curl -IL <url>`; retry with single worker `--workers 1`. |

### Operational Telemetry & Health Checks

Verify local SearXNG systemd service status:
```bash
systemctl --user status searxng.service
```

Inspect active SearXNG public fallback cache:
```bash
cat .aider_factory/logs/cache/searxng_fallbacks.json
```

Audit files indexed in the active LanceDB collection:
```bash
aider-oracle --list-files --collection external_docs
```

Harvest and filter documentation URLs via `llms.txt`:
```bash
aider-research search "https://docs.example.com/llms.txt" --sitemap --grep "api/v1" --out ./urls.txt
```
