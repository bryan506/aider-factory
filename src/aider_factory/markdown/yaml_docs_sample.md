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
# 1. DISPLAY & RETRY CONTROLS
# -----------------------------------------------------------------------------

colors:
  architect_debate: "#38bdf8" # sky blue — architect turns in debates
  oracle_debate: "#d3869b" # gruvbox pink — oracle turns + single query output

test_command_prefix: ""
# ^ Optional wrapper command prefix (e.g. "docker exec -i my-container")

test_runner: "echo 'No tests configured for this session'"
# ^ The core test execution command template. Substitutes {file} dynamically.

test_naming_and_path: "tests/test_{stem}.py"
# ^ Auto-generation convention for test file paths when omitted from files.test_files.

loop_aider_test: 1
# ^ Number of outer retry loops when iterate_test is enabled.

# -----------------------------------------------------------------------------
# 2. GLOBAL MODELS (Unified: All model strings live here)
# -----------------------------------------------------------------------------
models:
  architect_agent: "gemini/gemini-3.5-flash"
  editor_agent: "gemini/gemini-2.5-flash"
  editor_agent_test: "gemini/gemini-2.5-flash"
  editor_agent_test_fallback: "gemini/gemini-2.5-flash"
  rag_agent: "gemini/gemini-3.5-flash"
  ocr_agent: "glm-ocr-f16:latest"
  embed_model: "qwen3-embedding-8b-8k:LATEST"
  grounding_agent: "openai/minicheck-flan-t5-large"

# -----------------------------------------------------------------------------
# 3. GLOBAL API ENDPOINTS (Unified: All network addresses live here)
# -----------------------------------------------------------------------------
endpoints:
  architect_api_base: "http://localhost:11434/v1"
  editor_ollama_api: "http://localhost:11434"
  editor_test_ollama_api: "http://localhost:11434"
  rag_agent_api: "http://localhost:11434/v1"
  grounding_agent_api: "http://localhost:8090/v1"
  ocr_api_base: "http://192.168.100.2:8081/v1"
  embed_api_base: "http://192.168.100.2:8080/v1"

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
  - name: "Reconcile Aider Configurations"
    enabled: true

    # -------------------------------------------------------------------------
    # RAG — Phase-level RAG overrides
    # -------------------------------------------------------------------------
    rag:
      collection_name: "" # Empty to bypass RAG database queries
      batch: true # true = shared table, false = isolated table per document
      retrieval_mode: top_k # top_k | no_retrieve | full_document
      run_ocr_rag: false # true = ingest documents before phase starts
      vectordb_overwrite: false # true = drop and rebuild the LanceDB table
      ocr_prompt: "Extract text, tables, math, code, and documentation into clean Markdown."
      query_prefix: "Query: " # prefix for semantic search
      chunk_size_chars: 800
      chunk_overlap_chars: 100
      top_k: 5
      cer_threshold: 0.05
      ocr_max_retries: 2
      ocr_parallel: 1
      ocr_max_tokens: 4096
      code_chunk_size: 2000
      working_repo: ""
      code_exts: null
      text_doc_exts: null
      ignore: null

    # -------------------------------------------------------------------------
    # ORACLE — Programmatic side-agent and pre-edit debate configuration
    # -------------------------------------------------------------------------
    oracle:
      start_job: false # true = REVIEW mode (generate review), false = CODE mode
      template: "src/aider_factory/markdown/templates/literary_review_template.md"
      full_document: false # true = whole document context, false = top_k chunks
      pre_edit_debate:
        enabled: false # true = debate plans before implementing
        job_debate_template: []

    # -------------------------------------------------------------------------
    # TOGGLES — Fine-grained control over what this phase does.
    # -------------------------------------------------------------------------
    toggles:
      pair_programming: true # true = interactive session, false = autonomous
      run_job_one: true # true = run primary implementation job
      run_job_two: false # true = run test-writing job
      iterate_test: false # true = run iterative test-fixing loop
      auto_test: false # true = Aider-driven retries, false = Architect-driven
      sticky_context: true # true = carry completed files forward as read-only context

    # -------------------------------------------------------------------------
    # VALIDATION — Evidence validation (fact-checking) for Oracle output.
    # -------------------------------------------------------------------------
    validation:
      enabled: false # true = enable the self-healing evidence loop
      validation_tag: "evidence" # quote tag to audit (default: evidence)
      region_threshold: 0.60 # cosine similarity below which review passage is flagged
      region_margin: 2 # review lines above/below quote paragraph added to claim block
      region_paragraphs: 0 # full paragraphs expanded beyond the quote's own paragraph
      region_top_k: 5 # source chunks retrieved per failing quote
      validation_loops: 3 # per-phase ceiling for the heal loop
      redo_oracle_job: false # true = regenerate review every run, false = reuse existing
      verify_all_claims: false # true = score every claim, false = candidate claims only
      entail_threshold: 0.5 # calibrated support prob below which claim is flagged

    # -------------------------------------------------------------------------
    # ESCALATION DEBATE — Two-party deliberation loops
    # -------------------------------------------------------------------------
    escalation_debate:
      loops: 0 # turns per debate (0 = debate off, N = turns)
      rounds: 1 # debate-apply-verify cycles
      pass_history: false # true = persist debate context across rounds

    # -------------------------------------------------------------------------
    # FILES — Define which files the agent can edit and which are read-only.
    # All paths are relative to `working_directory`.
    # -------------------------------------------------------------------------
    files:
      target_files:
        - "src/aider_factory/default_configs/.env_ocr_rag.yml"
      extra_editable_files: []
      test_files: []
      context_files_job:
        - "src/aider_factory/default_configs/default_yaml_config/*.yml"
        - "src/aider_factory/markdown/factory_service_manual.md"
        - "src/aider_factory/markdown/yaml_docs_sample.md"
        - "src/aider_factory/python/*.py"
      context_files_test: []

    # -------------------------------------------------------------------------
    # PLANS — Markdown templates that serve as the initial instructions to the
    # architect model. These are the "prompt programs" for each job type.
    # Paths are relative to the .aider_factory/ directory.
    # -------------------------------------------------------------------------
    plans:
      job_one_plan: "markdown/templates/implement.md"
      # ^ Prompt template for primary implementation (job_one)
      job_two_plan: "markdown/templates/testing.md"
      # ^ Prompt template for test writing (job_two)
      deliberate_plan: "markdown/internal/deliberation_evidence_template.md"
      # ^ (REVIEW mode) Architect instructions for evidence debate
      apply_plan: "markdown/internal/apply_evidence_template.md"
      # ^ (REVIEW mode) Apply editor's rules for inserting Oracle text
      analyze_bugs_plan: "markdown/internal/analyze_bugs.md"
      # ^ (CODE mode) Architect debugging-debate instructions
      iterate_plan: "markdown/templates/testing_helpers.md"
      # ^ Constraints appended to test-fixing loops (iterate_test)

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
