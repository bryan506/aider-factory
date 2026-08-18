# AI Factory Pipeline — YAML Configuration Reference

> **Single source of truth** for configuring the AI Factory pipeline. Every parameter is
> documented inline with its behavior, options, and trade-offs. Copy any phase block as a
> starting template for new projects or tasks.
>
> **How to run (use the `factory` launcher or `aider-factory` CLI):**
>
> ```bash
> # Default config (.aider_factory/.env.yml)
> .aider_factory/bash/factory
>
> # Named session with paired configuration
> aider-factory refactor_ohlcv
>
> # Custom config with named session
> aider-factory .env.yml refactor_ohlcv
> ```
>
> **Cost analysis on archived logs** (re-run the aggregator standalone):
>
> ```bash
> ~/.local/share/uv/tools/aider-chat/bin/python .aider_factory/python/aggregate_costs.py .aider_factory/logs/<logfile>.log
> ```
>
> `.aider_factory/bash/factory` is the canonical launcher. It runs the pipeline under
> Aider's bundled Python, which already has every dependency the pipeline can touch
> (yaml + the RAG/OCR stack: lancedb, sentence-transformers, pymupdf, rapidfuzz,
> litellm). Plain `python …` or `uv run --with pyyaml …` only works for configs that
> do **not** ingest documents (`run_ocr_rag: false` everywhere) — the moment a phase
> ingests, those launchers fail with `ImportError: lancedb`. When in doubt, use
> `factory`; it always works.

---

## Conceptual Overview

The pipeline is a **DAG (Directed Acyclic Graph)** of AI-assisted tasks. Each `phase` in the
YAML becomes one or more tasks in the graph. Tasks within and across phases are automatically
chained by file dependency — a phase that processes `file_A` will wait for the previous phase's
`file_A` task to finish before starting.

Each task launches [Aider](https://aider.chat) — an AI pair programmer — with a precise set of
files, models, API endpoints, and instructions. The pipeline handles retries, context management,
and test execution automatically based on the toggles you configure below.

**The pipeline is fully language agnostic.** The test command, test runner script, and markdown
plan templates are the only language-specific components. Swap those three things to use this
pipeline on Python, Rust, Go, JavaScript, or any other codebase.

---

## Architecture: Two-Model Architect/Editor Design

Every phase uses two distinct AI models working together via Aider's native Architect/Editor pattern:

- **Architect model** — A high-reasoning model that reads the plan, analyzes the code, and
  writes detailed implementation instructions. It does NOT directly touch files.
- **Editor model** — A fast, code-focused model that receives the architect's instructions and
  applies the actual file edits using search/replace blocks.

This separation means you can use an expensive, slow reasoning model for planning (paying for
its tokens once per attempt) while using a cheaper, faster model for the repetitive work of
applying edits. You can also mix providers freely — cloud architect with local editor, for example.

---

## Iteration Strategy Reference

The `auto_test` and `loop_aider_test` settings combine to give you precise control over how
aggressively the pipeline retries failing tests and how much architect involvement each retry gets.

| `loop_aider_test` | `auto_test` | Max attempts | Architect input  | Best for                         |
| ----------------- | ----------- | ------------ | ---------------- | -------------------------------- |
| 1                 | false       | 1            | Every attempt    | Single-shot, review manually     |
| 3                 | false       | 3            | Every attempt    | Focused bugs, logic errors       |
| 3                 | true        | 9            | Every 3 attempts | Faster iteration, simpler fixes  |
| 5                 | false       | 5            | Every attempt    | Stubborn bugs, maximum oversight |
| 5                 | true        | 15           | Every 3 attempts | Maximum automation               |

### Final Test Verification (`Task.final_check`) & Soft Failure (`Task.soft_fail`)

- **Code Mode (`Task.final_check`)**: In code test-fixing loops, attempt $N$ verifies the edits made in attempt $N-1$. After outer loop exhaustion, `final_check: True` re-runs `test_cmd` once to verify whether the final edit passed, ensuring accurate final success/failure status.
- **Review Mode (`Task.soft_fail`)**: In evidence apply loops, loop exhaustion is treated as a soft success (`soft_fail: True`). Judgment is deferred to the downstream `finalize` task, which performs deterministic quote promotion and unsupported tagging.

---

## Pair Programming vs. Autonomous Mode

| Feature / Aspect | Autonomous (`pair_programming: false`) | Pair Programming (`pair_programming: true`) |
| :--- | :--- | :--- |
| **Startup** | Plan template auto-executed as `--message` | Plan loaded as context, human drives conversation |
| **Control & PTY** | Pipeline drives tasks non-interactively | Wrapped in `script -qfe` PTY for interactive CLI |
| **Test Running** | Automatic via `test_cmd` | Manual via `/test` or `/run <cmd>` in Aider chat |
| **Oracle Queries** | Programmatic or model-driven shell | Interactive `/run aider-oracle` or `/run aider-oracle --debate` |
| **Evidence Validation** | Auto-gated by `validations_context_check.sh` | Interactive `/run aider-validate` or script execution |
| **Evidence Healing** | Auto-edit pass via `apply_evidence_template.md` | Human reviews findings & instructs Aider to apply fixes |
| **Adding Files** | Declared in YAML before launch | `/add <file>` during active session |
| **Retry Loops** | Up to `loop_aider_test` outer loops | Single interactive session, human-driven retries |
| **Best For** | Batch runs, overnight automation | Deep research, strategy drafting, rapid verification |

### Optimizing for Pair Programming (KV Cache Preservation)

When in `pair_programming: true` mode, preserving the LLM's KV cache is critical for fast and cost-effective interactions. If the context window shifts (e.g., via chat summarization, repo map rebuilds, or unwanted autonomous formatting), the cache drops and must be recalculated.

To prevent this and lock the context, apply the following optimizations before launching an interactive session:

**1. Update `.aider_factory/.aider.conf.yml`**
Disable the repo map auto-refresh and increase the chat history limit so Aider never summarizes the conversation behind the scenes:

```yaml
max-chat-history-tokens: "100000"
map-tokens: "0"
map-refresh: manual
```

**2. Update `.aider.model.settings.yml` (Model Overrides)**
Force the architect model into a purely conversational mode (`ask`) so it doesn't attempt autonomous file edits, and disable thinking tokens to prevent cache-busting reasoning loops:

```yaml
- name: your/architect-model:latest
  edit_format: ask
  extra_params:
    think: false
  accepts_settings:
    - thinking_tokens: 0
```

**3. Offload Git Commits (The Weak Model)**
By default, Aider generates a Git commit message after every edit. This uses a new System Prompt which instantly invalidates your Architect's KV cache. To prevent this, offload commits to a fast, cheap model in `.aider_factory/.aider.conf.yml`:

```yaml
weak-model: "gemini/gemini-3.5-flash" # Highly recommended for pair programming!
```

**4. UI & Color Customization**
Aider's default neon green prompt (`architect>`) can be jarring. You can customize the CLI colors in `.aider_factory/.aider.conf.yml` using standard hex codes. A soft, dark orange works great in both light/dark modes:

```yaml
user-input-color: "#d97706" # Changes prompt text and file context lists
```

---

## DAG Pipeline Example (5-Phase Project)

```
Phase 1 "Implement"         job1_fileA ──► job1_fileB
                                  │               │
                                  ▼               ▼
Phase 2 "Validate"          job2_fileA ──► job2_fileB
                                  │               │
                                  ▼               ▼
Phase 3 "Unit Tests"        job3_fileA ──► job3_fileB
                                  │               │
                                  ▼               ▼
Phase 4 "Write Int. Tests"  job4_fileA ──► job4_fileB
                                  │               │
                                  ▼               ▼
Phase 5 "Run Int. Tests"    job5_fileA ──► job5_fileB
```

Each node is one Aider session. Nodes run sequentially left-to-right, top-to-bottom.
A failed node does NOT block subsequent nodes — the pipeline always attempts every
configured task, allowing partial success across a multi-file run.

---

## Full Annotated Configuration

```yaml
# =============================================================================
# AI FACTORY PIPELINE CONFIGURATION
# =============================================================================
#
# QUICKSTART: Copy this file, rename it, adjust the phases for your task,
# and run with:
#   .aider_factory/bash/factory .aider_factory/your_config.yml
#
# You can maintain multiple .yml config files side-by-side for different
# projects, tasks, or operational modes (autonomous vs. pair programming).
# =============================================================================

# -----------------------------------------------------------------------------
# PROJECT IDENTITY
# -----------------------------------------------------------------------------

name: "My Project"
working_directory: "/path/to/project"

# 1. DISPLAY & RETRY CONTROLS
colors:
    architect_debate: "#38bdf8" # teal — architect turns in ask-mode debates
    oracle_debate: "#d3869b" # gruvbox pink — oracle turns in debates

test_command_prefix: "docker exec -i --user myuser -w /path/to/project -e RETICULATE_PYTHON=/home/myuser/.venv-rocker/bin/python3 rocker-rstudio"
test_runner: "Rscript .aider_factory/tests/run_tests.R {file}"
test_naming_and_path: "tests/testthat/test-{stem}.R"
loop_aider_test: 3

## above test_ values resolve to "test_cmd = f"{test_command_prefix} {test_runner.replace('{file}', specific_test_file)}" in the source scripts. Adjust for desired language and test behavior if aider-helper does not get it right.

# --- Python Multi-Suite Recipe (Unit + E2E Simultaneous Execution) ---
# test_command_prefix: ""
# test_runner: "uv run --with pytest pytest src/aider_factory/tests/aider_factory_tests/test_validator*.py src/aider_factory/tests/aider_factory_tests/end-to-end/test_e2e_*.py"
# test_naming_and_path: ""
#
# When test_naming_and_path is "", the full command in test_runner is executed as-is:
#   1. Bare `/test` runs all unit and E2E test suites simultaneously.
#   2. The autonomous test-healing loop (`iterate_test: true`) verifies edits against both suites on every cycle.

# 3. GLOBAL API ENDPOINTS (Unified: All network addresses live here)
endpoints: # set multiple local endpoints, ignored when cloud model chosen
    architect_api_base: "http://192.168.100.2:8080/v1"
    editor_ollama_api: "http://192.168.100.1:8080/v1"
    editor_test_ollama_api: "http://192.168.100.1:8080/v1"
    rag_agent_api: "http://192.168.100.1:8080/v1"
    grounding_agent_api: "http://192.168.100.1:8090/v1"
    ocr_api_base: "http://192.168.100.2:8081/v1"
    embed_api_base: "http://192.168.100.1:8080/v1"

# =============================================================================
# PHASES
# =============================================================================
# Phases run in order from top to bottom. Each phase is a self-contained unit
# of work with its own models, files, toggles, and plan templates.
#
# DAG CHAINING:
#   - Within a phase: tasks run per target_file, chained sequentially.
#   - Across phases: the last task for each file in Phase N becomes the
#     dependency for the first task for that file in Phase N+1.
#   - A FAILED task does not halt the pipeline. All subsequent tasks still
#     run, allowing partial success across a multi-file, multi-phase run.
#
# TYPICAL PHASE SEQUENCE:
#   Phase 0: RAG & OCR         — ingest docs to LanceDB, build templates interactively via Oracle
#   Phase 1: Implement         — write the code changes
#   Phase 2: Validate          — review logic, write unit tests
#   Phase 3: Unit Test Loop    — iterate until unit tests pass
#   Phase 4: Integration Tests — write integration tests
#   Phase 5: Int. Test Loop    — iterate until integration tests pass
#
# You can freely add, remove, reorder, enable, or disable phases.
# =============================================================================

phases: # DAG phases, name multiple phase for multi-stage workflows if requested
  - name: "Code — Implement, Test, Debate-Escalate"
    enabled: true

    models:
        architect_agent: "gemini/gemini-3.6-flash"
        editor_agent: "gemini/gemini-2.5-flash"
        editor_agent_test: "gemini/gemini-2.5-flash"
        editor_agent_test_fallback: "gemini/gemini-2.5-flash"
        rag_agent: "gemini/gemini-2.5-flash"
        ocr_agent: "glm-ocr-f16:LATEST" # no prefix since litellm direct
        embed_model: "qwen3-embedding-8b-8k:LATEST" # no prefix
        grounding_agent: "openai/minicheck-flan-t5-large"

    rag:
        collection_name: "BaseFeatures_lib" # folder name for all rag content
        batch: true # a table per file/directory or all in one table
        retrieval_mode: top_k # no_retrieve, top_k, or full_document
        run_ocr_rag: false # can turn off/on to skip OCR step
        vectordb_overwrite: false # rewrite all documents to lanceDB
        use_docling: true # fast-path digital document extraction (PDF, DOCX, PPTX, XLSX, HTML)
        docling_do_ocr: true # internal OCR for hybrid/image pages in Docling
        docling_timeout: null # Timeout in seconds for Docling conversion (null = unlimited)
        ocr_prompt: "Extract text, tables, math, code, and documentation into clean Markdown. Preserve all structural integrity."
        query_prefix: "Instruct: Given a coding or financial query, retrieve relevant passages\nQuery: " # prefix prepended to embedding query
        chunk_size_chars: 800 # Max characters per text chunk
        chunk_overlap_chars: 100  # Overlap characters on consecutive chunks
        top_k: 30  # Number of semantic chunks retrieved per query
        cer_threshold: 0.05 # OCR Character Error Rate before text fallback
        ocr_max_retries: 2  # Number of OCR attempts on transient failures
        ocr_parallel: 8 # Number of parallel OCR workers (1 per page)
        code_chunk_size: 2000 # character length for AST-parsed code chunks
        ocr_max_tokens: 4096  # max output tokens per OCR page worker (e.g. 4096 tokens)
        embed_backend: "sentence-transformers" # openai, sentence-transformers
        working_repo: "" # optional override; defaults to basename of working_directory (used for RAG exclusion)
        code_exts: null # Override code extensions to ingest (e.g., [.py, .R])
        text_doc_exts: null  # Override text extensions (e.g., [.md, .txt])
        ignore: null  # Override directories to skip during ingestion scanning

    oracle:
        start_job: false # true = REVIEW mode (generate review), false = CODE mode
        template: "src/aider_factory/markdown/internal/analyze_bugs.md" # REVIEW mode: review generation template; CODE mode: debug debate template
        full_document: false # Send entire paper text instead of chunks
        pre_edit_debate:
            enabled: false # Hold debate before making any code edits
            job_debate_template: ""

    toggles:
        pair_programming: true # Interactive mode with terminal chat
        run_job_one: true # Run first edit phase (implement plan)
        run_job_two: true # Run second edit phase (write tests)
        iterate_test: true # Loop tests automatically until they pass
        auto_test: false # Let Aider run tests natively (3 loops)
        sticky_context: true # Keep edits from prior tasks in context

    validation:
        enabled: false # Enable strict quote-checking on reviews
        validation_tag: "evidence" # Tag used to identify quotes
        region_threshold: 0.60 # Cosine similarity cutoff for matches
        region_margin: 2 # Extra lines of context around matches
        region_paragraphs: 0 # Paragraphs to check above/below header limits
        region_top_k: 5 # Chunks to fetch for each quote check
        validation_loops: 3 # Max heal attempts for ungrounded quotes
        redo_oracle_job: false # Force generator to rerun every time
        verify_all_claims: false # Validate all claims, not just failed
        entail_threshold: 0.5 # Minimum entailment verifier score

    escalation_debate:
        loops: 4 # Maximum debate turns per round
        rounds: 2 # Number of debate rounds to run
        pass_history: true # Carry debate context to next round

    files:
        target_files: [] # allowed to edit (e.g., ["src/main.py"])
        extra_editable_files: [] # may also be edited, but different use case
        test_files: [] # Optional test files; if empty created from <stem>.lang
        context_files_job: [] # read only context files for job one
        context_files_test: [] # read only context files for testing jobs

    plans:
        job_one_plan: "markdown/templates/general.md"
        job_two_plan: "markdown/templates/testing.md"
        iterate_plan: "markdown/templates/testing_unit_iterate.md"

# =============================================================================
# CONFIGURATION CROSS-VALIDATION MATRIX
# =============================================================================
#
# Field Path | Layman Explanation & Execution Mechanics | Edge Cases & Optimization
# -----------------------------------------------------------------------------
# colors.architect_debate / oracle_debate
#   Sets 24-bit ANSI terminal colors for debate turns.
#   Invalid hex codes default to ANSI #38bdf8 (blue) and #d3869b (pink).
#
# test_command_prefix / test_runner
#   Execution wrapper (Docker/SSH) and command template applied to test files.
#   Substitutes {file} dynamically. Keep prefix empty "" if running natively on host.
#
# loop_aider_test
#   Global outer retry loops for test-fixing passes.
#   In review mode, overridden per phase by validation.validation_loops.
#
# endpoints.grounding_agent_api
#   Dedicated endpoint for claim-faithfulness verifier (minicheck_server.py).
#   Unreachable endpoint falls back to LanceDB cosine similarity automatically.
#
# rag.batch
#   true = shared corpus table (coll_repo_code). false = isolated per-doc table.
#   Use batch:true for codebase/library search; batch:false for per-paper reviews.
#
# rag.use_docling / rag.docling_do_ocr / rag.docling_timeout
#   use_docling: true enables isolated high-fidelity Docling extraction for digital PDFs, DOCX, PPTX, XLSX, HTML, and AsciiDoc documents.
#   docling_do_ocr: true enables internal OCR for hybrid/scanned pages. docling_timeout specifies max runtime per document.

# rag.code_chunk_size
#   Character limit for Tree-Sitter AST code chunks (default: 2000).
#
# rag.ocr_parallel / rag.ocr_max_tokens
#   Parallel worker threads for page OCR (default: 8) and max tokens per page worker (default: 4096).
#
# rag.working_repo
#   Folder name used to filter out active target/editable files during ingestion.
#   Defaults to basename(working_directory). Override if repo folder name differs.
#
# oracle.start_job / oracle.pre_edit_debate.enabled
#   start_job: true sets REVIEW mode (generate review); false sets CODE mode.
#   pre_edit_debate.enabled: true runs Architect <-> Oracle draft debate before code editing.
#
# validation.region_paragraphs / validation.redo_oracle_job
#   region_paragraphs: full paragraphs expanded above/below quote during region check.
#   redo_oracle_job: false reuses existing review output file without re-calling Oracle generator.
#
# validation.verify_all_claims / validation.entail_threshold
#   verify_all_claims: true scores claims around ALL quotes (annotates drift without demoting tags).
#   entail_threshold: support probability cutoff (default: 0.5) for MiniCheck verifier.
#
# escalation_debate.loops / escalation_debate.rounds / escalation_debate.pass_history
#   loops: max Architect <-> Oracle turns per debate round.
#   rounds: debate -> apply -> re-verify escalation cycles.
#   pass_history: true retains KV cache and chat session history across rounds.
# =============================================================================

# =============================================================================
# MODEL REFERENCE
# Paste model strings directly into the models: section above.
# =============================================================================

# --- Cloud / API Models (require API keys set as environment variables) ---
# gemini/gemini-3.1-pro-preview           High capability, long context (GEMINI_API_KEY)
# gemini/gemini-3.5-flash                 Fast iteration and test edits (GEMINI_API_KEY)
# gemini/gemini-3.7-flash                 High capability with reasoning_effort support (GEMINI_API_KEY)
# lm_studio/qwen3.8-27B-90k-think:LATEST  Local high-capacity model with 8192 thinking tokens
# lm_studio/qwen3.8-27B-90k-q5think:LATEST Local quantized model with 8192 thinking tokens
# github_copilot/gpt-5.4                  GitHub Copilot (Copilot auth)
# vertex_ai/claude-3-7-sonnet@20250219    GCP Vertex AI Claude 3.7 (GCP Auth)

# --- Local Models via Ollama ---
# ollama/qwen3.5-122B-80k:latest          Large, high quality
# ollama/qwen3.6-35B-80k:latest           Medium, fast
# ollama/qwen2.5-coder:1.5b               Tiny, very fast (simple edits)

# --- Local Models via OpenAI-compatible proxy (e.g. LiteLLM at port 11435) ---
# openai/minimax-229b-ud-iq4nl:latest
# openai/minimax-179b-80k:latest
# openai/qwen35-212B-80k:latest
# openai/gpt-oss-64k:latest

# Complete Database Maintenance CLI:
# oracle --list-files
# oracle --add-file <path1> <path2> ...
# oracle --add-table <folder1> <folder2> ...
# oracle --add-web <url1> [url2...]
# oracle --add-web --file <urls.txt>
# oracle --add-web --file <urls.txt> --no-rag
# oracle --add-web --file <urls.txt> --workers 8
# oracle --rm-file <filename>
# oracle --rm-table <table_name>
# oracle --rm-db
#
# Standalone Web Research & Sitemap Discovery CLI:
# aider-research search "<query>" [--academic] [--top N] [--links-only] [--out <file>]
# aider-research search "<url>" --sitemap [--grep "<pat>"] [--grep-exclude "<pat>"] [--out <file>]
```
