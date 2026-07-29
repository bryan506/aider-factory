# AI Factory Pipeline — YAML Configuration Reference

> **Single source of truth** for configuring the AI Factory pipeline. Every parameter is
> documented inline with its behavior, options, and trade-offs. Copy any phase block as a
> starting template for new projects or tasks.
>
> **How to run (use the `factory` launcher):**
>
> ```bash
> # Default config (.aider_factory/.env.yml)
> .aider_factory/bash/factory
>
> # Custom config (pass any .yml file as the first argument)
> .aider_factory/bash/factory .aider_factory/.env_auto_ocr.yml
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

name: "My Project Refactor"
# ^ Human-readable label for this pipeline run.
# Appears in log output for identification. No functional effect.

working_directory: "/absolute/path/to/your/project"
# ^ REQUIRED. Absolute path to the root of your project (where .git lives).
# All relative file paths declared in the `files:` sections below are
# resolved from this directory.
# Example: "/home/user/projects/my-app"
# Active file exclusion: `working_repo` is auto-derived from
# os.path.basename(working_directory). Any target, editable, or context
# file in the active phase is automatically excluded from the vector store
# during RAG ingestion. Override with rag.working_repo if needed.

# -----------------------------------------------------------------------------
# GLOBAL BEHAVIOUR
# -----------------------------------------------------------------------------

# NOTE: sticky_context is a PER-PHASE toggle — see `toggles.sticky_context` in each
# phase below. It is NOT read at the top level; a top-level `sticky_context:` key
# here is ignored by the pipeline.

test_command_prefix: "docker exec -i --user myuser -w /path/to/project my-container"
# ^ The shell command prefix prepended to every test execution (an execution
# WRAPPER, e.g. docker/ssh, or "" to run on the host). The pipeline builds the
# final command as:   {test_command_prefix} {test_runner with {file} substituted}
#
# Use cases:
#   Docker:   "docker exec -i --user myuser -w /project my-container"
#   Native:   ""  (empty string — runs tests directly on the host)
#   Docker + env vars: "docker exec -i -e MY_VAR=value my-container"
#   SSH:      "ssh user@remotehost"
#   bash:     "bash"  (e.g. to run a validation .sh directly; see test_runner)

test_runner: "Rscript .aider_factory/tests/run_tests.R {file}"
# ^ The language-AGNOSTIC test command template. `{file}` is replaced with the
# test file for the current target. The default shown runs the bundled R
# (testthat) runner; existing R projects need no change. Swap it per language:
#   Python:     "python -m pytest {file}"
#   Rust:       "cargo test"            # ({file} optional)
#   JavaScript: "npm test -- {file}"
#   Run a file directly (e.g. a validation .sh): "{file}"  (pair with prefix "bash")
# Full command example (R): docker exec ... Rscript .aider_factory/tests/run_tests.R tests/testthat/test-my_module.R
# NOTE: the runner script now lives at .aider_factory/tests/run_tests.R (moved from .aider_factory/R/).
# To run internal AI Factory unit tests (Aider environment dependencies), use:
# `bash .aider_factory/tests/run_all.sh`

test_naming_and_path: "tests/testthat/test-{stem}.R"
# ^ Convention used to AUTO-GENERATE a test file path when a phase omits
# files.test_files. `{stem}` = the target file's basename (no extension). Only
# used as a fallback; phases that list test_files explicitly ignore this.
# Python example: "tests/test_{stem}.py"

loop_aider_test: 3
# ^ Number of OUTER retry loops when `iterate_test: true` is set on a phase.
# Each outer loop is a completely fresh Aider session — chat history is wiped,
# models re-initialize, the architect sees the test failure fresh with no
# memory of previous attempts.
#
# Combined behavior with auto_test (see toggles section):
#
#   loop_aider_test: 3, auto_test: false
#     = 3 outer loops x 1 test each
#     = max 3 total attempts
#     = architect diagnoses EVERY failure
#
#   loop_aider_test: 3, auto_test: true
#     = 3 outer loops x up to 3 inner Aider attempts each
#     = max 9 total attempts
#     = architect diagnoses every 3rd failure
#
# Rule of thumb:
#   Simple/clear bugs:  loop_aider_test: 3, auto_test: false  (3 focused attempts)
#   Moderate bugs:      loop_aider_test: 3, auto_test: true   (9 attempts, faster)
#   Stubborn bugs:      loop_aider_test: 5, auto_test: true   (15 attempts)

# -----------------------------------------------------------------------------
# GLOBAL API ENDPOINTS
# Server addresses for your AI models. Each model prefix routes to a specific
# endpoint (see model prefix routing guide in the models section below).
# -----------------------------------------------------------------------------

colors:
  architect_debate: "#38bdf8" # sky blue — architect turns in debates
  oracle_debate: "#d3869b" # gruvbox pink — oracle turns + single query output
# Both are optional. Defaults are used if omitted. These affect the pipeline's
# terminal output only, not Aider's own colors (controlled via .aider.conf.yml).

ocr_api_base: "http://192.168.100.1:8081/v1"
# ^ Dedicated endpoint for the OCR vision model (e.g., a local llama-server running
# GLM-OCR). RAG document ingestion uses this to extract text from images and PDFs.
# Routing: SET = direct HTTP to local server. EMPTY ("") = route through litellm
# for cloud vision models (e.g., ocr_agent: "gemini/gemini-2.5-flash").
# Must be isolated from global LLM flags (like flash-attn) that break vision encoders.

# -----------------------------------------------------------------------------
# GLOBAL KNOWLEDGE ORACLE (RAG/OCR) DEFAULTS
# -----------------------------------------------------------------------------
rag:
  collection_name: "knowledge" # default vector db table and context sub-folder
  overwrite:
    false # false = skip OCR if the table already exists (cache hit).
    # Note: You can also surgically manage, list, add, or delete files/webpages
    # from the database manually using the CLI:
    #   `oracle --list-files`
    #   `oracle --rm-file <filename>`
    #   `oracle --add-file <path>`
    #   `oracle --add-web <url1> [url2...]`         # Ingest web page or .pdf link
    #   `oracle --add-web --file <urls.txt>`        # Ingest line-separated URL file
    # See the Factory Service Manual for the full suite of maintenance commands.
  ocr_agent: "glm-ocr-f16:LATEST" # prefix stripped. Name is CASE-SENSITIVE and must exactly match the models.ini section name
  ocr_prompt: "Extract the text, tables, and mathematical formulas from this page into clean Markdown. Preserve all structural integrity."
  ocr_parallel:
    8 # pages processed concurrently via ThreadPoolExecutor.
    # Match to llama-server --parallel for the vision model.
    # Default 1 (sequential). Sweet spot: 8 on AMD APUs.
  embed_model: "qwen3-embedding-8b-8k:LATEST" # Swap to BAAI/bge-m3 if no GPU api_base is available
  embed_backend: "openai" # "openai" | "sentence-transformers"
  embed_api_base: "http://192.168.100.1:8080/v1"
  # ^ Routing: SET = direct HTTP to /v1/embeddings (bypasses litellm serialization bugs).
  #   EMPTY ("") = route through litellm for cloud embeddings (e.g., embed_model: "gemini/text-embedding-004").
  #   Switching between local and cloud models with different embedding dimensions requires
  #   vectordb_overwrite: true to rebuild all tables (the dim guard catches mismatches).
  query_prefix: "Instruct: Given a coding or financial query, retrieve relevant passages\nQuery: "
  chunk_size_chars: 800 # oversized AST leaf nodes are split via _text_split_fallback()
  chunk_overlap_chars: 100 # at line boundaries with overlap, preserving AST metadata
  top_k: 5
  retrieval_mode: top_k
  cer_threshold: 0.05
  ocr_max_retries: 2

  # --- Code Ingestion Settings (for repo/code RAG) ---
  code_chunk_size: 2000
  # ^ Maximum chunk size (chars) for AST-based code chunking via tree-sitter.
  # Oversized AST leaf nodes are split via _text_split_fallback() at line
  # boundaries with ~20% overlap. Default 2000 (larger than doc chunks for
  # preserving function-level context).

  working_repo: ""
  # ^ Repository name used for active-file exclusion from the vector store.
  # Auto-derived from os.path.basename(working_directory) if empty/unset.
  # Override when working_directory ends in a non-standard path.
  # Active target, editable, and context files are automatically excluded
  # from ingestion to prevent stale code from polluting oracle retrieval.

  code_exts: null
  # ^ File extensions treated as code during ingestion. Default (null) uses
  # the built-in set: .r, .py, .js, .ts, .cpp, .cc, .c, .h, .hpp, .go,
  # .rs, .java, .rb, .sh, .sql. Override with a YAML list to add/remove.

  text_doc_exts: null
  # ^ File extensions treated as text documents (chunked without AST parsing).
  # Default (null) uses: .md, .rmd, .txt, .rst. Override with a YAML list.

  ignore: null
  # ^ Directory names to skip during code ingestion. Default (null) uses:
  # .git, renv, packrat, node_modules, __pycache__, .venv, build, dist,
  # data, .rproj.user. Override with a YAML list.

  # ^ Default retrieval strategy for INTERACTIVE `/run oracle` queries (NOT the
  # programmatic job path, which uses oracle.full_document instead):
  #   top_k         = embed the query, return the top_k closest chunks (default;
  #                   safe for pair-programming and multi-document collections).
  #   no_retrieve   = skip the vector DB; reason directly over the question/--file.
  #   full_document = dump the whole table for the collection (batch:false single-doc).
  # Override per phase via `retrieval_mode:`, or per call via the oracle `--mode` flag.
  #
  # Query truncation: in top_k mode, the query text is truncated to 6000 characters
  # before embedding (_MAX_EMBED_CHARS). This keeps the embedding vector focused on
  # the core issue rather than diluted by large code dumps. Short interactive queries
  # pass through unchanged. See the Factory Service Manual for details.

endpoints:
  architect_api_base: "http://localhost:11435/v1"
  # ^ OpenAI-compatible API base URL for the architect (planning) model.
  # Used for models with the `openai/` prefix.
  # Common setups:
  #   Local LiteLLM proxy:     "http://localhost:11435/v1"
  #   Local Ollama (compat):   "http://localhost:11434/v1"
  #   Remote OpenAI:           "https://api.openai.com/v1"
  #   Remote LiteLLM:          "http://192.168.1.10:11435/v1"
  #
  # Note: Models with the `gemini/` prefix bypass this and use GEMINI_API_KEY
  # from your environment directly. Models with `github_copilot/` are handled
  # natively by Aider via your GitHub Copilot authentication.

  editor_ollama_api: "http://localhost:11434"
  # ^ Ollama API base for the editor model used in job_one (implementation).
  # Used for models with the `ollama/` or `lm_studio/` prefix (maps to LM_STUDIO_API_BASE natively).
  # Default Ollama port is 11434.
  # Point to a remote machine for distributed inference:
  #   "http://192.168.1.100:11434"

  editor_test_ollama_api: "http://localhost:11434"
  # ^ Ollama API base for the editor model used in job_two and iterate_test.
  # Can point to a different port or machine than editor_ollama_api.
  # Useful if you have separate GPU servers for implementation vs. test runs.

  rag_agent_api: "http://192.168.100.2:8080/v1"
  # ^ API base for the Knowledge Oracle side-agent model (used during /run oracle).
  # Can point to a remote OpenAI-compatible router.

  grounding_agent_api: "http://192.168.100.1:8090/v1"
  # ^ API base for the entailment grounding verifier (e.g. a MiniCheck shim).
  # Used when models.grounding_agent is set (see section 7.12 of the Service Manual).
  # Routing: SET = direct HTTP to the verifier. Omit to use cosine-only fallback.
  # Only needed when you deploy the MiniCheck server or an equivalent verifier.

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

phases:
  # ---------------------------------------------------------------------------
  - name: "Implement"
    # ^ Human-readable phase name. Used in terminal logs and to generate task IDs.
    # Task IDs are derived as: {phase_name_slug}_job1_{filename}
    # Example: "Validate & Tests" -> "validate_and_tests_job1_mymodule"
    # Tip: Keep names short and descriptive.

    enabled: true
    # ^ Master on/off switch for this phase.
    # true  = Phase runs normally.
    # false = Phase is completely skipped as if it does not exist.
    #
    # Workflow tip: Once a phase succeeds on your codebase, flip this to false.
    # Re-running the pipeline will skip it and resume from where you left off,
    # saving time and API costs.

    # -------------------------------------------------------------------------
    # VECTOR STORE — Per-phase RAG Context
    # -------------------------------------------------------------------------
    vector_store:
      collection_name: "alpha_strategies"
      # ^ The folder inside `.aider_factory/markdown/lanceDB/` containing
      # raw PDFs/images to ingest, and the name of the LanceDB table. Overrides
      # the global default.
      #
      # ZERO-RAG BYPASS: If you set `collection_name: []` (empty list), the
      # pipeline bypasses RAG/LanceDB entirely for this phase. The Oracle will
      # rely strictly on `target_files` + `context_files_job` injected directly
      # into its prompt (relying purely on its massive LLM context window).

    # -------------------------------------------------------------------------
    # BATCH — How documents in the collection map to LanceDB tables.
    # -------------------------------------------------------------------------
    batch: true
    # ^ true  = ONE shared table for the whole collection (corpus-wide search;
    #           query everything without --collection).
    #   false = one ISOLATED table PER document. Enables focused per-document
    #           queries (`oracle --collection <doc>`) and, combined with a glob in
    #           target_files, one task per document (auto-created .md outputs).
    #           NOTE: there is NO combined table in this mode — a query without
    #           --collection returns nothing.
    # When batch=true, the Oracle uses RRF fusion across all {collection}_* tables.
    # If you pass a bare collection name (e.g. `oracle --collection MyProject`),
    # the Oracle prefix-matches all tables starting with `MyProject_` and fuses them.
    # Fault tolerance: each table build is independently try/except'd — a single
    # failing document does not kill the entire ingestion.

    # -------------------------------------------------------------------------
    # RETRIEVAL_MODE — Per-phase override of rag.retrieval_mode (see global block).
    # -------------------------------------------------------------------------
    retrieval_mode: top_k # top_k | no_retrieve | full_document

    # -------------------------------------------------------------------------
    # ORACLE_AUTO — Programmatic, NON-interactive side-agent job (no Aider).
    # -------------------------------------------------------------------------
    # When present AND pair_programming is false, this phase does NOT open an Aider
    # session. For each target file the Oracle reads `template`, pulls that
    # document's knowledge, and writes the synthesized answer directly to the target
    # file (used for automated literature reviews / summaries). If pair_programming
    # is true, programmatic oracle job is IGNORED (the interactive session wins).
    # oracle:
    #     template: ".aider_factory/markdown/templates/literary_review_template.md"
    #     full_document: true   # whole document (batch:false) vs top_k chunks

    # -------------------------------------------------------------------------
    # TOGGLES — Fine-grained control over what this phase does.
    # -------------------------------------------------------------------------
    toggles:
      run_job_one: true
      # ^ Triggers the primary implementation job.
      # true  = Aider launches with `job_one_plan` as its initial instruction.
      #         The architect reads the plan and instructs the editor to modify
      #         `target_files`. Used for: writing code, refactoring, implementing features.
      # false = Skip implementation. Use when this phase is test-only.

      run_job_two: false
      # ^ Triggers the test-writing job.
      # true  = Aider launches with `job_two_plan` as its initial instruction.
      #         The architect reads the plan and instructs the editor to write
      #         or update the `test_files` for each target.
      # false = Skip test writing.
      #
      # Can be combined with iterate_test:
      #   run_job_two: true  + iterate_test: true  = Write tests, then immediately fix them
      #   run_job_two: false + iterate_test: true  = Fix already-failing tests (no writing step)
      #   run_job_two: true  + iterate_test: false = Write tests only, no fixing loop

      iterate_test: false
      # ^ Enables the iterative test-fixing loop.
      # true  = After any test-writing step (or standalone), run the test suite,
      #         capture failures, feed them to the architect+editor for fixing.
      #         Repeats up to `loop_aider_test` times (see global settings).
      #         Requires test_files and a valid test command to be configured.
      #         Note: If pair_programming is true, the automated pre-test baseline
      #         is skipped, and you drop directly into the interactive session.
      # false = No test running in this phase.

      auto_test: false
      # ^ Controls the internal retry mechanism when iterate_test: true.
      #
      # false (ARCHITECT-DRIVEN — default, maximum oversight):
      #   Each outer loop = 1 test run -> fresh Aider session -> architect diagnosis.
      #   The architect sees every single failure and provides fresh targeted instructions.
      #   Chat history is wiped between every attempt. No context carryover.
      #   Best for: complex bugs, logic errors, cases requiring careful reasoning.
      #
      # true (AIDER-DRIVEN BATCHES — faster, less oversight):
      #   Each outer loop = up to 3 test attempts handled natively inside Aider.
      #   The editor model retains context across those 3 inner attempts.
      #   After exhausting 3 inner attempts, Python wipes history and the
      #   architect reviews the failure fresh for the next outer loop.
      #   Best for: simpler bugs, syntax errors, faster iteration.
      #
      # See "Iteration Strategy Reference" table above for the full matrix.

      pair_programming: false
      # ^ Switches this phase from fully autonomous to interactive (human-in-the-loop).
      #
      # false (AUTONOMOUS — default):
      #   Pipeline runs without human input. Plan is auto-executed, edits applied,
      #   tests run, loops repeat. Best for: batch runs, overnight automation,
      #   well-defined repeatable tasks.
      #
      # true (INTERACTIVE / PAIR PROGRAMMING):
      #   Aider launches in your terminal at the `architect>` prompt.
      #   The plan file is loaded as READ-ONLY context but NOT auto-executed.
      #   You drive the conversation from the prompt.
      #
      #   Useful Aider commands during a pair programming session:
      #     /test                  Run the `test_cmd` hooked up by the pipeline and feed
      #                            errors back into the chat.
      #     /run <shell command>   Run any shell command; output is added to chat context.
      #                            Example: /run pytest tests/test_module.py -v
      #     /add <file>            Promote a file from read-only to editable mid-session.
      #     /drop <file>           Remove a file from the current context.
      #     /files                 List all files currently loaded and their edit status.
      #     /undo                  Undo the last set of file changes Aider made.
      #     /exit                  End the session and return cleanly to the pipeline.
      #
      #   Knowledge Oracle (from the Aider prompt):
      #     /run .aider_factory/bash/oracle "question"      Ask the oracle a question.
      #     /run .aider_factory/bash/oracle --debate "q"     Start a multi-turn debate.
      #     /run .aider_factory/bash/oracle --type code "q"  Filter RAG to code tables only.
      #     /run .aider_factory/bash/oracle --type docs "q"  Filter RAG to doc tables only.
      #     /run .aider_factory/bash/oracle --clear          Reset all oracle sessions.
      #
      # Notes:
      #   - Forces max_outer_loops = 1 (no auto-retry after /exit).
      #   - Requires a real interactive terminal (TTY). Will not work in CI/CD pipelines.
      #   - Interrupting Aider mid-generation (Ctrl+C) is caught safely and will drop you
      #     back into the chat prompt without breaking the orchestrator loop.
      #   - Prepare your plan template beforehand for best results — it gives you a
      #     rich starting context even though it is not auto-executed.
      #
      #   COST REPORTING: In pair programming mode, Aider runs inside a `script`
      #   PTY wrapper that captures all terminal output (including /run oracle
      #   debate costs) to a file. This output flows through the factory launcher's
      #   tee pipeline to the log file, so aggregate_costs.py captures every cost
      #   source: main Aider session, /run debates, and oracle turns. No special
      #   configuration needed — works automatically when launched via factory.

      run_ocr_rag: false
      # ^ Trigger document ingestion via rag_manager.py before this phase's tasks.
      # true  = Convert PDFs/images in `vector_store.collection_name` to Markdown
      #         via the OCR Agent, chunk, and embed them into LanceDB.
      # false = Skip ingestion.

      vectordb_overwrite: false
      # ^ Overrides global rag.overwrite.
      # false = If LanceDB table exists, cache hit (skips OCR process entirely).
      # true  = Drop LanceDB table and re-ingest all documents.

      sticky_context: true
      # ^ Carries each completed target file forward as read-only context to
      # LATER phases. This is the ONLY place sticky_context is read (it is not a
      # top-level key).
      # true  = later phases see what earlier phases changed (prevents undoing
      #         prior work; also how a Phase-0 Oracle-built design doc flows into
      #         implementation phases). Recommended for multi-phase refactors.
      # false = each phase starts fresh with only its own declared context files.

    # -------------------------------------------------------------------------
    # ORACLE_TOGGLES — Evidence validation (fact-checking) for Oracle output.
    # -------------------------------------------------------------------------
    # The Oracle can produce documents (e.g. a literature review) that quote a
    # source. These toggles AUDIT those quotes against the original OCR text so the
    # output is provably grounded — not hallucinated — and self-heal what isn't:
    #
    #   Quote grounding (deterministic) — is each tagged quote an EXACT normalized
    #                      substring of the OCR source? If yes -> relabel [validated].
    #   Region check (semantic) — for a FAILING quote, embed the surrounding REVIEW
    #                      passage and compare it to the paper's LanceDB table to flag
    #                      regions whose claims may be hallucinated; the closest source
    #                      chunks are handed to the Oracle, the architect heals the
    #                      quote AND claim -> relabel [fixed]. Loops with a no-progress
    #                      guard so it never spins on the unfixable.
    #
    # Anchors carry their state as a tag: [evidence] (unverified) -> [validated]
    # (proven verbatim) | [fixed] (healed). No automated step ever deletes a quote.
    # Leave this whole block out to disable validation entirely.
    oracle_toggles:
      post_validate: true
      # ^ Turn on the self-healing evidence loop (runs after an `oracle` programmatic job
      # review job). Each attempt RE-VALIDATES the review:
      #   - QUOTE grounding (deterministic, provable, no model): every quote that
      #     is an EXACT normalized substring of the OCR source is relabeled
      #     [evidence] -> [validated] in place;
      #   - failing quotes (tripwires) get a semantic REGION score (the review
      #     passage around them, embedded vs the paper's LanceDB table) plus the
      #     closest source chunks, written to <review_dir>/validations/<stem>.context.md;
      #   - the Oracle judges each failure against its chunks and the architect HEALS
      #     the quote AND any hallucinated surrounding claim, relabeling it [fixed].
      # No automated step ever deletes a quote or writes "Not specified in paper.";
      # anything left as [evidence] after the loop is for human review. Requires
      # files.test_files to point at the heal script (see "Validation scripts").

      validation_tag: "evidence"
      # ^ The authored anchor the auditor promotes. Default "evidence" matches
      # [evidence] "..."; the promoted states [validated]/[fixed] are fixed words.
      # Change it to reuse the system for other tags (e.g. "citation", "source").

      region_threshold: 0.60
      # ^ Cosine similarity (0–1) below which a failing quote's surrounding REVIEW
      # passage is flagged as "may be hallucinated" in the report. ANNOTATION ONLY:
      # every tripped quote still goes to the agent; this just guides the human.

      region_margin: 2
      # ^ How many REVIEW lines above AND below the quote's paragraph/bullet to add
      # to the "claim block" that gets embedded for the region check.

      region_paragraphs: 0
      # ^ How many FULL PARAGRAPHS to expand in each direction beyond the quote's
      # own paragraph, before adding the line margin. Headings are hard stops (the
      # walk never crosses a ## boundary). Default 0 (just the quote's paragraph +
      # margin lines). Set 1-2 for wider context when claims span multiple paragraphs.

      region_top_k: 5
      # ^ How many source chunks to retrieve per failing quote (written into the
      # report for the Oracle to judge against / the architect to heal from).
      # (The Oracle's own heal retrieval uses the global rag.top_k, e.g. 15.)

      validation_loops: 3
      # ^ Per-phase ceiling for the heal loop (overrides loop_aider_test for THIS
      # phase only). It is a ceiling, not a fixed count: the no-progress guard stops
      # early as soon as a pass resolves nothing (saves tokens). Requires
      # toggles.iterate_test: true and toggles.auto_test: false.

      redo_oracle_job: true
      # ^ Only relevant when this phase has an `oracle:` block. true (default)
      # = regenerate the review every run. false = REUSE the existing review file
      # if present (skip the Oracle model call) — perfect for iterating on the heal
      # loop without paying to regenerate the document each time.

      debate_loops: 0
      # ^ The single on/off + budget knob for the escalation debate. There is NO
      # separate `deliberate:` block anymore — setting debate_loops turns on the
      # resolve/escalate chain for whichever MODE the phase is in (review or code):
      #   unset / 0  (DEFAULT) = debate OFF.
      #                  - review: the deterministic auto-fix still runs; any quote it
      #                    cannot stitch is left as [evidence] for a human.
      #                  - code: the normal iterate_test loop runs; on exhaustion the
      #                    task just fails (no debate).
      #   N  (e.g. 4)  = the number of TURNS in one debate (Architect<->Oracle
      #                  exchanges); the referee stops early on agreement/deadlock.
      #                  When the verify step leaves a residual, a refereed debate
      #                  proposes a fix; if they AGREE, an apply step makes the edit.
      #                  A deadlock/exhausted debate is held for a human.
      # Philosophy: deterministic-first. Spend agent budget ONLY on what code cannot
      # do — the auto-fix / test loop clears the bulk; the debate sees only the
      # genuine judgment calls.

      debate_rounds: 1
      # ^ How many full escalation CYCLES run. Each round is one complete debate
      # (up to debate_loops turns) -> apply -> re-verify. 1 (default) = a single
      # debate->apply cycle. Values >1 enable multi-round reflexion: if the first
      # round's verdict is not "agreed," a second round starts with fresh or
      # accumulated context (controlled by pass_round_history below). Early exit
      # on "agreed" — no wasted rounds after consensus. Distinct from debate_loops
      # (turns WITHIN one debate).
      #
      # Round-suffixed artifacts: when debate_rounds > 1, each round produces its
      # own verdict file (e.g. <stem>.job2_verdict_r1.md, <stem>.job2_verdict_r2.md).
      # When debate_rounds == 1, no suffix is added (backward-compatible).
      #
      # Pre-job debates (architect_oracle_chat: true) also respect debate_rounds:
      # each round gets a suffixed task ID (_r1, _r2), and rounds chain via
      # depends_on in the DAG. The last round's verdict feeds the downstream job.

      pass_round_history: false
      # ^ Controls whether debate context persists across escalation rounds
      # (only meaningful when debate_rounds > 1).
      #   false (DEFAULT) = each round starts with a clean slate (fresh architect
      #                     Aider history + fresh oracle session). Independent
      #                     judgments per round; no cross-round drift.
      #   true             = persist context across rounds. The architect's Aider
      #                     debate history (.debate_aider_history.md) and the
      #                     oracle's debate session (.oracle_debate_session.json)
      #                     carry forward from round to round. Round 2's architect
      #                     sees Round 1's full conversation; the oracle session
      #                     preserves its retrieval context and judgments.
      # KV cache benefit: with true, Round 2 reuses the llama.cpp server's cached
      # token prefix from Round 1 (the saved session is byte-for-byte identical to
      # what was sent), so only the delta tokens are processed. With false, each
      # round pays the full prompt processing cost.
      #
      # The debate uses SEPARATE session files from the main pipeline:
      #   .oracle_debate_session.json  (not .oracle_session.json)
      #   .debate_aider_history.md     (not .aider.chat.history.md)
      # This isolation ensures the apply phase's cleanup (which wipes the main
      # session files between tasks) never destroys cross-round debate context.
      #
      # CLI debate session management (pair programming mode):
      #   When you run `/run oracle --debate` from the Aider prompt, the Oracle
      #   reads the active phase's files and pass_round_history from the YAML.
      #   Sessions are gated by a files_hash (SHA256 of the sorted file list):
      #     - Same files + new question = continuation (follow-up in existing context)
      #     - Different files = fresh start (old session auto-cleared)
      #     - `oracle --clear` = always fresh start
      #   After turn 0 sends the full file context, subsequent rounds reuse it
      #   from the session (only the new question is sent). This prevents context
      #   duplication and preserves the KV cache across rounds.

      # NOTE: the legacy toggles validate_evidence, validate_only, fail_threshold,
      # rescue_threshold, and context_lines have been REMOVED. The `deliberate:`
      # block is also gone — the resolve chain is driven by debate_loops (above)
      # plus oracle.start_job (mode). Older configs that still contain these
      # keys are simply ignored.
      #
      # Debate observability:
      #   - Oracle chunk count is surfaced in the terminal on every oracle turn:
      #     "[oracle] N source chunk(s) . mode=top_k . model=..."
      #   - Source files are included on EVERY oracle turn (not just turn 0).
      #     RAG chunks are retrieved on Turn 0 (using the initial question) and on EVERY subsequent turn (using the Architect's proposal as the query). This ensures the Oracle always has fresh, targeted chunks to validate the Architect's exact implementation details/claims.
      #     Subsequent CLI debate invocations also run vector search unconditionally for follow-up questions.
      #   - Debate transcript: .aider_factory/logs/debates/<stem>.debate.md (permanent)
      #   - Machine ledger: .aider_factory/logs/debates/<stem>.debate.json (permanent)
      #   - Oracle RAG transcript (with retrieved LanceDB chunks in <details> tags):
      #     archived to .aider_factory/logs/oracle_history/ after each debate.
      #   - Oracle prompts are written to temp files (not CLI args) to avoid E2BIG
      #     errors on large codebases. The temp file is cleaned up after each turn.
      #   - Architect reasoning/thinking blocks are automatically stripped from
      #     captured output before passing to the oracle (saves tokens and keeps
      #     the debate transcript clean). The live stream still shows them on-screen.
      #   - PYTHONHASHSEED=0 is set on every architect debate turn for deterministic
      #     Python set iteration, ensuring the exact prompt prefix is preserved for
      #     perfect KV cache hits across turns.
      #   - Debate architect turns override max-chat-history-tokens to 1,000,000
      #     (effectively unlimited) to prevent Aider from truncating/summarizing
      #     the debate history mid-debate.
      #   - Debate session files (separate from main pipeline sessions):
      #       .oracle_debate_session.json  — oracle multi-turn history for debates
      #       .debate_aider_history.md     — architect Aider history for debates
      #     These are conditionally cleared based on round_idx + pass_round_history.
      # See "Artifact & Log Directory Map" in the Factory Service Manual for
      # the complete output directory map of all pipeline artifacts.

    # -------------------------------------------------------------------------
    # ORACLE_AUTO (optional) — the phase's Oracle "startup" job / mode selector.
    # There is NO `deliberate:` block. One skeleton runs every phase:
    #     produce -> verify (iterate-test loop) -> escalate (debate -> apply) -> finalize
    # and a "mode" just chooses what fills each slot. The mode discriminator:
    #
    #   CODE mode activates when ANY of:
    #     - run_job_one: true OR run_job_two: true
    #     - oracle block present AND start_job: false
    #     - iterate_test: true with NO grounding signal (bare test loop)
    #
    #   REVIEW / grounding mode activates otherwise (when a "grounding signal" exists):
    #     - oracle block present AND start_job: true (generates a review)
    #     - post_validate: true (heal loop enabled)
    #     - debate_loops is set (resolve evidence chain)
    #
    #   The escalation debate (debate -> apply) only fires when BOTH:
    #     debate_loops > 0 AND iterate_test: true (for code mode)
    #
    # Code mode NEVER runs the generate step, so oracle can never overwrite a
    # source file.
    # -------------------------------------------------------------------------
    oracle:
      job_debate_template: ".aider_factory/markdown/templates/job_debate.md"
      # ^ When architect_oracle_chat: true, this template seeds the pre-edit debate
      #   between the Architect and the Oracle during run_job_one and run_job_two
      #   before code is written.

      template: ".aider_factory/markdown/templates/literary_review_template.md"
      # ^ When start_job: true  (REVIEW mode) — the template the Oracle fills from
      #   the paper's LanceDB table to GENERATE the review (written to the target file).
      #   When start_job: false (CODE mode)   — no generation happens; this template
      #   becomes the debate's Architect "debugger" instructions instead (a general,
      #   language-agnostic prompt, e.g. analyze_bugs.md). Path is relative to
      #   working_directory (i.e. include the ".aider_factory/" prefix).

      start_job: true
      # ^ true (default when oracle is present) = REVIEW mode: run the generate
      #   node (produce = generate + autofix). false = CODE mode: skip generation;
      #   the template above feeds the debate. Keep start_job: false for code runs.

      full_document: true
      # ^ REVIEW mode only: true = the generator sees the WHOLE paper (its own
      #   batch:false table); false = top_k retrieval. Ignored in code mode.

      architect_oracle_chat: false
      # ^ true = CODE mode only: Enables the pre-edit debate in run_job_one and
      #   run_job_two before writing code. Drafts a plan without running tests.
      #
      #   The debate uses oracle.job_debate_template to seed the conversation
      #   (set to [] to skip the template and use the plan directly as the issue).
      #   Multi-round pre-edit debates are supported via oracle_toggles.debate_rounds.
      #   The debate verdict becomes the message_file for the downstream job,
      #   replacing the original plan template (so the architect implements
      #   the agreed resolution instead of the raw plan).
      #
      #   draft_mode: verdicts from pre-edit debates are always actionable (no gate
      #   required) since there is no test suite to verify against at this stage.
      #
      #   In pair programming mode, architect_oracle_chat is ignored (the interactive
      #   session takes priority). Trigger debates manually via:
      #     /run .aider_factory/bash/oracle --debate [code|review] [--loops N] [--rounds N] "question"
      #   Sessions persist for the same target files (files_hash-gated).
      #   Use `oracle --clear` to explicitly reset.

    # -------------------------------------------------------------------------
    # HOW THE RESOLVE CHAIN IS BUILT (no separate block — driven by toggles)
    #
    #   REVIEW mode:  generate -> autofix -> heal -> [debate -> apply] -> finalize
    #     generate  <- oracle present + start_job: true
    #     autofix   <- oracle_toggles.debate_loops set (>=0)   (deterministic, no model)
    #     heal      <- oracle_toggles.post_validate: true
    #     debate/apply/finalize <- oracle_toggles.debate_loops > 0
    #
    #   CODE mode:    job_one -> job_two/iterate_test -> [debate -> apply -> final-check]
    #     job_one/job_two/iterate_test <- toggles.run_job_one/run_job_two/iterate_test
    #     debate/apply <- oracle_toggles.debate_loops > 0
    #     (the test suite exit code is the gate; region_*/validation_tag are ignored;
    #      after apply, a deterministic final test-run reports honest pass/fail)
    #
    #   AUTHORITY MECHANISMS (how each mode knows the final result):
    #     CODE mode uses `final_check`: after the iterate loop exhausts, re-runs
    #       test_cmd ONCE with no agent — the loop never re-tests its own final
    #       edit (verification happens at the START of the next attempt), so this
    #       extra run reports the true pass/fail of the last edit.
    #     REVIEW mode uses `soft_fail` + `finalize`: the apply loop treats
    #       exhaustion as success (soft_fail=true) and defers to the downstream
    #       finalize step, which has the authority to promote [validated]/[fixed]
    #       and flag [unsupported].
    #     CODE with escalation uses BOTH: the verify node has final_check=true
    #       AND soft_fail=true. If the final test passes -> SUCCESS. If it fails
    #       -> soft SUCCESS (defers to the escalation debate/apply chain).
    #
    # Debate templates default to code-defaults and can be overridden in plans:
    #   plans.deliberate_plan  (review debate; default deliberation_evidence_template.md)
    #   plans.apply_plan       (review apply;  default apply_evidence_template.md)
    #   plans.analyze_bugs_plan(code debate;   default analyze_bugs.md — or set it via
    #                           oracle.template with start_job: false)
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # MODELS — Assign AI models to each role in this phase.
    # Mix providers freely: local Ollama, remote APIs, Gemini, GitHub Copilot.
    #
    # MODEL PREFIX ROUTING:
    #   "openai/model-name"         -> Uses architect_api_base endpoint
    #                                  Set OPENAI_API_KEY in environment (or uses sk-dummy)
    #   "ollama/model-name"         -> Uses editor_ollama_api endpoint (local Ollama)
    #   "lm_studio/model-name"      -> Uses editor_ollama_api endpoint (maps to LM_STUDIO_API_BASE)
    #   "gemini/model-name"         -> Bypasses endpoints, uses GEMINI_API_KEY env var
    #   "github_copilot/model-name" -> Handled natively by Aider via Copilot auth
    # -------------------------------------------------------------------------
    models:
      architect_agent: "openai/my-reasoning-model:latest"
      # ^ Planning and reasoning model. Responsibilities:
      #   - Reads your markdown plan template
      #   - Analyzes all context files and the target file
      #   - Writes detailed, scoped implementation instructions for the editor
      #   - Reviews test failure logs and diagnoses root causes
      #   - Does NOT directly edit files
      #
      # Recommendation: Use your highest-capability model here. It runs once
      # per outer attempt, so even expensive models are cost-manageable.
      # Strong reasoning ability matters more than raw speed for this role.

      editor_agent: "ollama/my-fast-coder:latest"
      # ^ Code-editing model for job_one (implementation tasks). Responsibilities:
      #   - Receives the architect's scoped instructions
      #   - Applies precise search/replace edits to target_files
      #   - Uses editor-diff format for minimal, targeted changes
      #
      # Recommendation: Use a fast, code-specialized model. Speed and cost
      # matter here more than reasoning depth — the architect already did the thinking.

      editor_agent_test: "ollama/my-fast-coder:latest"
      # ^ Code-editing model for job_two and iterate_test (testing tasks).
      # Can be identical to editor_agent or a different model specialized
      # for test writing vs. implementation.
      #
      # Tip: Some models write better tests than code and vice versa.
      # Using different models per job lets you optimize for each task type.

      editor_agent_test_fallback: "openai/my-smarter-model:latest"
      # ^ ESCALATION model. Automatically used on attempt > 0 during iterate_test.
      #
      # Attempt 1:      editor_agent_test is used (cheap/fast)
      # Attempts 2+:    editor_agent_test_fallback is used (smarter/slower)
      #
      # This implements a "try cheap first, escalate on failure" strategy:
      #   - Round 1: fast model tries the easy fix
      #   - Round 2+: more capable model handles what the fast model missed
      #
      # Set equal to editor_agent_test to disable escalation entirely.

      rag_agent: "openai/qwen3.6-27b-90k:latest"
      # ^ The model answering queries for the Knowledge Oracle side-agent when you
      # execute `/run .aider_factory/bash/oracle "<query>"`.
      # Defaults to the architect model if unset.

      ocr_agent: "glm-ocr-f16:latest"
      # ^ The dedicated vision model used strictly by rag_manager.py to rasterize
      # and extract text from PDFs/images during ingestion. Should be a bare name
      # or alias matching the preset on your `ocr_api_base` server.

    # -------------------------------------------------------------------------
    # FILES — Define which files the agent can edit and which are read-only.
    # All paths are relative to `working_directory`.
    # -------------------------------------------------------------------------

    ocr_prompt: "Extract the text, tables, and mathematical formulas from this page into clean Markdown. Preserve all structural integrity."
    # ^ Phase-specific override for the Vision OCR system prompt.

    files:
      target_files:
        - "src/my_module.py"
        - "src/another_module.py"
      # ^ REQUIRED. The QUEUE of primary files this phase will process.
      #
      # AUTONOMOUS MODE: The pipeline processes this list sequentially. It creates a
      # completely separate Aider session for the first file, runs it through job1,
      # job2, and iterate_test, closes Aider, and then starts a NEW session for the
      # second file.
      #
      # PAIR PROGRAMMING MODE: Because `target_files` acts as a queue, Aider will
      # launch an interactive session for the first file. When you type /exit, it
      # will immediately launch a second session for the next file.
      # -> If you want multiple files loaded into a SINGLE pair-programming session,
      #    put ONE "anchor" file here, and put the rest in `extra_editable_files`.
      #
      # GLOB EXPANSION: All lists under `files:` support wildcard expansion (e.g.
      # `*.md`, `R/**/*.R`). Wildcards are expanded and alphabetically sorted.
      # With `batch: false`, the pipeline auto-creates a per-document output `.md`
      # for each source doc in the collection before expanding `target_files`, so a
      # fresh collection resolves cleanly.

      extra_editable_files:
        - "src/shared_helpers.py"
      # ^ The CLUSTER of additional editable files loaded alongside the target file.
      #
      # These files are loaded as EDITABLE in every single session spawned by the
      # target_files queue above.
      #
      # PAIR PROGRAMMING TRICK: To start a single interactive session with 4 editable
      # files, put 1 file in `target_files` and the other 3 in `extra_editable_files`.
      #
      # Leave blank if none are needed (pipeline handles null safely):
      #   extra_editable_files:

      test_files:
        - "tests/test_*.py"
      # ^ Test files mapped to each target file. INDEX-MATCHED to target_files.
      #
      # GLOB ALIGNMENT: Because all globs are sorted alphabetically, you can rely on
      # alphabetical symmetry. If `target_files` expands to `["a.py", "b.py"]`, and
      # `test_files` expands to `["test_a.py", "test_b.py"]`, they index-match perfectly.
      # BROADCAST: If the list contains exactly 1 item (e.g. a single global test script),
      # it is broadcast and applied to ALL target files universally.
      #
      # Used when run_job_two: true (writing) or iterate_test: true (fixing).
      # Loaded as EDITABLE so the editor can create or update them.
      #
      # If omitted, paths are auto-generated using the `test_naming_and_path`
      # convention from the top of the file (default tests/testthat/test-{stem}.R).
      #
      # VALIDATION SCRIPTS: for a REVIEW heal phase (post_validate: true), test_files[0]
      # points at the heal script instead of a unit-test file, e.g.
      #   - ".aider_factory/tests/validations/validations_context_check.sh"  (review heal gate)
      # In that case the script is used as the test command only — it is NOT loaded
      # as an editable file (only the target document is editable). In CODE mode,
      # test_files are the real unit-test files (one per target, index-matched).

      context_files_job:
        - "src/interfaces.py"
        - "docs/architecture.md"
        - ".aider_factory/gitDiffs/recent_changes.diff"
      # ^ Read-only context files for job_one (implementation).
      # The agent reads these to understand the codebase but CANNOT edit them.
      #
      # Good candidates:
      #   - Interface/contract files the target must conform to
      #   - Related modules the target file calls or is called by
      #   - Git diff files showing what recently changed and why
      #   - Architecture docs, design specs, or API references
      #   - Any file the architect needs to plan the implementation correctly
      #
      # Note: CONVENTIONS.md (.aider_factory/CONVENTIONS.md) is ALWAYS
      # appended automatically. You do not need to list it here.
      #
      # Leave blank if no extra context needed (pipeline handles null safely):
      #   context_files_job:

      context_files_test:
        - "src/interfaces.py"
        - "tests/conftest.py"
      # ^ Read-only context files for job_two and iterate_test (testing).
      # Kept separate from context_files_job so test sessions can have
      # different context than implementation sessions.
      #
      # Good candidates:
      #   - Test fixtures, conftest files, test helpers
      #   - Mock data or fixture files
      #   - The actual source files under test (for understanding the API)
      #   - Spec documents defining expected test behavior
      #
      # Note: CONVENTIONS.md is always appended automatically here too.
      # Leave blank if no extra context needed (pipeline handles null safely):
      #   context_files_test:

    # -------------------------------------------------------------------------
    # PLANS — Markdown templates that serve as the initial instructions to the
    # architect model. These are the "prompt programs" for each job type.
    # Paths are relative to the .aider_factory/ directory.
    # -------------------------------------------------------------------------
    plans:
      job_one_plan: "markdown/templates/implement.md"
      # ^ Markdown template for job_one (implementation/validation).
      # Resolves to: .aider_factory/markdown/templates/implement.md
      #
      # In AUTONOMOUS mode: loaded as context AND sent as the initial message:
      #   "Please execute the instructions found in [this file]."
      # In PAIR PROGRAMMING mode: loaded as read-only context only.
      #   You reference it in your conversation manually.
      #
      # Template writing tips:
      #   - Write instructions in the architect's voice (to an AI planner)
      #   - Define scope, constraints, and expected output format explicitly
      #   - Reference your codebase's conventions and patterns
      #   - The more precise the template, the more focused the output
      #   - Keep one template per distinct task type; create new ones freely

      job_two_plan: "markdown/templates/testing.md"
      # ^ Markdown template for job_two (test writing).
      # Used only when run_job_two: true. In iterate_test-only mode (run_job_two: false),
      # this is ignored and the pipeline injects live test failure output instead.

      deliberate_plan: "markdown/internal/deliberation_evidence_template.md"
      # ^ (optional, REVIEW mode) The Architect's role instructions for the evidence
      # debate (un-splice / correct a misstated claim / declare UNSUPPORTED). Defaults
      # to the value shown. .aider_factory-relative path.

      apply_plan: "markdown/internal/apply_evidence_template.md"
      # ^ (optional, REVIEW mode) The apply editor's rules: insert ONLY the Oracle's
      # verbatim text, never change tags. Defaults to the value shown.

      analyze_bugs_plan: "markdown/internal/analyze_bugs.md"
      # ^ (optional, CODE mode) The Architect's debugging-debate instructions
      # (diagnose the failing test, propose the minimal fix grounded in the retrieved
      # corpus). Defaults to the value shown; oracle.template (start_job: false)
      # overrides it.

      iterate_plan: "markdown/templates/testing_helpers.md"
      # ^ Optional plan used when iterate_test: true (this includes validation
      # phases). The test/validation output is captured and fed to the architect;
      # iterate_plan's contents are appended as the constraint/instruction block
      # below that output. If omitted, the orchestrator uses a hardcoded default.
      # For a REVIEW heal phase, point this at the contextual fix template:
      #   iterate_plan: "markdown/internal/contextual_revalidation_template.md"

      # Suggested templates to maintain:
      #   markdown/templates/implement.md             — feature implementation
      #   markdown/templates/validate.md              — code review and validation
      #   markdown/templates/testing.md               — unit test writing
      #   markdown/templates/integrate_testing.md     — integration test writing
      #   markdown/templates/testing_unit_iterate.md  — constraints for test fixing loops
      #   markdown/templates/literary_review_template.md       — Oracle auto literature review
      #   markdown/internal/contextual_revalidation_template.md — evidence heal plan (self-healing loop)
      #   markdown/internal/deliberation_evidence_template.md   — debate architect instructions (review)
      #   markdown/internal/analyze_bugs.md                     — debate architect instructions (code)
      #   markdown/internal/apply_evidence_template.md          — apply editor rules (review)
      #   markdown/debug_<issue>.md                            — custom debug session (any name)
      #
      # PATH RESOLUTION:
      #   plans: paths are relative to .aider_factory/ (omit the .aider_factory/ prefix)
      #   oracle: paths are relative to working_directory (include .aider_factory/ prefix)
      #
      # For the complete template directory map, authoring guide, and debate setup
      # instructions, see "Interaction Templates" in the Factory Service Manual.
      #
      # TEMPLATE TIERS:
      #   markdown/templates/       User-customizable. Create, edit, swap freely.
      #   markdown/internal/        Infrastructure. Contains pipeline-parsed formats
      #                             (PROPOSAL/VERDICT lines, [evidence] tag rules).
      #                             Editing these can break debate parsing or
      #                             validation gates. Override via plans.* only if
      #                             you understand the downstream contracts.
      #   markdown/oracle_pre_plan/ Strategy workflow (Phase-0 knowledge base plans).
      #                             User-customizable; loaded only when explicitly
      #                             configured via target_files.

# =============================================================================
# MODEL REFERENCE
# Paste model strings directly into the models: section above.
# =============================================================================

# --- Cloud / API Models (require API keys set as environment variables) ---
# gemini/gemini-3.1-pro-preview           High capability, long context (GEMINI_API_KEY)
# gemini/gemini-3.5-flash                 Fast iteration and test edits (GEMINI_API_KEY)
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
```
