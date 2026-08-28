# AI Factory Pipeline — YAML Configuration Reference

> **Single source of truth** for configuring the AI Factory pipeline. Every parameter is
> documented inline with its runtime behavior, codepaths, and multi-toggle combinations. Copy any phase block as a
> starting template for new projects or tasks.
>
> **How to run (use the `factory` launcher or `aider-factory` CLI):**
>
> ```bash
> # Default config (.aider_factory/.env.yml)
> .aider_factory/bash/factory
>
> # Named session with default configuration
> aider-factory my_session
>
> # Custom config with named session
> aider-factory .aider_factory/.env_custom.yml my_session
> ```
>
> **Cost analysis on archived logs** (re-run the aggregator standalone):
>
> ```bash
> ~/.local/share/uv/tools/aider-chat/bin/python .aider_factory/python/aggregate_costs.py .aider_factory/logs/<logfile>.log
> ```
>
> `.aider_factory/bash/factory` is the canonical launcher. It runs the pipeline under
> Aider's bundled Python, which includes all required dependencies (PyYAML, LanceDB,
> Sentence-Transformers, PyMuPDF, RapidFuzz, LiteLLM, Playwright, Docling).

---

## Conceptual Overview & Execution Modes

The pipeline executes a **Directed Acyclic Graph (DAG)** of AI-assisted tasks. Each `phase` declared
in the configuration YAML translates to a sequence of execution nodes per target file. Tasks are automatically
chained by file dependency across phases.

The pipeline operates in two primary modes determined by the phase configuration:

1. **Code Mode (`oracle.start_job: false` or standard edit toggles active):**
   * **Job 1 (Implementation):** Applies primary code or architecture modifications using `plans.job_one_plan`.
   * **Job 2 (Spec Audit / Validation):** Performs a second-pass audit or mathematical validation using `plans.job_two_plan`.
   * **Job 3 (Write Tests):** Authors unit or integration tests using `plans.job_three_plan`.
   * **Job 4 (Iterate / Fix Tests):** Loops test execution and pushes compiler/test output back to the model until all tests pass.
   * **Pre-Edit Debate (`oracle.pre_edit_debate`):** Inserts an ask-mode debate before Job 1, Job 2, or Job 3 (`insert_debate: [1, 0, 0]`) to reach consensus before files are modified.
   * **Escalation Debate (`escalation_debate`):** If tests fail after loop exhaustion, launches a multi-turn Architect <-> Oracle debate and applies the consensus verdict.

2. **Review / Evidence Grounding Mode (`oracle.start_job: true` or `validation.enabled: true`):**
   * **Generate (Oracle):** Synthesizes structured markdown reviews directly from ingested source documents via LanceDB.
   * **Autofix (Validator):** Performs deterministic anchored-stitch repairs on quote anchors before LLM invocation.
   * **Heal (Agent Iterate Loop):** Iteratively refines quotes and passages against the deterministic validator gate.
   * **Finalize:** Deterministically tags supported vs. unsupported claims based on debate and audit ledgers.

---

## Architecture: Two-Model Architect/Editor Pattern

Every task leverages two distinct model roles:
* **Architect Model (`architect_agent`):** A high-reasoning model that inspects context, analyzes failures, and formulates implementation specifications. It does not directly write file edits.
* **Editor Model (`editor_agent` / `editor_agent_test`):** A fast, surgical code model that consumes the Architect's proposal and executes search/replace blocks on disk.
* **Fallback Editor (`editor_agent_test_fallback`):** An optional escalation model dynamically substituted on test attempt $> 0$ if the primary editor fails to resolve a test error.

---

## Iteration Strategy & Multi-Toggle Synergy

The combination of `loop_aider_test`, `auto_test`, and `max_aider_loops` governs the automated test repair cycle:

| `loop_aider_test` | `auto_test` | Total Attempts | Architect Interaction | Optimal Use Case |
| :---: | :---: | :---: | :---: | :--- |
| `1` | `false` | 1 | Every attempt | Single-shot run, manual review |
| `3` | `false` | 3 | Every attempt | Focused debugging, complex logic fixes |
| `3` | `true` | 9 | Every 3 attempts | Fast iteration, automated test repair |
| `5` | `false` | 5 | Every attempt | Hard bugs, maximum Architect oversight |
| `5` | `true` | 15 | Every 3 attempts | Deep autonomous test fixing |

### Verification Invariants
* **`Task.final_check` (Code Mode):** Because attempt $N$ verifies the edit made in attempt $N-1$, loop exhaustion could leave the final edit unverified. `final_check: true` automatically re-runs the test suite once after the outer loop finishes to establish honest success/failure.
* **`Task.soft_fail` (Review Mode):** When applying debate verdicts in grounding mode, loop exhaustion is treated as a soft success (`soft_fail: true`), deferring final judgment to the deterministic `finalize` step.

---

## Pair Programming Mode (`pair_programming: true`)

When `pair_programming: true` is enabled, autonomous execution loops are suspended:
* Aider is wrapped in a PTY (`script -qfe`) allowing interactive terminal chat with live streaming.
* The plan template is loaded as read-only context (`--read`) rather than an auto-executed command message (`--message`), allowing the human to drive the conversation.
* The user can run interactive slash commands (`/test`, `/run aider-oracle`, `/run aider-validate`, `/add <file>`).

### Preserving KV-Cache in Pair Programming
To prevent context eviction and save LLM token costs during long paired sessions:
1. Set `map_tokens: 0` and `map_refresh: "manual"` to eliminate background repository map recalculations.
2. Set `max_chat_history_tokens: 100000` to prevent automatic conversation truncation.
3. Configure `auto_commits: false` or assign a lightweight `weak-model` in `.aider.conf.yml` to prevent commit message generation from purging the architect's context cache.

---

## Complete Annotated Configuration Schema

```yaml
# =============================================================================
# AI FACTORY PIPELINE CONFIGURATION
# =============================================================================

# -----------------------------------------------------------------------------
# 1. PROJECT IDENTITY & WORKSPACE ROOT
# -----------------------------------------------------------------------------
name: "My Project"
working_directory: "/path/to/project" # Target repository working directory

# -----------------------------------------------------------------------------
# 2. DISPLAY & DEBATE COLOR SCHEME (24-bit TrueColor)
# -----------------------------------------------------------------------------
colors:
    architect_debate: "#38bdf8" # Teal — Architect turns in debate streams
    oracle_debate: "#d3869b"    # Gruvbox pink — Oracle turns in debate streams

# -----------------------------------------------------------------------------
# 3. GLOBAL TEST HARNESS & LINTING CONTROLS
# -----------------------------------------------------------------------------
test_command_prefix: ""         # Optional command prefix (e.g., Docker wrapper, SSH)
test_runner: "uv run --with pytest pytest {file}" # Execution command template substituting {file}
test_naming_and_path: "src/aider_factory/tests/aider_factory_tests/end-to-end/test_e2e_{stem}.py" # Default test mapping
lint_cmd: null                  # Optional custom linter command string
auto_lint: true                 # Run linter automatically after edits
loop_aider_test: 3              # Outer test retry loops in autonomous mode

# -----------------------------------------------------------------------------
# 4. GLOBAL API ENDPOINTS (Unified Proxy Routing)
# -----------------------------------------------------------------------------
endpoints:
    architect_api_base: "http://192.168.100.2:8080/v1"
    editor_api: "http://192.168.100.1:8080/v1"
    editor_api_fallback: "http://192.168.100.1:8080/v1"
    rag_agent_api: "http://192.168.100.1:8080/v1"
    grounding_agent_api: "http://192.168.100.1:8090/v1" # MiniCheck entailment server
    ranking_api_base: null                              # Remote reranker endpoint (null = local model)
    ocr_api_base: "http://192.168.100.2:8081/v1"
    embed_api_base: "http://192.168.100.1:8080/v1"

# -----------------------------------------------------------------------------
# 5. EXECUTION PHASES (DAG Task Definitions)
# -----------------------------------------------------------------------------
phases:
  - name: "Code — Implement, Test, Debate-Escalate"
    enabled: true

    # Model Routing for this Phase
    models:
        architect_agent: "gemini/gemini-3.7-flash"
        editor_agent: "gemini/gemini-3.6-flash"
        editor_agent_test: "gemini/gemini-3.6-flash"
        editor_agent_test_fallback: "gemini/gemini-3.6-flash" # Escalation model for attempt > 0
        rag_agent: "gemini/gemini-3.6-flash"                  # Knowledge Oracle model
        ranking_agent: "jinaai/jina-reranker-v3.5"            # Cross-encoder reranker model
        ocr_agent: "gemini/gemini-3.6-flash"                  # Vision model for document OCR
        embed_model: "gemini/text-embedding-004"              # Dense vector embedding model
        grounding_agent: "openai/minicheck-flan-t5-large"     # Claim entailment verifier

    # Retrieval-Augmented Generation & Ingestion Settings
    rag:
        collection_name: "working_repo_lib" # Target LanceDB collection folder
        batch: true                         # true = shared corpus table; false = per-doc isolated tables
        retrieval_mode: top_k               # top_k, full_document, or no_retrieve
        use_docling: true                   # Fast-path digital document extraction (PDF, DOCX, XLSX, HTML)
        docling_do_ocr: true                # Enable internal OCR for hybrid/scanned pages in Docling
        docling_timeout: null               # Timeout in seconds for Docling conversion (null = unlimited)
        run_ocr_rag: false                  # Trigger ingestion on phase start (false = use existing DB)
        vectordb_overwrite: false           # Overwrite existing LanceDB tables on ingestion
        ocr_prompt: "<|grounding|>Convert the document to markdown."
        query_prefix: "Instruct: Given a coding or financial query, retrieve relevant passages\nQuery: "
        chunk_size_chars: 1500              # Maximum characters per text chunk
        chunk_overlap_chars: 300            # Overlap character length between sequential chunks
        recall_k: 75                        # Stage 1 vector candidates fetched from LanceDB
        top_k: 20                           # Stage 2 candidates returned after cross-encoder reranking
        cer_threshold: 0.05                 # Character Error Rate threshold before OCR fallback
        ocr_max_retries: 2                  # Max retry attempts on OCR failures
        ocr_parallel: 8                     # Number of parallel page OCR workers
        code_chunk_size: 2000               # Character length for Tree-Sitter AST code chunks
        ocr_max_tokens: 4096                # Max generation tokens per OCR worker
        embed_backend: "sentence-transformers" # "sentence-transformers" or "openai"
        working_repo: ""                    # Repository folder name for RAG self-exclusion
        code_exts: null                     # Custom code extensions (e.g., [.py, .R, .rs])
        text_doc_exts: null                 # Custom text extensions (e.g., [.md, .txt])
        ignore: null                        # Custom directory ignore patterns for ingestion

    # Oracle & Pre-Edit Deliberation
    oracle:
        start_job: false                    # true = REVIEW mode; false = CODE mode
        template: "src/aider_factory/markdown/internal/analyze_bugs.md"
        full_document: false                # Inject complete document text instead of retrieved chunks
        pre_edit_debate:
            enabled: false                  # Hold Architect <-> Oracle debate before editing files
            insert_debate: [1, 0, 0]        # 3-tuple: [Job 1 debate, Job 2 debate, Job 3 debate]
            loops: 3                        # Max debate turns per job
            job_debate_template: ""         # Template path or list [/j1_tmpl, /j2_tmpl, /j3_tmpl]
            job_debate_collection: ""       # Collection name or list [/coll1, /coll2, /coll3]

    # Aider Runtime & Session Toggles
    toggles:
        pair_programming: true              # PTY interactive mode vs autonomous pipeline
        shared_history: false               # false = isolate chat history per target file
        run_job_one: true                   # Execute Job 1 (Implementation)
        run_job_two: false                  # Execute Job 2 (Spec Audit / Validation)
        run_job_three: false                # Execute Job 3 (Write Tests)
        iterate_test: false                 # Loop test suite automatically until passing
        auto_test: false                    # Let Aider iterate tests natively in 3-loop batches
        sticky_context: false               # Retain completed files from prior tasks in context
        map_tokens: 0                       # Repository map token budget (0 = disabled)
        map_refresh: "manual"               # Repo map refresh mode ("manual", "auto", "always")
        map_multiplier_no_files: 0          # Multiplier for map size when no files are loaded
        max_chat_history_tokens: 100000     # Chat history token budget ceiling
        yes_always: false                   # Auto-confirm all prompts non-interactively
        auto_accept_architect: false        # Auto-accept Architect proposal to editor
        auto_commits: true                  # Auto-commit git changes after each edit
        suggest_shell_commands: true        # Allow model to propose shell commands
        detect_urls: false                  # Scrape URLs found in model responses
        disable_playwright: false           # Prevent automated browser installations

    # Evidence Grounding & Validation Settings
    validation:
        enabled: false                      # Enable strict substring grounding audit
        validation_tag: "evidence"          # Tag name used for grounded quotes
        region_threshold: 0.60              # Cosine similarity cutoff for fuzzy region matching
        region_margin: 2                    # Extra lines of context around matches
        region_paragraphs: 0                # Number of full paragraphs to expand around matches
        region_top_k: 5                     # Chunks to fetch for quote region verification
        validation_loops: 3                 # Max heal attempts for ungrounded quotes
        redo_oracle_job: false              # Re-run Oracle document generator on every pass
        verify_all_claims: false            # Score claims around all quotes, not just ungrounded
        entail_threshold: 0.5               # Entailment probability cutoff for MiniCheck verifier

    # Post-Failure Escalation Debate
    escalation_debate:
        loops: 4                            # Maximum debate turns per round
        rounds: 2                           # Number of debate -> apply -> test cycles
        pass_history: true                  # Carry accumulated debate history to the next round

    # Target & Context Files
    files:
        target_files: []                    # Editable files (e.g. ["src/main.py"])
        extra_editable_files: []            # Secondary editable files (e.g. shared utilities)
        test_files: []                      # Explicit test files; auto-derived if empty
        context_files_job: []               # Read-only context for Job 1 & Job 2
        context_files_test: []              # Read-only context for Job 3 & test loops

    # Markdown Plan Templates
    plans:
        job_one_plan: "markdown/templates/implement.md"
        job_two_plan: "markdown/templates/validate.md"
        job_three_plan: "markdown/templates/testing.md"
        iterate_plan: "markdown/templates/testing_unit_iterate.md"
```

---

## Configuration Cross-Validation Matrix

| Parameter Path | Layman Explanation & Codepath | Edge Cases & Optimization |
| :--- | :--- | :--- |
| `colors.architect_debate` / `oracle_debate` | Sets 24-bit ANSI terminal colors for debate turns in `orchestrate.py`. | Hex strings (e.g. `#38bdf8`) are parsed into ANSI escape sequences. Bad strings fall back to standard colors. |
| `test_runner` / `test_command_prefix` | Defines the test execution command. Formatted dynamically as `{test_command_prefix} {test_runner.replace('{file}', specific_test_file)}`. | If running natively on host, keep `test_command_prefix: ""` empty. For containerized test suites, pass `docker exec -i ...`. |
| `loop_aider_test` | Outer retry loop count in `run_workflow.py` for test-fixing passes. | In Review Mode, this is overridden per phase by `validation.validation_loops`. |
| `models.editor_agent_test_fallback` | Escalation model substituted during iterative test repair on attempt $> 0$. | When an initial cheap editor model fails to fix a test error, Aider automatically escalates to this model on subsequent attempts. |
| `rag.batch` | Controls LanceDB table topology. `true` = single shared table (`collection_name`). `false` = per-document table and per-document `.md` outputs. | Use `batch: true` for codebase search and technical libraries. Use `batch: false` for multi-paper academic reviews. |
| `rag.use_docling` / `docling_timeout` | Enables digital document extraction via Docling before rasterizing to image OCR. | Bypasses slow pixel OCR for clean digital PDFs, Word documents (`.docx`), presentations (`.pptx`), and Excel sheets (`.xlsx`). |
| `rag.recall_k` / `top_k` | Two-stage retrieval parameters in `oracle_agent.py`. `recall_k` vector candidates are fetched from LanceDB, then reranked down to `top_k` via Cross-Encoder. | If reranking is disabled or unavailable, the system truncates candidates to `top_k` directly. |
| `oracle.start_job` | Discriminator between Review Mode (`start_job: true`) and Code Mode (`start_job: false`). | `start_job: true` executes programmatic synthesis before launching validator tasks. `start_job: false` executes Job 1/2/3 code plans. |
| `oracle.pre_edit_debate.insert_debate` | 3-tuple boolean list `[j1, j2, j3]` parsed by `_parse_insert_debate()` in `run_workflow.py`. | Controls exactly which edit jobs receive an Architect <-> Oracle consensus debate before file modifications begin. |
| `oracle.pre_edit_debate.job_debate_template` / `job_debate_collection` | Resolves prompt templates and vector collections for pre-edit debates in `run_workflow.py`. | Accepts either a single string (applied to all active jobs) or a 3-element list `[j1, j2, j3]` to assign dedicated debate prompt templates and vector collections to each respective job. |
| `toggles.pair_programming` | Wraps Aider in a `script -qfe` PTY session for interactive terminal pairing. | Disables non-interactive outer retry loops; plans are loaded via `--read` so the user drives the conversation directly. |
| `toggles.shared_history` | Toggles state isolation. `false` saves separate chat histories per file (`.aider.chat.history_<stem>.md`). | Always use `shared_history: false` when processing multiple independent files to prevent prompt history pollution. |
| `toggles.map_tokens` / `map_refresh` | Controls Aider's repository map size and refresh policy. | Set `map_tokens: 0` and `map_refresh: manual` for isolated single-file tasks to maximize KV-cache reuse. |
| `validation.enabled` / `validation_tag` | Activates exact-substring quote grounding in `validator.py`. | Scans generated documents for `[evidence]...[/evidence]` tags and scores them against source documents using Cosine and MiniCheck entailment. |
| `escalation_debate.rounds` / `pass_history` | Multi-round debate -> apply -> test re-check cycle on persistent test failures. | `pass_history: true` carries accumulated debate context and ledgers across rounds so the model learns from prior attempts. |

---

## Complete Database Maintenance & CLI Reference

### Knowledge Oracle Maintenance (`aider-oracle` / `.aider_factory/bash/oracle`)
```bash
# List all files and tables in the LanceDB database
.aider_factory/bash/oracle --list-files
.aider_factory/bash/oracle --list-tables

# Ingest specific files or entire folders
.aider_factory/bash/oracle --add-file docs/architecture.pdf
.aider_factory/bash/oracle --add-table research_papers/

# Web Ingestion & Sitemap Crawling
.aider_factory/bash/oracle --add-web https://docs.example.com/sitemap.xml
.aider_factory/bash/oracle --add-web --file urls.txt --workers 8

# Deletion & Database Cleanup
.aider_factory/bash/oracle --rm-file old_paper.pdf
.aider_factory/bash/oracle --rm-table legacy_collection
.aider_factory/bash/oracle --rm-db
```

### Standalone Web Research Agent (`aider-research` / `.aider_factory/bash/research`)
```bash
# Standard and academic web search
.aider_factory/bash/research "Explain compound indexing in SQLite"
.aider_factory/bash/research "Transformer attention mechanisms" --academic --top 15

# Sitemap extraction with regex filtering
.aider_factory/bash/research "https://docs.rs/sitemap.xml" --sitemap --grep "tokio" --out tokio_urls.txt
```
