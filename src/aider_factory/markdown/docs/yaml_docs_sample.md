# AI Factory Pipeline — Technical Specification & Configuration Reference

> **Authoritative Single Source of Truth** for the AI Factory Directed Acyclic Graph (DAG) Pipeline.
> Every runtime configuration key, execution lifecycle, mathematical invariant, CLI interface, and diagnostic workflow is documented with 100% codebase fidelity against `run_workflow.py`, `orchestrate.py`, `rag_manager.py`, `validator.py`, `deliberate.py`, `apply_agent.py`, and `oracle_agent.py`.

---

## 1. Executive Overview & Foundational Invariants

The AI Factory Pipeline orchestrates multi-phase, multi-model Directed Acyclic Graphs (DAGs) for autonomous software engineering, formal verification, and evidence-grounded document authoring. It coordinates specialized LLM personas (Architect, Editor, Oracle, Validator, and Reranker) through deterministic state machines, process-tree sandboxes, and immutable context ledgers.

The pipeline execution graph is compiled from a declarative YAML schema (`.env.yml`). Each declared `phase` produces a deterministic sequence of tasks mapped across target files, with dependency barriers ensuring that downstream validation or testing stages execute only when upstream prerequisites have been met.

```bash
# Universal cross-platform launcher (Linux, macOS, Windows):
aider-launcher my_session .aider_factory/.env.yml

# Direct CLI orchestrator:
aider-factory my_session .aider_factory/.env.yml

# Standalone cost aggregation on archived logs:
python -m aider_factory.python.aggregate_costs .aider_factory/logs/<logfile>.log
```

### 1.1 Foundational System Invariants

1. **Deterministic-First Verification**: Do with deterministic code what code can prove; reserve LLMs strictly for genuine judgment. Grounding and verification rely on real OS exit codes (`0`), AST parsing, exact character-level substring matching, and normalized edit distances—never on model self-assessment or conversational agreement.
2. **Strict State Isolation & Zero Blast Radius**: No task, experiment, or turn may bleed state, prompt history, or scratch artifacts into adjacent execution contexts. State persistence is isolated in session-specific vaults (`.aider_factory/sessions/<session_name>/chat_history/`) using deterministic per-stem file swaps.
3. **KV-Cache & Context Efficiency**: Prompts utilize immutable byte-parity prefixes, append-only delta injection, and deterministic serialization (`PYTHONHASHSEED=0`) to maximize KV-cache reuse. Active context windows are treated as scarce, high-value surfaces capped below 70–80% active utilization.
4. **Minimal-Delta Scoping**: Edits are constrained strictly to the active target files explicitly assigned to a task. Scaffolding, configuration defaults, and passing tests remain immutable unless explicitly targeted.
5. **Truthful Documentation & Separation of Concerns**: Specifications document shipped, runtime-verified code paths with zero hallucinated features. Clear boundaries are maintained between architectural planning, surgical file editing, and test verification.

### 1.2 Multi-Persona Role Allocation

Every task in the execution graph is mediated across decoupled model roles:
- **Architect Model (`architect_agent`)**: High-reasoning model (e.g., `gemini-3.7-flash`, `o3-mini`, `deepseek-reasoner`). Inspects read-only context, diagnoses test failures, plans implementation steps, and outputs structured specifications. It operates in non-interactive ask mode (`--edit-format ask`) and never writes file edits directly to disk.
- **Editor Model (`editor_agent` / `editor_agent_test`)**: Fast, deterministic code generation model (e.g., `gemini-3.6-flash`, `qwen2.5-coder-32b`). Consumes the Architect's specification and emits unified diffs or search/replace blocks applied directly to disk.
- **Fallback Editor (`editor_agent_test_fallback`)**: High-capacity escalation model dynamically substituted on test attempt $> 0$ when an initial editor pass fails to resolve a failing test harness.
- **Knowledge Oracle (`rag_agent`)**: Grounding side-agent consulted during planning and debate turns. Queries local LanceDB vector tables, evaluates source code ASTs, and emits evidence-backed critique.
- **Evidence Validator (`grounding_agent`)**: Specialized classifier or NLI entailment server (e.g., MiniCheck Flan-T5-Large) that scores claim faithfulness against retrieved source passages.
- **Neural Reranker (`ranking_agent`)**: Cross-encoder model (e.g., `jina-reranker-v3.5`, `bge-reranker-large`) that re-scores dense vector candidates prior to LLM context injection.

### 1.3 Execution Modes

The pipeline operates in two distinct execution modes governed by phase discriminators:
- **Code Mode (`oracle.start_job: false`)**: Focuses on source code modification, test authoring, and autonomous debugging. Executes Jobs 1 through 4, pre-edit deliberation, and test-driven escalation debates. Loop exhaustion triggers `Task.final_check` to verify the final code state against the real test suite.
- **Review / Evidence Grounding Mode (`oracle.start_job: true` or `validation.enabled: true`)**: Synthesizes literature reviews, technical specifications, and audits from LanceDB vector stores. Quotes are tagged with verbatim anchors (`[evidence]`), checked via deterministic exact substring matching, repaired via ellipsis-stitching (`_autofix`), verified through semantic region checking and MiniCheck entailment, and finalized into terminal states (`[validated]`, `[fixed]`, or `[unsupported]`).

---

## 2. System Topology & Lifecycle Flowcharts

### 2.1 End-to-End Pipeline Execution Lifecycle

The pipeline lifecycle transitions through deterministic phases: environment loading, phase compilation, per-target task generation, isolated execution, and terminal cost accounting.

```text
+---------------------------------------------------------------------------------------------------+
|                                  1. INITIALIZATION & SESSION RESOLUTION                           |
|  - Resolve Session Name: CLI arg > AI_FACTORY_SESSION env > Auto-timestamp                        |
|  - Resolve Working Directory & Copy session.yml into .aider_factory/sessions/<session_name>/      |
|  - Initialize OSTee: Multiplex OS file descriptors 1 (stdout) and 2 (stderr) to terminal & log   |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                     2. PHASE COMPILATION LOOP                                     |
|  For each phase in config['phases'] where enabled == true:                                        |
|    - Resolve Models, Endpoints, and Weak Model Fallbacks                                          |
|    - Resolve Test Runner, Test Convention, and Command Prefix Hierarchies                         |
|    - Execute RAG Ingestion (rag_manager.ingest) if run_ocr_rag == true                            |
|    - Resolve Target Files (sticky_phases plan extraction or glob expansion)                       |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                3. PER-TARGET TASK PIPELINE EXECUTION                              |
|                                                                                                   |
|   CODE MODE (oracle.start_job: false)               REVIEW / GROUNDING MODE (start_job: true)     |
|   +---------------------------------------+         +-----------------------------------------+   |
|   | Optional: Pre-Edit Debate             |         | Oracle Document Synthesis               |   |
|   | (insert_debate: [j1, j2, j3])         |         | (template + LanceDB -> <stem>.md)       |   |
|   +---------------------------------------+         +-----------------------------------------+   |
|                      |                                                   |                        |
|                      v                                                   v                        |
|   +---------------------------------------+         +-----------------------------------------+   |
|   | Job 1: Implementation Pass            |         | Deterministic Autofix (_autofix)        |   |
|   | (Editor diff on target_files)         |         | (Ellipsis stitch -> [fixed])            |   |
|   +---------------------------------------+         +-----------------------------------------+   |
|                      |                                                   |                        |
|                      v                                                   v                        |
|   +---------------------------------------+         +-----------------------------------------+   |
|   | Job 2: Spec Audit / Validation        |         | Agent Grounding Heal Loop               |   |
|   | (Architect audit against spec)        |         | (Validator test runner gate)            |   |
|   +---------------------------------------+         +-----------------------------------------+   |
|                      |                                                   |                        |
|                      v                                                   v                        |
|   +---------------------------------------+         +-----------------------------------------+   |
|   | Job 3 & 4: Write Tests & Iterate      |         | Escalation Deliberation Debate          |   |
|   | (Test runner gate -> error loop)      |         | (Architect <-> Oracle deliberation)     |   |
|   +---------------------------------------+         +-----------------------------------------+   |
|                      |                                                   |                        |
|                      v                                                   v                        |
|   +---------------------------------------+         +-----------------------------------------+   |
|   | Escalation Debate & Apply Loop        |         | Verbatim Apply & Finalize               |   |
|   | (Deliberation verdict -> apply_agent) |         | (Promote [fixed] / Demote [unsupported])|   |
|   +---------------------------------------+         +-----------------------------------------+   |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                  4. TEARDOWN & FINANCIAL TELEMETRY                                |
|  - Terminate OSTee worker thread and flush buffers to disk                                        |
|  - Run aggregate_costs.py over log: Extract tokens sent, tokens received, and total USD cost      |
|  - Return Pipeline OS Exit Code: 0 on complete success, 1 on unhandled task failure               |
+---------------------------------------------------------------------------------------------------+
```

### 2.2 Deliberation Consensus State Machine (`deliberate.py`)

The deliberation referee parses structured assistant outputs, hashes architect proposals, tracks repetition, and gates downstream application.

```text
                          +-------------------------------+
                          |   Trigger Deliberation Turn   |
                          +-------------------------------+
                                          |
                                          v
                          +-------------------------------+
                          | Gate Command Check (Pre-Test) |
                          +-------------------------------+
                                     /         \
                         (Pass == True)       (Pass == False / None)
                                   /             \
                                  v               v
                        +---------------+   +-----------------------------------+
                        | State: clean  |   | Turn 0: Oracle Pre-Assessment     |
                        +---------------+   +-----------------------------------+
                                                              |
                                                              v
                                            +-----------------------------------+
                               +----------> | Turn N: Architect PROPOSAL: Line  |
                               |            +-----------------------------------+
                               |                              |
                               |                              v
                               |            +-----------------------------------+
                               |            | Turn N: Oracle VERDICT: Evaluation|
                               |            +-----------------------------------+
                               |                              |
                               |                              v
                               |            +-----------------------------------+
                               |            | consensus_state(ledger) Evaluation|
                               |            +-----------------------------------+
                               |               /              |               \
                        State: "continue"     /         State: "agreed"        \   State: "deadlock" /
                               |             /                |                 \  "exhausted"
                               +------------+                 v                  v
                                                    +-------------------+  +--------------------+
                                                    | Actionable Verdict|  | Non-Actionable     |
                                                    | (STATUS: agreed)  |  | Verdict (STATUS:   |
                                                    | (GATE: present)   |  | deadlock/exhausted)|
                                                    +-------------------+  +--------------------+
                                                              |                      |
                                                              v                      v
                                                    +-------------------+  +--------------------+
                                                    | Downstream Apply  |  | Held for Human     |
                                                    | Node Permitted    |  | Review (No Edit)   |
                                                    +-------------------+  +--------------------+
```

### 2.3 State Vault & Chat History Isolation Architecture

To ensure zero context bleeding across distinct files in multi-file phases, `orchestrate.py` implements a physical state vault.

```text
Active Stage: .aider_factory/sessions/<session_name>/
  ├── .aider.chat.history.md          <--- Active conversation context read by Aider
  ├── .aider.input.history            <--- Input line buffer
  ├── .aider.llm.history              <--- Raw prompt/completion ledger
  ├── .oracle_session.json            <--- Knowledge Oracle KV-cache messages
  └── .debate_aider_history.md        <--- Multi-turn debate history

                                  |
               _swap_out_state()  |  _swap_in_state()
               (Archive & Flush)  |  (Restore & Bind)
                                  v

Vault Directory: .aider_factory/sessions/<session_name>/chat_history/
  ├── .aider.chat.history_job1_auth_service.md
  ├── .aider.chat.history_job1_payment_gateway.md
  ├── .oracle_session_job1_auth_service.json
  ├── .oracle_session_job1_payment_gateway.json
  └── ...
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### 3.1 Mathematical Formulations

#### 3.1.1 Reciprocal Rank Fusion (RRF)
During multi-table vector retrieval (fusing code, documentation, and academic tables), candidate chunks are merged deterministically using Reciprocal Rank Fusion:

$$RRF(d) = \sum_{m \in M} \frac{1}{c + r_m(d)}$$

Where:
- $M$: The set of individual LanceDB table result sets participating in the retrieval.
- $r_m(d)$: The 0-based ordinal ranking position of chunk $d$ in result set $m$.
- $c$: A rank-smoothing constant fixed at $c = 60$.

Deduplication keys are computed from the tuple `(source_file, text[:64])`. Ties are broken deterministically by evaluating secondary sort keys:

$$\text{SortKey}(d) = \left( -RRF(d), \; \text{source\_file}(d), \; \text{text\_prefix}(d) \right)$$

#### 3.1.2 Character Error Rate (CER) Validation Gate
Document OCR quality is deterministically evaluated against native digital PDF text layers using Normalized Character Error Rate:

$$CER(\text{ref}, \text{hyp}) = \frac{\text{Levenshtein}(\text{ref}_{\text{norm}}, \text{hyp}_{\text{norm}})}{|\text{ref}_{\text{norm}}|}$$

Where $\text{ref}_{\text{norm}}$ and $\text{hyp}_{\text{norm}}$ are derived by stripping all non-alphanumeric characters:

$$\text{norm}(s) = \text{regex\_replace}(s, \text{"[^a-z0-9]"}, \text{""})$$

**Boundary Invariants**:
- If $|\text{ref}_{\text{norm}}| = 0$ (a purely scanned graphical document with no embedded text layer), $CER \equiv 0.0$ and OCR validation passes immediately.
- If $CER > 0.40$ and $|\text{ref}_{\text{norm}}| > 50$, vision OCR output is classified as degraded/hallucinatory, and the system discards the hypothesis in favor of the raw native PDF text layer.

#### 3.1.3 Semantic Vector Grounding & Metric Spaces
Passage semantic verification computes the cosine distance between the query claim embedding $\mathbf{u}$ and candidate source chunk embeddings $\mathbf{v}$:

$$\text{Sim}_{\text{cosine}}(\mathbf{u}, \mathbf{v}) = \frac{\mathbf{u} \cdot \mathbf{v}}{\|\mathbf{u}\|_2 \|\mathbf{v}\|_2} = 1 - \text{Dist}_{\text{cosine}}(\mathbf{u}, \mathbf{v})$$

**Index Optimization Threshold**:
- LanceDB tables containing $N \le 50,000$ rows execute exact flat $k$-nearest neighbors ($k$-NN).
- When table row count crosses the threshold $N > 50,000$, `rag_manager.py` automatically builds an Inverted File with Product Quantization (IVF-PQ) Approximate Nearest Neighbor (ANN) index with cosine distance metrics.

#### 3.1.4 MiniCheck Sentence-Level Claim Entailment
Claim entailment scoring evaluates natural language assertions against retrieved evidence passages $D$. The input claim $C$ is partitioned into discrete sentences $S = \{s_1, s_2, \dots, s_k\}$ using punctuation lookbehind regex, filtering fragments where $|s_i| < 8$ characters.

Each sentence is scored independently against document context $D$ via the MiniCheck classifier, which reads class probabilities directly from decoder logits. The composite claim score is governed by the conservative minimum support probability:

$$P(\text{supported} \mid D, C) = \min_{s_i \in S} P(s_i \mid D)$$

If $P(\text{supported} \mid D, C) < \tau_{\text{entail}}$ (where $\tau_{\text{entail}} = 0.50$ by default), the claim block is flagged as unsupported/hallucinated.

#### 3.1.5 Token Usage & Financial Cost Accounting
Execution logs capture token metrics emitted by LiteLLM and Aider. Total session costs are aggregated by `aggregate_costs.py` using single-pass regex extraction:

$$\text{Cost}_{\text{total}} = \sum_{t=1}^{T} \left( P_{\text{prompt}} \cdot N_{\text{prompt}}^{(t)} + P_{\text{completion}} \cdot N_{\text{completion}}^{(t)} \right)$$

Captured patterns:
```regex
Tokens:\s*(?P<sent>[0-9.,]+[kM]?)\s*sent,\s*(?P<recv>[0-9.,]+[kM]?)\s*received.*Cost:\s*\$\s*(?P<msg>[0-9.,]+)\s*message,\s*\$\s*(?P<sess>[0-9.,]+)
```
Metric suffixes are normalized: $k \times 1,000$, $M \times 1,000,000$.

### 3.2 Algorithmic Subsystems

#### 3.2.1 Pre-Edit Debate Mechanics (`oracle.pre_edit_debate`)
Configuring `pre_edit_debate.insert_debate` allows inserting an ask-mode debate before Job 1, Job 2, or Job 3:
- `_parse_insert_debate()` converts string or list inputs into a deterministic boolean 3-tuple $[d_1, d_2, d_3]$.
- When $d_3 = 1$, the pipeline launches Pre-Test Deliberation between Role 1 (Oracle Test Critic) and Role 2 (Architect Test Designer) using `testing_debate.md`. The Oracle audits edge cases, boundary conditions, and invariant rules, outputting an exhaustive `## Test Decision Matrix` before tests are authored in Job 3.
- Setting `job_debate_collection: ""` bypasses LanceDB vector retrieval entirely, causing `orchestrate.py` to inject physical repository source files directly into `<project_files>`.

#### 3.2.2 Sticky Phases & File Auto-Discovery
When `sticky_phases.editable: true` or `sticky_phases.readonly: true` is enabled and `files.target_files` is empty, `run_workflow.py` invokes `_extract_files_from_plan()`:
1. **Scope Parsing**: Scans the strategy template (`markdown/oracle_pre_plan/strategy_template.md` or `plans.job_one_plan`) for YAML code blocks under `## Scope Analysis`.
2. **Markdown Fallback**: If no YAML block is found, parses markdown lists under `### Target Files:`, `### Extra Editable Files:`, `### Test Files:`, and `### Context Files:`.
3. **Classification & Verification**: Runs `is_test_path()` on every candidate. Test files accidentally categorized under `target_files` are re-routed to `test_files`. Files that do not exist physically on disk are pruned.

#### 3.2.3 Tree-Sitter AST Chunking vs. Recursive Splitting
Code ingestion utilizes Tree-Sitter language grammars:
- Language parsers recursively traverse the concrete syntax tree. Chunks are extracted at structural node boundaries (classes, functions, methods) annotated with symbol identifiers and 1-based line ranges (`line_start`, `line_end`).
- If an individual AST node exceeds `code_chunk_size` (default: 2,000 characters), `_text_split_fallback()` divides the node at line boundaries with 3 lines of overlap. Single oversized lines are split at character boundaries with 20% overlap.
- Markdown documents use `MarkdownHeaderTextSplitter` (`#`, `##`, `###`) combined with recursive character splitting, while atomic code blocks (```` ``` ````) are preserved without mid-block division.

#### 3.2.4 Document Ingestion & Vision OCR Pipeline
1. **Docling Extraction**: Clean digital documents (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`) are converted directly to structured markdown via `docling_runner.py`.
2. **PyMuPDF Rasterization**: Scanned pages or unhandled formats are rendered to PNG images at 150 DPI into `.aider_factory/markdown/lanceDB/<collection>/images/`.
3. **Vision OCR Worker Pool**: Pages are dispatched across concurrent workers (`ocr_parallel`). Each page undergoes CER evaluation against its native text layer.
4. **Buffered Flush**: Extracted chunks are buffered in memory and committed to LanceDB in batches of `FLUSH_CHUNK_THRESHOLD = 2000` to prevent memory exhaustion.

#### 3.2.5 Two-Stage Reranking Mechanics
1. **Stage 1 (Vector Retrieval)**: Retrieves $K_1 = \text{recall\_k}$ candidates (default: 75) using cosine distance vector search across LanceDB tables.
2. **Stage 2 (Neural Rerank)**: Evaluates $K_1$ candidates using a cross-encoder model down to $K_2 = \text{top\_k}$ (default: 20).
   - *Listwise Path*: Native listwise models (`jina-reranker-v3.5`) are loaded via `transformers.AutoModel(trust_remote_code=True)` and invoked jointly via `.rerank(query, documents)`.
   - *Pairwise Path*: Classic cross-encoders (`bge-reranker-large`, `ms-marco-MiniLM-L-6-v2`) are loaded via `sentence_transformers.CrossEncoder` and scored via `.predict([[query, doc], ...])`.

#### 3.2.6 Deterministic Ellipsis-Stitch Autofix (`_autofix`)
Prior to agent execution in review mode, `validator.py` inspects ungrounded quotes containing ellipsis markers (`...`, `…`, `. . .`):
- Splice fragments are located as exact substrings in the normalized OCR source.
- If all fragments occur in sequential order and the total inter-fragment gap does not exceed $\text{MAX\_STITCH\_GAP} = 200$ characters, the quote is reconstructed into a single continuous source span and relabeled `[fixed]`.
- If the semantic similarity of the surrounding claim block falls below `region_threshold`, the stitch is declined and held for debate review.

---

## 4. Exhaustive CLI & Parameter Reference

### 4.1 CLI Tool Invocation Matrix

| Command / Utility | Source Script | Primary Operational Function | Key Parameters & Flags | Exit Codes |
| :--- | :--- | :--- | :--- | :--- |
| `aider-factory` | `run_workflow.py` | Primary multi-phase DAG pipeline orchestrator | `[session_name] [config.yml]`, `-h, --help` | `0` = Complete<br>`1` = Task failure |
| `aider-launcher` | `factory_launcher.py` | Cross-platform launcher with live terminal tee logging | `[options] [session_name] [config.yml]` | Preserves workflow exit code |
| `aider-oracle` | `oracle_agent.py` | LanceDB RAG query, debate turn, and corpus maintenance | `"<question>"`, `--file <p>`, `--debate [code\|review]`, `--collection <c>`, `--add-file <p>`, `--add-web <url>` | `0` = Success<br>`1` = Error |
| `aider-validate` | `validator.py` | Substring quote grounding, region check, and claim audit | `--file <p>`, `--source <src>`, `--report <out>`, `--claims-only`, `--autofix`, `--finalize-unsupported` | `0` = Grounded / No-progress<br>`1` = Trips remain |
| `aider-apply` | `apply_agent.py` | Headless Aider edit pass driven by spec files or history | `<files...>`, `--spec <file>`, `--turns <N>`, `--stream`, `--no-diff` | `0` = Clean edit<br>`1` = Apply error |
| `aider-research` | `research_agent.py` | SearXNG search client and XML sitemap crawler | `"<query>"`, `--academic`, `--sitemap`, `--grep "<pat>"`, `--links-only` | `0` = Success<br>`1` = Failure |
| `aider-clean-lancedb` | `clean_lancedb.py` | Cleans ephemeral images, validation, and debate logs | `<collection>`, `--project-dir <path>` | `0` = Success<br>`1` = Error |
| `minicheck_server.py` | `minicheck_server.py` | OpenAI-compatible MiniCheck NLI entailment server | FastAPI endpoint `/v1/chat/completions` on port 8090 | `0` = Clean shutdown |

---

### 4.2 Comprehensive Command-Line Flags

#### `aider-factory` (`run_workflow.py`)
```bash
# Execute session with explicit configuration
aider-factory my_session .aider_factory/.env.yml

# Execute session using default configuration discovery (.aider_factory/.env.yml)
aider-factory my_session
```
- `[session_name]`: Optional explicit session identifier (alphanumeric, dashes, underscores). If omitted, defaults to `session_YYYYMMDD_HHMMSS_ffffff`.
- `[config_file.yml]`: Optional path to YAML configuration. Defaults to `.aider_factory/.env.yml` or `.env.yml`.

#### `aider-launcher` (`factory_launcher.py`)
```bash
# Launch pipeline with stream tee logging to .aider_factory/logs/
aider-launcher my_session .aider_factory/.env.yml
```
- `-h, --help`: Displays launcher help and exits.
- `-s, --session <name>`: Explicit session identifier.

#### `aider-oracle` (`oracle_agent.py`)
```bash
# Interactive query against active collection
aider-oracle "What is the formula for capital adequacy ratio?"

# Query with file context
aider-oracle --file "docs/formula.txt" "Verify this specification"

# Multi-turn debate between Oracle and Architect
aider-oracle --debate code --loops 3 --rounds 2 "Resolve deadlock in mutex lock"

# Database Maintenance
aider-oracle --list-tables
aider-oracle --list-files
aider-oracle --add-file docs/architecture.pdf
aider-oracle --add-table research/papers/
aider-oracle --add-web https://docs.example.com/sitemap.xml --workers 4
aider-oracle --rm-file old_draft.pdf
aider-oracle --rm-table legacy_collection
aider-oracle --rm-db
aider-oracle --clear oracle
```
- `--config <path>`: Explicit path to `.env.yml` pipeline configuration.
- `--collection <name|path>`: Overrides `ORACLE_COLLECTION`.
- `--mode <top_k|no_retrieve|full_document>`: Overrides retrieval mode.
- `--type <code|docs>`: Corpus filter restricting search to `*_code` or `*_docs` tables.
- `--no-rag`: Bypasses RAG vector retrieval for pure LLM inference.
- `--no-rerank`: Disables cross-encoder reranking.
- `--recall-k <N>`: Candidate retrieval pool size prior to reranking.
- `--claims-only`: Validates paragraph claims against knowledge base.
- `--reasoning-effort <low|medium|high>`: Reasoning effort for thinking models.
- `--temperature <float>`: Sampling temperature override.
- `--debate [code|review]`: Launches multi-turn deliberation.
- `--loops <N>`: Maximum loops per debate round (default: 3).
- `--rounds <N>`: Maximum debate rounds (default: 1).
- `--persist`: Continues debate audit exploration after provisional agreement.
- `--oracle-persona <path>` / `--architect-persona <path>`: Custom system prompt personas.
- `--oracle-file <path>` / `--architect-file <path>`: Injects instruction templates.

#### `aider-validate` (`validator.py`)
```bash
# Evidence grounding audit
aider-validate --file review.md --source source_ocr.md --report heal_report.md

# Unanchored claims verification
aider-validate --file response.md --claims-only --report claims_report.md

# Pre-debate deterministic ellipsis-stitching
aider-validate --file review.md --source source_ocr.md --autofix

# Post-debate terminal status finalization
aider-validate --file review.md --source source_ocr.md --finalize-unsupported --baseline-ledger debate.json
```
- `--file <path>`: Path to generated markdown review document.
- `--source <path>`: Path to ground-truth OCR markdown file.
- `--report <path>`: Destination path for generated audit report.
- `--tag <name>`: Anchor tag token (default: `evidence`).
- `--region-threshold <float>`: Cosine similarity threshold (default: 0.60).
- `--region-margin <int>`: Context line margin around claim paragraph (default: 2).
- `--region-paragraphs <int>`: Additional paragraphs to expand context (default: 0).
- `--top-k <int>`: Number of LanceDB chunks to retrieve for claim context (default: 5).
- `--claims-only`: Evaluates raw paragraphs without requiring `[evidence]` tags.
- `--autofix`: Stitches ellipsis-separated quotes matching continuous source spans.
- `--finalize-unsupported`: Finalizes agreed ungrounded quotes to `[unsupported]`.
- `--baseline-ledger <path>`: Path to debate ledger holding `quote_baseline`.
- `--grounding-model <name>`: Model identifier for MiniCheck entailment verification.
- `--entail-threshold <float>`: Entailment probability cutoff (default: 0.50).
- `--verify-all`: Scores claims around all quotes, including grounded quotes.

#### `aider-apply` (`apply_agent.py`)
```bash
# Apply specification from active session chat history to target files
aider-apply src/main.py src/utils.py

# Apply explicit specification file with live terminal output
aider-apply src/core/engine.py --spec active_spec.md --stream
```
- `files...`: One or more target files to modify.
- `--spec, -s <path>`: Explicit specification markdown file path.
- `--turns, -t <int>`: Number of recent chat history turns to include in spec (default: 1).
- `--model, -m <name>`: Overrides editor model.
- `--session <name>`: Overrides active session directory.
- `--no-diff`: Suppresses git diff summary output.
- `--stream`: Streams inner Aider terminal output via `/dev/tty` or `CONOUT$`.

#### `aider-research` (`research_agent.py`)
```bash
# Academic web search
aider-research "Transformer multi-head attention optimizations" --academic --top 10

# Sitemap harvest with regex filtering
aider-research "https://docs.rs/sitemap.xml" --sitemap --grep "tokio" --out urls.txt
```
- `"<query>"`: Web search query string.
- `--academic`: Restricts engines to scientific databases (arXiv, Google Scholar, CrossRef).
- `--engines <e1,e2>`: Comma-separated list of engines (e.g. `google,duckduckgo`).
- `--top <int>`: Maximum search results to retrieve (default: 10).
- `--time-range <range>`: Filters by recency (`day`, `month`, `year`).
- `--links-only, -l`: Outputs bare URLs, one per line.
- `--out, -o <file>`: Destination output path for report or URL list.
- `--sitemap`: Extracts URLs from domain XML sitemap or `llms.txt`.
- `--grep, -g "<pattern>"`: Case-insensitive regex filter for discovered URLs.
- `--grep-exclude, -ge "<p>"`: Regex exclusion pattern.
- `--site-depth, -d <N>`: Recursive sub-sitemap crawl depth (default: 1).

---

## 5. Configuration Schema & YAML Knobs

### 5.1 Complete Annotated Pipeline Schema

```yaml
# =============================================================================
# AI FACTORY PIPELINE CONFIGURATION SCHEMA (.env.yml)
# =============================================================================

# -----------------------------------------------------------------------------
# 1. PROJECT IDENTITY & WORKSPACE ROOT
# -----------------------------------------------------------------------------
name: "Production Workspace"                     # String: Human-readable name for the pipeline run
working_directory: "/path/to/project"            # String: Canonical workspace root (always use forward slashes)

# -----------------------------------------------------------------------------
# 2. DISPLAY & DEBATE COLOR SCHEME (24-bit TrueColor)
# -----------------------------------------------------------------------------
colors:
  architect_debate: "#38bdf8"                    # String: Hex color for Architect stream (default: Teal)
  oracle_debate: "#d3869b"                       # String: Hex color for Oracle stream (default: Soft Rose)

# -----------------------------------------------------------------------------
# 3. GLOBAL TEST HARNESS & LINTING CONTROLS
# -----------------------------------------------------------------------------
test_command_prefix: ""                          # String: Optional prefix (e.g. "docker exec -t app", "source venv/bin/activate &&")
test_runner: "uv run --with pytest pytest {file}"# String: Universal runner template substituting {file}
test_naming_and_path: "tests/test_{stem}.py"     # String: Universal fallback test path template substituting {stem}
lint_cmd: null                                   # String | null: Custom lint command (e.g. "ruff check --fix {file}")
auto_lint: true                                  # Boolean: Execute automated linter after code edits
loop_aider_test: 3                               # Integer: Autonomous outer retry loops when tests fail

# -----------------------------------------------------------------------------
# 4. GLOBAL API ENDPOINTS (Unified Proxy Routing)
# -----------------------------------------------------------------------------
endpoints:
  architect_api_base: "http://127.0.0.1:4000/v1" # String | null: Base URL for Architect LLM
  editor_api: "http://127.0.0.1:4000/v1"         # String | null: Base URL for Primary Editor LLM
  editor_api_fallback: "http://127.0.0.1:4000/v1"# String | null: Base URL for Test / Fallback Editor
  rag_agent_api: "http://127.0.0.1:4000/v1"      # String | null: Base URL for Knowledge Oracle LLM
  grounding_agent_api: "http://127.0.0.1:8090/v1"# String | null: Base URL for MiniCheck Entailment Server
  ranking_api_base: null                         # String | null: Base URL for remote reranker (null = local in-process)
  ocr_api_base: "http://127.0.0.1:8081/v1"       # String | null: Base URL for local Vision OCR (null = cloud API)
  embed_api_base: "http://127.0.0.1:4000/v1"     # String | null: Base URL for Dense Embedding Server
  weak_model_api_base: "http://127.0.0.1:4000/v1"# String | null: Base URL for Weak Model

# -----------------------------------------------------------------------------
# 5. GLOBAL MODELS
# -----------------------------------------------------------------------------
models:
  architect_agent: "gemini/gemini-3.7-flash"     # String: Default Architect reasoning model
  editor_agent: "gemini/gemini-3.6-flash"        # String: Default Primary Editor code model
  editor_agent_test: "gemini/gemini-3.6-flash"   # String: Default Test Editor code model
  editor_agent_test_fallback: "gemini/gemini-3.7-flash" # String | null: Escalation model on retry attempt > 0
  weak_model: "gemini/gemini-2.5-flash"          # String: Lightweight model for git commits and summaries
  rag_agent: "gemini/gemini-3.6-flash"           # String: Knowledge Oracle model
  ranking_agent: "jinaai/jina-reranker-v3.5"     # String: Neural cross-encoder reranker
  ocr_agent: "gemini/gemini-2.5-flash"           # String: Multimodal model for document image OCR
  embed_model: "gemini/text-embedding-004"       # String: Dense vector embedding model
  grounding_agent: "openai/minicheck-flan-t5-large" # String: NLI verification model
  reasoning_effort: "high"                       # String: low | medium | high (for reasoning models)
  temperature: 0.8                               # Float: Generation sampling temperature

# -----------------------------------------------------------------------------
# 6. GLOBAL RAG & VECTOR STORE CONFIGURATION
# -----------------------------------------------------------------------------
rag:
  collection_name: "core_lib"                    # String: Default LanceDB collection directory
  batch: true                                    # Boolean: true = shared table; false = per-document tables
  type_filter: null                              # String | null: "code" (*_code tables) | "docs" (*_docs tables) | null (fused)
  retrieval_mode: top_k                          # String: top_k | full_document | no_retrieve
  use_docling: true                              # Boolean: Fast digital PDF extraction via Docling
  docling_do_ocr: true                           # Boolean: Enable OCR inside Docling for hybrid documents
  docling_timeout: 300                           # Integer | null: Maximum seconds per Docling conversion
  run_ocr_rag: false                             # Boolean: Trigger ingestion on pipeline launch
  vectordb_overwrite: false                      # Boolean: Overwrite existing LanceDB tables on ingestion
  ocr_prompt: "Extract the text, tables, and mathematical formulas into Markdown."
  query_prefix: ""                               # String: Embedding model prefix (e.g. "Query: ")
  chunk_size_chars: 1500                         # Integer: Maximum chunk length for prose text
  chunk_overlap_chars: 300                       # Integer: Overlap character length between sequential chunks
  recall_k: 75                                   # Integer: Stage 1 candidate pool size from LanceDB
  top_k: 20                                      # Integer: Stage 2 candidate pool size after reranking
  cer_threshold: 0.05                            # Float: Character Error Rate cutoff before OCR retry
  ocr_max_retries: 2                             # Integer: Maximum OCR retry attempts per page
  ocr_parallel: 4                                # Integer: Number of concurrent page OCR workers
  code_chunk_size: 2000                          # Integer: Maximum characters per Tree-Sitter code chunk
  ocr_max_tokens: 4096                           # Integer: Maximum tokens per OCR generation call
  embed_backend: "sentence-transformers"         # String: "sentence-transformers" | "openai"
  working_repo: "core_lib"                       # String: Self-exclusion directory to prevent RAG pollution

# -----------------------------------------------------------------------------
# 7. EXECUTION PHASES (DAG Task Specifications)
# -----------------------------------------------------------------------------
phases:
  - name: "Phase_01_Production_Engineering"
    enabled: true

    # Per-Phase Test Harness Overrides (falls back to section 3 if omitted)
    test_naming_and_path: "tests/unit/test_{stem}.py"
    test_runner: "uv run --with pytest pytest {file}"
    test_command_prefix: ""

    # Phase Model Overrides
    models:
      architect_agent: "gemini/gemini-3.7-flash"
      editor_agent: "gemini/gemini-3.6-flash"
      editor_agent_test: "gemini/gemini-3.6-flash"
      editor_agent_test_fallback: "gemini/gemini-3.7-flash"
      weak_model: "gemini/gemini-2.5-flash"

    # Phase RAG Overrides
    rag:
      collection_name: "core_lib"
      retrieval_mode: top_k
      recall_k: 75
      top_k: 20

    # Knowledge Oracle & Pre-Edit Deliberation
    oracle:
      start_job: false                           # Boolean: true = Review/Grounding Mode; false = Code Mode
      template: "src/aider_factory/markdown/internal/analyze_bugs.md"
      full_document: false                       # Boolean: Inject entire table text instead of top_k search
      pre_edit_debate:
        enabled: true                            # Boolean: Execute debate before editing files
        insert_debate: [0, 0, 1]                 # 3-Tuple: [Job 1 debate, Job 2 debate, Job 3 debate]
        loops: 3                                 # Integer: Max turns per debate round
        rounds: 1                                # Integer: Number of debate rounds
        pass_history: true                       # Boolean: Carry conversation context across rounds
        persist: false                           # Boolean: Continue audit turns after provisional agreement
        job_debate_template: "markdown/templates/testing_debate.md" # String or list [j1, j2, j3]
        job_debate_collection: ""                # String: Vector collection ("" = bypass RAG, audit AST)
        job_debate_db: ""                        # String: Vector database path override

    # Runtime Execution Toggles
    toggles:
      pair_programming: false                    # Boolean: Interactive terminal PTY vs autonomous DAG
      shared_history: false                      # Boolean: false = isolate chat history per target file
      run_job_one: true                          # Boolean: Execute Job 1 (Implementation)
      run_job_two: false                         # Boolean: Execute Job 2 (Spec Audit / Validation)
      run_job_three: true                        # Boolean: Execute Job 3 (Write Tests)
      iterate_test: true                         # Boolean: Autonomous test-fixing iteration
      auto_test: false                           # Boolean: Let Aider iterate tests natively in 3-loop batches
      auto_lint: true                            # Boolean: Run automated linter before commits
      lint_cmd: null                             # String | null: Custom linter command
      sticky_context: false                      # Boolean: Retain completed files from earlier targets
      map_tokens: 0                              # Integer: Repo map token budget (0 = disabled)
      map_refresh: "manual"                      # String: manual | auto | always
      map_multiplier_no_files: 0                 # Float: Multiplier when no files are loaded
      max_chat_history_tokens: 100000            # Integer: Chat history ceiling
      yes_always: true                           # Boolean: Auto-confirm prompts non-interactively
      auto_accept_architect: true               # Boolean: Auto-accept Architect proposal to Editor
      auto_commits: true                         # Boolean: Git commit after every successful edit
      suggest_shell_commands: true               # Boolean: Permit model to suggest shell commands
      detect_urls: false                         # Boolean: Scrape URLs in responses
      disable_playwright: false                  # Boolean: Prevent browser installations

    # Sticky Phases Discovery
    sticky_phases:
      editable: false                            # Boolean: Auto-discover target_files from strategy plan
      readonly: false                            # Boolean: Auto-discover context_files from strategy plan

    # Evidence Grounding & Validation
    validation:
      enabled: false                             # Boolean: Activate substring evidence audit
      post_validate: false                       # Boolean: Run agent heal loop on failing quotes
      claims_only: false                         # Boolean: Validate unanchored prose claims
      validation_tag: "evidence"                 # String: Anchor tag token (e.g. [evidence])
      region_threshold: 0.60                     # Float: Cosine similarity cutoff
      region_margin: 2                           # Integer: Line margin around claim paragraph
      region_paragraphs: 0                       # Integer: Additional paragraphs to expand context
      region_top_k: 5                            # Integer: Chunks to retrieve for region check
      validation_loops: 3                        # Integer: Max heal attempts in review mode
      redo_oracle_job: false                     # Boolean: Force regeneration of review documents
      verify_all_claims: false                   # Boolean: Verify claims around grounded quotes
      entail_threshold: 0.5                      # Float: MiniCheck support probability cutoff

    # Post-Failure Escalation Deliberation
    escalation_debate:
      loops: 3                                   # Integer: Maximum debate turns per round
      rounds: 1                                  # Integer: Number of debate -> apply -> test rounds
      pass_history: true                         # Boolean: Retain debate context across rounds
      persist: false                             # Boolean: Continue exploring audit layers after agreement

    # File Allocations
    files:
      target_files: ["src/core/engine.py"]       # List[String]: Primary editable files
      extra_editable_files: []                   # List[String]: Secondary editable files
      test_files: []                             # List[String]: Test files (auto-derived if empty)
      context_files_job: []                      # List[String]: Read-only context for Job 1 & 2
      context_files_test: []                     # List[String]: Read-only context for Job 3 & tests

    # Markdown Plans & Templates
    plans:
      job_one_plan: "markdown/templates/implement.md"
      job_two_plan: "markdown/templates/validate.md"
      job_three_plan: "markdown/templates/testing_exec.md"
      iterate_plan: "markdown/templates/testing_unit_iterate.md"

---

### 5.2 Configuration Cross-Validation Matrix

| Parameter Path | Layman Explanation & Codepath | Edge Cases & Runtime Precedence |
| :--- | :--- | :--- |
| `name` / `working_directory` | Pipeline identity and canonical root. Evaluated in `run_workflow.py` and passed to `os.chdir()`. | Forward slashes required. If `working_directory` is missing, defaults to current working directory (`base_cwd`). |
| `colors.architect_debate` / `colors.oracle_debate` | Terminal 24-bit TrueColor hex strings converted via `_hex_to_ansi()` in `run_workflow.py`. | Exported as `PIPELINE_COLOR_ARCHITECT` and `PIPELINE_COLOR_ORACLE`. Malformed hex falls back to standard ANSI codes. |
| `test_runner` / `test_command_prefix` / `test_naming_and_path` | Hierarchical test command builder: `{prefix} {runner.replace('{file}', specific_test_file)}`. | **Precedence**: `phase` > `phase.files` / `phase.toggles` > global root configuration. Enables seamless unit $\rightarrow$ integration $\rightarrow$ E2E transitions. |
| `endpoints.*` | Maps LLM provider endpoints to child processes in `orchestrate.py`. | Local endpoints are injected into `OPENAI_API_BASE`, `OLLAMA_API_BASE`, or `LM_STUDIO_API_BASE`. Cloud models (`gemini/`) clear API bases. |
| `models.editor_agent_test_fallback` | Escalation code model substituted during test iterations on attempt $> 0$. | Triggered in `orchestrate.py` when `attempt > 0` and `fallback_editor_model` is defined. Allows cheap initial models with strong fallback. |
| `models.weak_model` / `endpoints.weak_model_api_base` | Lightweight model for metadata operations (git commit messages, token summaries). | Strict isolation: `is_local_model()` ensures cloud weak models never receive local router endpoints. Synthesizes session `.aider.model.settings.yml`. |
| `rag.batch` | Controls LanceDB table topology in `rag_manager.py`. | `true`: Single shared corpus table (`<collection_name>`). `false`: Per-document tables named via `table_name_for(file)`. |
| `rag.type_filter` | Restricts RRF candidate retrieval to specific corpus types in `oracle_agent.py`. | Options: `null` (fuses all tables), `"code"` (searches `*_code` tables), or `"docs"` (searches `*_docs` tables). |
| `rag.use_docling` / `docling_timeout` | Triggers high-speed digital document parsing via `docling_runner.py`. | Bypasses pixel rasterization and OCR for digital PDFs, Word, PowerPoint, and Excel documents. Scanned pages trigger Vision OCR fallback. |
| `rag.recall_k` / `rag.top_k` | Two-stage candidate filtering parameters in `oracle_agent.py`. | LanceDB retrieves `recall_k` vector candidates, which are reranked down to `top_k` by the neural cross-encoder. |
| `oracle.start_job` | Primary mode discriminator in `run_workflow.py`. | `false`: Enforces Code Mode (Jobs 1–4, test iteration). `true`: Enforces Review / Evidence Grounding Mode (synthesis, autofix, healing). |
| `oracle.pre_edit_debate.insert_debate` | 3-tuple `[j1, j2, j3]` parsed by `_parse_insert_debate()` in `run_workflow.py`. | Triggers an ask-mode Architect <-> Oracle deliberation before Job 1, Job 2, or Job 3. `[0, 0, 1]` runs Pre-Test Deliberation before test authoring. |
| `oracle.pre_edit_debate.job_debate_collection` | Vector collection name for pre-edit debates. | Setting `job_debate_collection: ""` bypasses LanceDB retrieval, causing the Oracle to audit source code ASTs directly under `<project_files>`. |
| `toggles.pair_programming` | Suspends autonomous loops and wraps Aider in an interactive terminal PTY. | Uses `script -qfe` (Linux), `script -q` (macOS), or Win32 line-tee. Plan templates are passed via `--read` so the user drives the conversation. |
| `toggles.shared_history` | Toggles state vault isolation in `orchestrate.py`. | `false`: Enforces strict isolation per target file (`.aider.chat.history_<stem>.md`). `true`: Shares conversation history across all target files. |
| `toggles.map_tokens` / `map_refresh` | Repository map token budget and refresh policy. | Set `map_tokens: 0` and `map_refresh: manual` for isolated tasks to eliminate background AST recomputation and preserve KV-cache stickiness. |
| `toggles.auto_lint` / `lint_cmd` | Executes automated code linter prior to git commits. | If `lint_cmd` is null, defaults to language conventions. Non-zero exit codes prevent git commit and push error traces back to the Editor. |
| `sticky_phases.editable` / `sticky_phases.readonly` | Automatic target and context file discovery in `run_workflow.py`. | Parses YAML or markdown blocks from strategy plans via `_extract_files_from_plan()`, prunes non-existent files, and routes test files. |
| `validation.enabled` / `validation_tag` | Activates substring evidence grounding in `validator.py`. | Parses `[evidence]` tags, verifies exact substring match in OCR source, and computes semantic cosine similarity and MiniCheck entailment. |
| `escalation_debate.rounds` / `pass_history` | Multi-round deliberation cycles on persistent test failure. | Deliberation produces an actionable verdict (`.verdict.md`), which `apply_agent.py` applies to disk. `pass_history: true` carries debate memory. |
| `plans.job_three_plan` | Injected template for Job 3 test authoring. | Use `markdown/templates/testing.md` for standalone test generation. Use `markdown/templates/testing_exec.md` when executing pre-test debate consensus. |

---

### 5.3 Iteration Strategy Matrix

The combination of `loop_aider_test`, `auto_test`, and `max_aider_loops` governs the autonomous test repair cycle:

| `loop_aider_test` | `auto_test` | Total Attempts | Architect Interaction | Optimal Use Case |
| :---: | :---: | :---: | :---: | :--- |
| `1` | `false` | 1 | Every attempt | Single-shot implementation, simple documentation generation, manual inspection |
| `3` | `false` | 3 | Every attempt | Standard feature development, focused bug-fixing with deep Architect diagnosis |
| `3` | `true` | 9 | Every 3 attempts | Fast unit test fixing where the Editor can rapidly resolve syntax and assert errors |
| `5` | `false` | 5 | Every attempt | High-complexity algorithmic refactoring requiring close step-by-step guidance |
| `5` | `true` | 15 | Every 3 attempts | Autonomous legacy test suite migration and comprehensive test healing |

**Terminal Verification Invariant**:
- In Code Mode, `Task.final_check = True` re-runs the test suite once after loop exhaustion to verify the final edit. If tests fail, the task fails honestly (`exit code 1`).
- In Review Mode, `Task.soft_fail = True` allows loop exhaustion to proceed to the terminal `finalize` step, which serves as the ultimate authority for tagging ungrounded quotes as `[unsupported]`.

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

### 6.1 Process Tree Sandboxing & Timeout Handling
Subprocesses spawned across `orchestrate.py`, `apply_agent.py`, and `run_workflow.py` are registered in distinct process groups (`start_new_session=True`). This guarantees clean termination of all child processes (compilers, test runners, Python workers) when timeouts occur.

- **POSIX Termination**: Computes the process group ID (`pgrp = os.getpgid(proc.pid)`) and issues `os.killpg(pgrp, signal.SIGKILL)`.
- **Windows Termination**: Executes `taskkill /F /T /PID <pid>` to force-terminate the process tree.
- **Timeout Thresholds**:
  - `AIDER_STREAM_TIMEOUT`: Configurable stream watchdog (default: 300 seconds).
  - Main task execution timeout: 600 seconds.
  - Test baseline and gate evaluation timeout: 300 seconds.

### 6.2 Stream Multiplexing & OSTee Telemetry
The `OSTee` context manager redirects operating system file descriptors 1 (`stdout`) and 2 (`stderr`):
- **POSIX Systems**: Uses `os.pipe()` and `os.dup2()` to capture all output from Python and native subprocesses (`git`, `pytest`, `cargo`, `Rscript`), pumping output simultaneously to the terminal (with ANSI color preservation via `FORCE_COLOR=1`) and `.aider_factory/logs/<config_stem>_run_<timestamp>.log`.
- **Windows Systems**: Employs synchronized write-through wrappers (`_TeeWriter`) over `sys.stdout` and `sys.stderr`.
- **Inner Aider Isolation (`aider-apply`)**: When executing headless code applications, inner tool telemetry is redirected to `/dev/tty` (POSIX) or `CONOUT$` (Windows) to maintain terminal visibility without polluting the outer Aider context window.

### 6.3 Rate-Limiting & Public Instance Failovers (`research_agent.py`)
When executing web searches, `research_agent.py` queries local SearXNG endpoints (`http://localhost:8088`), dynamically falling back to public instances:
1. Queries `https://searx.space/data/instances.json` (cached locally for 24 hours).
2. Filters instances: `network_type == "normal"`, 30-day uptime $\ge 99\%$, grade in `["A", "A+", "V"]`, and Google engine error rate $< 50\%$.
3. Sorts candidate instances by latency and cycles through the top 5 fallbacks if the local instance returns rate-limit (`429`) or unresponsive engine errors.

### 6.4 Context Window Budgeting & Sentinel Preservation
To prevent multi-hop reasoning degradation, total prompt token utilization is budgeted below 70%:

| Budget Slice | Target Percentage | Function & Contents |
| :--- | :---: | :--- |
| $T_{\text{prefix}}$ | 5–10% | Locked, immutable byte-parity prompt prefix (KV-cache anchor) |
| $T_{\text{repomap}}$ | 10–20% | Ranked dependency map (set `map_tokens: 0` for isolated single-file tasks) |
| $T_{\text{retrieval}}$ | 20–30% | RRF-fused, reranked LanceDB knowledge passages ($k=20$) |
| $T_{\text{history}}$ | 20–30% | Structured task state ledgers and compact sliding conversation window |
| $T_{\text{headroom}}$ | 15–20% | Generation headroom for reasoning traces and code diff output |

**Protected Sentinel Set**: During context compression or multi-turn handoffs, the following elements must never be generalized, truncated, or paraphrased:
- Exact relative file paths (e.g. `src/core/engine.py`).
- Exact symbol identifiers, function signatures, and class names.
- Mathematical formulations and invariant rules.
- Active Task IDs (e.g. `[Task ID: 001]`).

### 6.5 Anchor Deletion Guard & Ledger Auditing (`validator.py`)
In Review / Grounding Mode, `validator.py` enforces deletion protection using quote hashing:
1. Prior to editing, initial quote hashes are stored in `quote_baseline` inside the debate ledger (`.debate.json`):
   $$\text{Hash}(q) = \text{SHA1}(\text{norm}(q))[:12]$$
2. During validation, the total number of recognized anchors ($|items|$) is evaluated against baseline hashes:
   $$\text{Violation} \iff |items| < |quote\_baseline|$$
3. If an anchor was removed or retagged outside the recognized vocabulary (`[evidence]`, `[validated]`, `[fixed]`, `[unsupported]`), the validator triggers an `ANCHOR COUNT DROPPED` error, halting the pipeline and requiring human review.
4. **Terminal Relabeling Rules**:
   - Grounded quotes present in `quote_baseline` $\rightarrow$ `[validated]`.
   - Grounded quotes whose text was edited $\rightarrow$ `[fixed]`.
   - Ungrounded quotes from an agreed debate $\rightarrow$ `[unsupported]`.
   - Ungrounded quotes from deadlocked/exhausted debates remain tagged `[evidence]` for manual remediation.
