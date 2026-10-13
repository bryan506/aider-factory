# Pipeline DAG & Autonomous Debates

## 1. Executive Overview & Foundational Invariants

The AI Factory orchestrates an industrial-grade, multi-stage software engineering Directed Acyclic Graph (DAG) via `run_workflow.py` and `orchestrate.py`. It integrates granular pre-edit debate insertion, dynamic strategy injection, and OS-level stream multiplexing to ensure deterministic, reproducible, and fully observable autonomous execution.

### Foundational Invariants

1. **Deterministic-First Execution**: The pipeline executes deterministic verification scripts, AST analysis, and exact-substring tests before engaging LLM judgment. Grounding and verification rely on real OS exit codes (`0`), verified disk diffs, and exact hash matches.
2. **Strict State Isolation & Zero Blast Radius**: No task, experiment, or turn may bleed state, prompt history, or scratch artifacts into adjacent execution contexts. All per-file chat and input histories are isolated via active stage swapping into a session vault (`.aider_factory/sessions/<slug>/chat_history/`).
3. **KV-Cache & Context Efficiency**: Prompts utilize immutable byte-parity prefixes, append-only delta injection, and deterministic serialization (`PYTHONHASHSEED=0`) to maximize prefix cache hits. Context utilization is monitored to prevent multi-hop reasoning degradation.
4. **Minimal-Delta Scoping**: Edits are confined strictly to active target files assigned in the DAG task. Scaffolding, comments, and inactive blocks are preserved intact.
5. **Truthful Documentation & Separation of Concerns**: Technical manuals strictly reflect shipped, running code without hallucinated or planned features. Clear boundaries are maintained between Architecture Manuals, Feature References, and Agent Skills.
6. **Three-Tier Observability Mesh**: Every execution is preserved across three synchronized tiers:
   - *Tier 1: Live Interactive Terminal Streaming*: ANSI truecolor output multiplexed to the user terminal.
   - *Tier 2: Master Replay Log*: Byte-for-byte stream capture written to `.aider_factory/logs/<config_stem>_run_<timestamp>.log`.
   - *Tier 3: Structured Disk Artifacts*: Formal Markdown transcripts, JSON state ledgers, and chat histories stored in `.aider_factory/logs/` and `.aider_factory/sessions/`.
7. **Deterministic Financial Accounting**: Every token sent and received is parsed, aggregated, and logged into a USD cost ledger. Process and session totals are tracked using exact model pricing without extrapolation.
8. **Spec-Anchored Lifecycle Contract**: Autonomous execution follows a rigid 7-phase sequence:
   $$\text{Understand} \longrightarrow \text{Diagnose} \longrightarrow \text{Spec} \longrightarrow \mathbf{\text{Approval Gate}} \longrightarrow \text{Implement} \longrightarrow \text{Cross-Validate} \longrightarrow \text{Document}$$

## 2. System Topology & Lifecycle Flowcharts

### 2.1 The 4-Stage Autonomous DAG Topology

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   THE 4-STAGE AUTONOMOUS DAG                                    │
├───────────────────┬───────────────────┬─────────────────────────┬───────────────────────────────┤
│ STAGE 1:          │ STAGE 2:          │ STAGE 3:                │ STAGE 4:                      │
│ Implementation    │ Spec Audit        │ Write Tests             │ Self-Healing Loop             │
│ (`run_job_one`)   │ (`run_job_two`)   │ (`run_job_three`)       │ (`iterate_test`)              │
├───────────────────┼───────────────────┼─────────────────────────┼───────────────────────────────┤
│ • Architect plans │ • Senior reviewer │ • Writes unit tests for │ • Executes test runner        │
│ • Editor writes   │   spec audit      │   new implementation    │ • Ingests failure output      │
│   initial code    │ • Strategy-locked │ • Broad-scope coverage  │ • Iterative fix attempts      │
│ • Pre-Debate: J1  │ • Pre-Debate: J2  │ • Pre-Debate: J3        │ • Escalation Debate           │
└─────────┬─────────┴─────────┬─────────┴────────────┬────────────┴───────────────┬───────────────┘
          │                   │                      │                            │
          ▼                   ▼                      ▼                            ▼
   [Debate J1]         [Debate J2]            [Debate J3]                  [Escalation Debate]
   (Pre-Edit)          (Pre-Edit)             (Pre-Edit)                   (Multi-Round)
```

### 2.2 Multi-Round Escalation Reflexion & Chained Ledger Architecture

```text
               STAGE 4 TEST SUITE FAILURE (Exit Code != 0)
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │ ROUND r: INITIATE DELIBERATION TASK                    │
       │ Inputs: Seed Prompt + Test Failure Log + Prior Ledger  │
       └────────────────────────────┬───────────────────────────┘
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │ ORACLE TURN 0 (Pre-Assessment)                         │
       │ Inputs: Code files + LanceDB context + Failure log     │
       └────────────────────────────┬───────────────────────────┘
                                    │
                                    ▼
   ┌───► ┌────────────────────────────────────────────────────┐
   │     │ ARCHITECT TURN (Refine Proposal)                   │
   │     │ Output: PROPOSAL: <one-line summary>               │
   │     └──────────────────────────┬─────────────────────────┘
   │                                │
   │                                ▼
   │     ┌────────────────────────────────────────────────────┐
   │     │ ORACLE TURN (Critical Review)                      │
   │     │ Output: <critique>... VERDICT: AGREE|REVISE|OBJECT │
   │     └──────────────────────────┬─────────────────────────┘
   │                                │
   │                                ▼
   │     ┌────────────────────────────────────────────────────┐
   │     │ CONSENSUS EVALUATION (deliberate.py)               │
   │     └──────┬───────────────────┬───────────────────┬─────┘
   │            │                   │                   │
   │       [Continue]           [Deadlock]          [Agreed]
   │       (Turn < N)          (Hash match)             │
   └───◄────────┘                   │                   │
                                    │                   ▼
                                    │         ┌───────────────────┐
                                    │         │ WRITE VERDICT     │
                                    │         │ STATUS: agreed    │
                                    │         │ GATE: present     │
                                    │         └─────────┬─────────┘
                                    │                   │
                                    │                   ▼
                                    │         ┌───────────────────┐
                                    │         │ APPLY TASK        │
                                    │         │ Headless Editor   │
                                    │         └─────────┬─────────┘
                                    │                   │
                                    │                   ▼
                                    │         ┌───────────────────┐
                                    │         │ TEST SUITE GATE   │
                                    │         └──────┬─────┬──────┘
                                    │                │     │
                                    │            [Pass]   [Fail]
                                    │              │       │
                                    ▼              ▼       ▼
                       ┌───────────────────────────────┐ ┌───────────────┐
                       │ SUCCESS: PROCEED IN DAG       │ │ NEXT ROUND?   │
                       │ Exit Code: 0                  │ │ r < rounds:   │
                       │                               │ │ r = r + 1     │
                       └───────────────────────────────┘ └───────┬───────┘
                                                                 │
                                                                 ▼
                                                  ┌───────────────────────────────┐
                                                  │ CHAIN PRIOR LEDGER            │
                                                  │ Extract failed proposal into  │
                                                  │ Round r + 1 Seed Prompt       │
                                                  └───────────────────────────────┘
```

### 2.3 Vault State-Swapping Lifecycle

```text
 ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
 │                         ACTIVE STAGE: .aider_factory/sessions/<slug>/                       │
 │  • .aider.chat.history.md          • .oracle_session.json          • .pair_capture.log      │
 │  • .aider.input.history            • .oracle_debate_session.json   • .debate_aider_history  │
 │  • .aider.llm.history              • .oracle_chat.history.md                                │
 └──────────────────────────────▲──────────────────────────────▲───────────────────────────────┘
                                │                              │
                1. _swap_in_state(stem)        2. _swap_out_state(stem)
                 (Restore file state)           (Persist file state)
                                │                              │
 ┌──────────────────────────────▼──────────────────────────────▼───────────────────────────────┐
 │                     SESSION VAULT: .aider_factory/sessions/<slug>/chat_history/             │
 │  • .aider.chat.history_<stem>.md             • .oracle_session_<stem>.json                  │
 │  • .aider.input.history_<stem>               • .oracle_debate_session_<stem>.json           │
 │  • .aider.llm.history_<stem>                 • .debate_aider_history_<stem>.md              │
 └─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.4 AI Factory Observability Mesh

```text
                                  AI FACTORY OBSERVABILITY MESH
 ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                             │
 │   1. Orchestrator & Aider Engine ──► OS-Level File Descriptor Interceptor (OSTee)           │
 │   2. LanceDB & Document RAG      ──► Table Ingestion Traces & Chunk Attribution Logs        │
 │   3. Knowledge Oracle Agent      ──► Verbatim Retrieval Transcripts & Stderr File Headers   │
 │   4. Refereed Escalation Debate  ──► Markdown Transcripts & Deterministic JSON Ledgers      │
 │   5. Grounding & MiniCheck       ──► Exact Substring Audit Reports & Entailment Ledgers     │
 │   6. Subprocess Test Runners     ──► Real-Time stdout/stderr Stream (pytest, Rscript)       │
 │   7. Financial Cost Accounting   ──► Token-by-Token Sent/Received & USD Aggregation         │
 │                                                                                             │
 └──────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                                │
                                                ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
 │                               THREE DURABLE OBSERVABILITY TIERS                             │
 ├──────────────────────────────┬──────────────────────────────┬───────────────────────────────┤
 │     1. Live Interactive      │     2. Master Replay Log     │    3. Structured Artifacts    │
 │     Terminal Streaming       │  (.aider_factory/logs/*.log) │ (Sessions, Ledgers, Archives) │
 └──────────────────────────────┴──────────────────────────────┴───────────────────────────────┘
```

## 3. Technical Mechanics & Deep-Dive Logic

### 3.1 Granular Pre-Edit Debates (`insert_debate`)
Before modifying source code in Job 1 (`run_job_one`), Job 2 (`run_job_two`), or Job 3 (`run_job_three`), the orchestrator can insert a deliberation phase between the Architect and Knowledge Oracle.
- **3-Tuple Normalization (`_parse_insert_debate`)**: Converts configuration inputs into a strict boolean 3-tuple $(j_1, j_2, j_3)$:
  - Accepts list/tuple of booleans or integers (e.g. `[1, 0, 1]` $\to$ `(True, False, True)`).
  - Accepts string representations (e.g. `"1, 0, 0"` or `"1 0 0"`). Missing elements default to `False`. If omitted entirely, defaults to `(True, False, False)`.
- **Template Routing (`_resolve_job_debate_template`)**: Index-matches the active job number ($1, 2, 3$) against `job_debate_template`. If passed as a list, index $job\_num - 1$ is resolved. If the list is shorter than the job index, index 0 is used as fallback.
- **Collection & DB Routing (`_resolve_job_debate_collection`)**: Resolves both the vector collection name and LanceDB directory path $(C_{\text{coll}}, D_{\text{dir}})$ for the active job:
  - **Scalar & List Resolution**: `job_debate_collection` and `job_debate_db` accept either a scalar string or a 3-element list `[j_1, j_2, j_3]` indexed by $job\_num - 1$.
  - **Path Normalization**: Database directory paths expand user tildes (`~`), anchor relative paths to `project_directory`, and normalize backslashes (`\`) to forward slashes (`/`).
  - **Smart Path & Zero-RAG Bypass**: If `job_debate_collection` is set to `""`, vector retrieval is bypassed, allowing the Oracle to inspect source AST directly. When an external filesystem path is provided (e.g. `/data/external/lancedb` or `/data/external/collection_name`), the table name and LanceDB directory are auto-detected.

### 3.2 Dynamic Strategy Injection (`_render_validate_template`)
When transitioning from Phase 0 (Planning) to Phase 1 (Execution), `_render_validate_template()` ensures the senior code reviewer in Job 2 audits code against exact specifications:
1. Discovers `strategy_template.md` (or completed markdown outputs from prior phases).
2. Reads the default audit template (`markdown/templates/validate.md`).
3. Injects the strategy text directly into the `## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS` placeholder via regex substitution.
4. Saves the rendered template to `.aider_factory/temp/<stem>_validate_rendered.md` for execution.

### 3.3 Sticky Phases & Automated Scope Analysis (`sticky_phases`)
When `sticky_phases` is enabled in YAML (`editable: true` and/or `readonly: true`), the pipeline automatically extracts file targets from the planning phase artifact (`strategy_template.md` or `job_one_plan`):
- **YAML Block Extraction**: `_extract_files_from_plan()` first searches for YAML blocks within the `## Scope Analysis` section matching:
  ```yaml
  files:
    target_files: ["src/module.py"]
    extra_editable_files: []
    test_files: ["tests/test_module.py"]
    context_files_job: ["README.md"]
    context_files_test: ["README.md"]
  ```
- **Markdown Header Fallback**: If no YAML block is present, it parses bulleted lists under `### Target Files:`, `### Extra Editable Files:`, `### Test Files:`, and `### Context Files:`.
- **Structural Isolation via `is_test_path()`**: Any file placed in `target_files` that matches test naming conventions (directories like `tests/`, `spec/`, or suffixes `_test.py`, `test_*.py`, `*.spec.ts`) is automatically quarantined and moved to `test_files` to prevent implementation tasks from polluting tests.
- **Physical Disk Verification**: Prunes phantom paths; files in `target_files` must physically exist on disk (or be expanded via glob patterns), while new `test_files` may be scheduled for creation.

### 3.4 Multi-Round Escalation Reflexion (`escalation_debate`)
If the test suite fails during Stage 4 (`iterate_test`), the orchestrator triggers an escalation debate:
- **Debate Rounds (`rounds`)**: Chained full debate cycles (Debate $\to$ Apply $\to$ Re-Test).
- **Cross-Round Memory (`pass_history`)**: Carries prior turn context and model KV caches across rounds (`pass_history: true`).
- **Ledger Chaining**: Passes `<stem>.job_verdict_r1.md` and `<stem>.job_debate_r1.json` to Round 2. The orchestrator explicitly parses the `prior_ledger` to extract the exact failed proposal from the previous round and injects it into the new prompt, giving the model memory of its past attempts to prevent infinite loops of identical fixes.
- **Persistent Exploration (`persist: true`)**: When enabled, the debate does not terminate on provisional agreement. Instead, the Architect is prompted to rotate focus to boundary conditions, concurrency, and unhandled exceptions across subsequent turns.

### 3.5 Consensus State Machine & Arbitration (`deliberate.py`)
The referee operates deterministically without LLM calls:
- **Proposal Hash**: Computes SHA1 hash on normalized `PROPOSAL:` lines:
  $$H(P) = \text{SHA1}(\text{normalize}(P))[0:12]$$
- **Oracle Verdict Parsing**: Extracts `VERDICT: AGREE | OBJECT | REVISE | DISAGREE | REJECT`. Strips critique blocks (`<critique>...</critique>`) and evaluation contracts before parsing. Normalizes `DISAGREE` and `REJECT` to `object`.
- **Deadlock Detection Rule**:
  $$\text{State} = \begin{cases}
  \text{'agreed'} & \text{if } V_t = \text{'agree'} \\
  \text{'deadlock'} & \text{if } H(P_t) = H(P_{t-1}) \wedge V_t, V_{t-1} \in \{\text{'object'}, \text{'revise'}\} \\
  \text{'continue'} & \text{otherwise}
  \end{cases}$$
- **Actionable Verdict Contract**: A verdict file is actionable by the downstream edit pass iff:
  $$A = (S = \text{'agreed'} \wedge G = \text{'present'}) \vee D_{\text{draft}}$$
  where $S$ is status, $G$ indicates presence of a deterministic verification gate, and $D_{\text{draft}}$ is draft mode. Writes atomically via `tempfile.mkstemp` and `os.replace`.

### 3.6 Polymorphic Gate Execution (`_gate_run`)
In review and grounding modes, the deterministic verification gate is constructed as a structured command list (`[sys.executable, validator.py, ...]`) rather than a shell string. `orchestrate.py` inspects the command type:
- **List Command (`isinstance(cmd, list)`)**: Executes with `shell=False` and indexes the gate cache using an immutable tuple `tuple(cmd)`. This prevents shell injection vulnerabilities and eliminates platform-specific shell escaping bugs on Windows.
- **String Command (`isinstance(cmd, str)`)**: Executes with `shell=True` using the user's configured `test_cmd`, indexed in cache by the raw command string.
- **Process-Tree Termination (`kill_proc_tree`)**: Both execution paths are protected by watchdog timers (`AIDER_STREAM_TIMEOUT`, default 300s). On timeout or cancellation, `kill_proc_tree` terminates process trees via `taskkill /F /T` on Windows or `os.killpg(pgrp, SIGKILL)` on POSIX.

### 3.7 OS-Level Stream Multiplexing (`OSTee` & `_TeeWriter`)
Standard Python logging drops subprocess stdout/stderr. `run_workflow.py` wraps execution in `OSTee`:
- **POSIX Platforms (Linux & macOS)**: Duplicates file descriptors 1 and 2 at the kernel level using `os.dup()` and redirects them via `os.dup2()` to an OS pipe drained by a background pump thread.
- **Windows (`win32`)**: Redirects `sys.stdout` and `sys.stderr` to `_TeeWriter` stream proxies that simultaneously write to the active console and the log file, avoiding `os.dup2` descriptor corruption on Windows.

### 3.8 Session State Isolation & Vault Swapping
To achieve zero cross-file context contamination, `AiderFactory` manages active session state files:
- Active state files: `.aider.chat.history.md`, `.aider.input.history`, `.aider.llm.history`, `.oracle_session.json`, `.oracle_debate_session.json`, and `.pair_capture.log`.
- **Vault Mapping**: `_get_vault_path(active_path, stem)` stores archives in `.aider_factory/sessions/<slug>/chat_history/<base>_<stem>.<ext>`.
- **Swapping Lifecycle**:
  - `_swap_in_state(stem)`: Wipes active files from the session root and copies in the file-specific history vault.
  - `_swap_out_state(stem)`: Persists active files back to the vault on task completion.
  - `shared_history: true`: Bypasses swapping when unified multi-file session history is explicitly desired.
  - `dependencies_met(task)`: Evaluates task dependencies, allowing the DAG to continue even when previous tasks return `TaskStatus.FAILED`, ensuring all configured jobs in the sequence are attempted.

### 3.9 Token Cost Accounting & Metric Aggregation
At run completion, `aggregate_costs.py` executes a single-pass regex extraction across the master log file:
- **Cost Pattern**:
  ```python
  COST_PATTERN = re.compile(
      r"Tokens:\s*(?P<sent>[0-9.,]+[kM]?)\s*sent,\s*(?P<recv>[0-9.,]+[kM]?)\s*received(?:[.\s]*"
      r"Cost:\s*\$\s*(?P<msg>[0-9.,]+)\s*message,\s*\$\s*(?P<sess>[0-9.,]+)(?:\s*session)?)?",
      re.IGNORECASE,
  )
  ```
- **Metric Normalization**: Tokens with metric suffixes are converted:
  $$N_{\text{tokens}} = \begin{cases}
  \lfloor v \times 10^3 \rfloor & \text{if suffix is } \text{'k'} \\
  \lfloor v \times 10^6 \rfloor & \text{if suffix is } \text{'M'} \\
  \lfloor v \rfloor & \text{otherwise}
  \end{cases}$$
- **Total Run Cost**:
  $$C_{\text{total}} = \sum_{i=1}^{N_{\text{matches}}} c_{\text{msg}, i}$$
- **Reciprocal Rank Fusion (RRF)**:
  $$RRF(d) = \sum_{m \in M} \frac{1}{60 + r_m(d)}$$
  where $r_m(d)$ is the 0-indexed rank of candidate chunk $d$ in retrieval table $m$.
- **Ellipsis Stitch Gap Limit**: For deterministic verbatim repairs, fragments must resolve within:
  $$G_{\text{gap}} = (e_{\text{last}} - s_{\text{first}}) - \sum_{i=1}^{K} (e_i - s_i) \le 200 \text{ characters}$$

## 4. Exhaustive CLI & Parameter Reference

### 4.1 Master CLI Entry Points

| Command / Invocation | Target Alias | Exit Code | Runtime Behavior |
| -------------------- | ------------ | --------- | ---------------- |
| `aider-launcher [options] [session] [config.yml]` | Cross-Platform Launcher | Preserves exit code | Universal Python pipeline launcher (Linux, macOS, Windows). Spawns `run_workflow.py`, tees output to log file, and executes `aggregate_costs.py`. |
| `aider-factory [options] [session] [config.yml]` | Pipeline CLI | `0` on success, `1` on failure | Core orchestrator entry point. Parses YAML, initializes session directories, constructs DAG, and executes tasks. |
| `.aider_factory/bash/factory [session] [config.yml]` | Bash Wrapper | `0` on success, `1` on failure | POSIX convenience wrapper for Unix environments. |
| `aider-oracle [options] "<question>"` | Knowledge Oracle | `0` on success, `1` on failure | Standalone CLI and side-agent interface for LanceDB RAG retrieval, reranking, and multi-turn debate. |
| `aider-apply [files...] --spec <spec.md>` | Headless Applier | `0` on success, `1` on failure | Executes headless Aider code edit pass from markdown specifications and streams git diffs. |
| `aider-clean-lancedb <collection>` | RAG Cleanup | `0` on success, `1` on failure | Cross-platform cleanup of ephemeral OCR page images, validation logs, and debate artifacts. |
| `aider-helper query "<instruction>"` | Pipeline Helper | `0` on success, `1` on failure | Queries configuration or applies minimal-delta YAML updates using LLM assistance. |
| `python -m aider_factory.python.aggregate_costs <log>` | Cost Aggregator | `0` on success, `1` on failure | Parses log files to calculate token totals and USD run expenditure. |

### 4.2 Knowledge Oracle CLI Parameters (`aider-oracle`)

| Flag / Option | Argument | Description |
| :--- | :--- | :--- |
| `--debate [mode]` | `code` \| `review` | Runs multi-turn Architect-Oracle deliberation (default: `code`). |
| `--loops <N>` | Integer | Maximum turn loops per debate round (default: 3). |
| `--rounds <N>` | Integer | Maximum escalation debate rounds (default: 1). |
| `--persist` | None | Enables persistent audit exploration after provisional agreement. |
| `--oracle-persona <p>` | Path / Comma-separated | Injects markdown persona into Oracle system prompt and critique contract. |
| `--architect-persona <p>`| Path / Comma-separated | Injects markdown persona into Architect ask prompt. |
| `--oracle-file <p>` | Path / Comma-separated | Injects template/instructions directly to the Oracle. |
| `--architect-file <p>` | Path / Comma-separated | Injects template/instructions directly to the Architect. |
| `--collection <name>` | Name / Path | Targets specific LanceDB table or external corpus directory. |
| `--config <path>` | File Path | Explicit path to pipeline YAML configuration file. |
| `--type <code\|docs>` | `code` \| `docs` | Corpus type filter; restricts RRF search to code or documentation tables. |
| `--no-rag` | None | Bypasses vector retrieval; executes pure LLM reasoning. |
| `--no-rerank` | None | Disables cross-encoder reranking pass. |
| `--recall-k <N>` | Integer | Candidate retrieval depth before reranking (default: 75+). |
| `--claims-only` | None | Validates raw text paragraphs without requiring `[evidence]` tags. |
| `--reasoning-effort <e>` | `low` \| `medium` \| `high` | Sets reasoning effort for thinking models. |
| `--temperature <val>` | Float | Explicit sampling temperature override. |
| `--clear [oracle]` | None | Clears active Oracle and debate conversation history. |
| `--list` | None | Lists all LanceDB tables in the active database directory. |
| `--list-files` | None | Lists unique source files indexed in the collection. |
| `--add-file <paths...>` | File Paths | Incrementally ingests individual files into active collection. |
| `--add-table <dirs...>` | Directory Paths | Incrementally ingests directories into active collection. |
| `--add-web <urls...>` | URLs / File | Fetches and ingests web URLs, llms.txt, or sitemaps. |
| `--rm-table <name>` | Table Name | Drops a specific table from LanceDB. |
| `--rm-file <name>` | File Name | Surgically removes all chunks for a file across tables. |
| `--rm-db` | None | Wipes vector database directory for collection while preserving OCR cache. |

### 4.3 Structured Artifact Matrix

| Artifact | Path (relative to `.aider_factory/`) | Lifetime | Purpose |
| :--- | :--- | :--- | :--- |
| **Master Replay Log** | `logs/<config_stem>_run_<timestamp>.log` | Permanent | Byte-for-byte stream capture of stdout and stderr. |
| **Oracle Transcript** | `logs/oracle_history/<timestamp>_<task_id>.md` | Permanent | Complete record of Oracle queries, retrieved chunks, and answers. |
| **Chat Archive** | `logs/chat_history/<timestamp>_<task_id>.md` | Permanent | Archival copy of the Aider Architect/Editor conversation. |
| **Raw LLM History** | `logs/llm_history/<timestamp>_<task_id>.llm.log` | Permanent | Raw token-level LLM prompt and response traces. |
| **Debate Ledger** | `logs/debates/<stem>.debate.json` | Run / Phase | Machine-readable turn records, proposal hashes, and verdicts. |
| **Deliberation Verdict** | `logs/debates/<stem>.verdict.md` | Run / Phase | Structured verdict file gating downstream code edits. |
| **Oracle Cost Ledger** | `sessions/<slug>/.oracle_session.json.costs.json` | Session | Sidecar tracking cumulative Oracle session USD costs. |

## 5. Configuration Schema & YAML Knobs

```yaml
# ==============================================================================
# AI FACTORY PIPELINE CONFIGURATION SCHEMA
# ==============================================================================
name: "Production Pipeline"
working_directory: "."
loop_aider_test: 3
test_runner: "uv run --with pytest pytest {file}"
test_naming_and_path: "tests/test_{stem}.py"
test_command_prefix: ""
auto_lint: true
lint_cmd: null

endpoints:
  architect_api_base: "http://localhost:4000/v1"
  editor_api: "http://localhost:4000/v1"
  editor_api_fallback: "http://localhost:4000/v1"
  weak_model_api_base: "http://localhost:4000/v1"
  rag_agent_api: "http://localhost:4000/v1"
  grounding_agent_api: "http://localhost:8090/v1"
  ranking_api_base: "http://localhost:4000/v1"
  ocr_api_base: "http://localhost:8080"
  embed_api_base: "http://localhost:4000/v1"

models:
  architect_agent: "gemini/gemini-3.6-flash"
  editor_agent: "gemini/gemini-2.5-flash"
  editor_agent_test: "gemini/gemini-2.5-flash"
  editor_agent_test_fallback: "gemini/gemini-3.6-flash"
  weak_model: "gemini/gemini-2.5-flash"
  rag_agent: "gemini/gemini-2.5-flash"
  ranking_agent: "jinaai/jina-reranker-v3.5"
  embed_model: "gemini/text-embedding-004"
  ocr_agent: "gemini/gemini-2.5-flash"
  grounding_agent: "minicheck-flan-t5-large"
  reasoning_effort: "high"
  temperature: 0.2

colors:
  architect_debate: "#38bdf8"
  oracle_debate: "#d3869b"

phases:
  - name: "Core Phase"
    enabled: true

    toggles:
      run_job_one: true              # Stage 1: Initial implementation
      run_job_two: false             # Stage 2: Spec audit
      run_job_three: true            # Stage 3: Write tests
      iterate_test: true             # Stage 4: Test & self-healing loop
      auto_test: false               # Continuous test feedback per attempt
      pair_programming: false        # Interactive terminal PTY mode
      sticky_context: false          # Carry forward prior target files
      shared_history: false          # Isolate chat history per file stem
      yes_always: true               # Auto-confirm tool prompts
      auto_accept_architect: true    # Auto-accept architect proposals
      auto_commits: true             # Git commit on edit completion
      auto_lint: true                # Run linter after edits
      lint_cmd: null                 # Custom linter command
      suggest_shell_commands: false  # Propose shell commands in chat
      detect_urls: false             # Auto-scrape web links
      disable_playwright: true       # Bypass headless browser scraping
      map_tokens: 0                  # Repo map token budget
      map_refresh: "manual"          # Repo map refresh policy
      max_chat_history_tokens: 100000

    sticky_phases:
      editable: false                # Extract target files from strategy plan
      readonly: false                # Extract context files from strategy plan

    files:
      target_files:
        - "src/module.py"
      extra_editable_files: []
      test_files:
        - "tests/test_module.py"
      context_files_job:
        - "README.md"
      context_files_test:
        - "README.md"

    plans:
      job_one_plan: "src/aider_factory/markdown/templates/implement.md"
      job_two_plan: "src/aider_factory/markdown/templates/validate.md"
      job_three_plan: "src/aider_factory/markdown/templates/write_tests.md"
      iterate_plan: "src/aider_factory/markdown/internal/analyze_bugs.md"
      deliberate_plan: "src/aider_factory/markdown/internal/deliberation_evidence_template.md"
      apply_plan: "src/aider_factory/markdown/internal/apply_evidence_template.md"
      analyze_bugs_plan: "src/aider_factory/markdown/internal/analyze_bugs.md"
      validate_strategy_file: null

    oracle:
      start_job: false
      template: null
      full_document: true
      pre_edit_debate:
        enabled: true
        insert_debate: [1, 0, 1]     # Insert debates before Job 1 and Job 3
        loops: 3                     # Turn loops per pre-edit debate
        rounds: 1                    # Rounds per pre-edit debate
        pass_history: true           # Carry context across rounds
        persist: false               # Persistent exploration mode
        job_debate_template:
          - "src/aider_factory/markdown/internal/deliberation_evidence_template.md"
        job_debate_collection:
          - "knowledge"
        job_debate_db:
          - ""

    escalation_debate:
      loops: 3                       # Turns per escalation debate
      rounds: 2                      # Escalation debate cycles
      pass_history: true             # Carry context across rounds
      persist: false                 # Persistent exploration mode
      oracle_persona: ""             # Custom oracle persona markdown path
      architect_persona: ""          # Custom architect persona markdown path
      oracle_file: ""                # Custom oracle instruction file
      architect_file: ""             # Custom architect instruction file

    validation:
      enabled: false
      post_validate: false
      validation_tag: "evidence"
      region_threshold: 0.60
      region_margin: 2
      region_paragraphs: 0
      region_top_k: 5
      validation_loops: 3
      redo_oracle_job: false
      verify_all_claims: false
      entail_threshold: 0.5
      claims_only: false

    rag:
      run_ocr_rag: false
      collection_name: "knowledge"
      vectordb_overwrite: false
      batch: true
      chunk_size_chars: 1500
      chunk_overlap_chars: 300
      code_chunk_size: 2000
      type_filter: null              # "code" | "docs"
      retrieval_mode: "top_k"
      top_k: 5
      recall_k: 30
      use_docling: true
      docling_do_ocr: true
      docling_timeout: 120
```

### 5.1 Interactive PTY Capture (`pair_programming`)
When `pair_programming: true` is set, Aider requires a pseudo-terminal (PTY) to support `prompt_toolkit` key bindings and terminal formatting:
- **POSIX Execution**: The orchestrator wraps execution in `script`:
  ```bash
  script -qfe -c "aider --model gemini/gemini-3.6-flash ..." .pair_capture.log
  ```
- **macOS BSD Execution**:
  ```bash
  script -q .pair_capture.log /bin/bash -c "aider --model gemini/gemini-3.6-flash ..."
  ```
- **Windows Execution**: Uses standard process pipes teeing stdout into `.pair_capture.log`.
The capture file is parsed on task completion to extract token counts and USD costs into the session accounting ledger.

## 6. Telemetry, Diagnostics & Operational Edge Cases

| Edge Case / Failure Mode | Root Cause | System Mitigation & Telemetry |
| :--- | :--- | :--- |
| **C-Extension Segmentation Faults** | A compiled library (e.g. `pyarrow`, `lancedb`) crashes the Python process. | Captured by `OSTee`. Because file descriptors are redirected at the OS kernel level via `os.dup2`, the C stack trace is written to the master log file before process exit. |
| **`E2BIG` (Argument list too long)** | Massive source code or context passed as CLI arguments exceeds OS exec limits. | `orchestrate.py` and `oracle_agent.py` write large prompt payloads to temporary files (`.aider_ask_prompt_*.txt`, `.oracle_prompt_*.txt`) and pass them via `--message-file` or `--file`. |
| **Deadlock in Deliberation** | Architect and Oracle repeat identical positions without progress. | `deliberate.py` checks if the Architect's proposal hash $H(P_t) = H(P_{t-1})$ is unchanged across $\ge 2$ consecutive turns while the Oracle continues to object. Returns `deadlock`, halting the debate immediately to conserve tokens. |
| **Infinite Fix Oscillation** | An escalation debate repeats the exact same failed fix attempted in a prior round. | In multi-round debates (`rounds > 1`), `orchestrate.py` reads `prior_ledger` (`<stem>.job_debate_r1.json`), extracts the failed proposal from round $r-1$, and injects it into the round $r$ prompt with an explicit directive to avoid repeating that fix. |
| **Token Cost Regex Drift** | Changes in upstream LLM log formats break cost line parsing. | `aggregate_costs.py` employs an optional cost-group regex pattern. If cost tokens are missing, token counts are still extracted and unmatched lines default to `$0.00` without halting execution. |
| **Oracle Library Logging Noise** | Transformers, HuggingFace Hub, or HTTP warnings pollute stdout. | `oracle_agent.py` sets logging levels to `WARNING` or `ERROR`, wraps retrieval in `contextlib.redirect_stdout(sys.stderr)`, and prints only clean answers to `stdout`. |
| **Windows Stream Buffer Corruption** | Standard `os.dup2` calls corrupt buffered I/O streams on Windows. | `run_workflow.py` detects `sys.platform == "win32"` and activates `_TeeWriter` proxy wrappers around `sys.stdout` and `sys.stderr`, avoiding low-level descriptor redirection. |
| **Process Tree Hanging on Subprocess Timeout** | A sub-process spawns child processes that ignore parent signals. | `kill_proc_tree()` recursively terminates the entire process tree using `taskkill /F /T /PID` on Windows or `os.killpg(pgrp, SIGKILL)` on POSIX systems. |
| **Pipeline Halting on Task Failure** | A task fails and halts downstream dependency tasks. | `dependencies_met()` checks for `TaskStatus.SUCCESS` or `TaskStatus.FAILED`. If an unhandled failure halts the phase, the orchestrator logs the failed task IDs and halts with exit code 1 to protect state. |
| **Anchor Floor Drops in Evidence Validation** | An agent deletes or re-tags an ungrounded quote to pass tests. | `validator.py` checks anchor counts against `baseline_ledger`. If the count falls below the baseline set, it triggers a `floor_violation`, records `ANCHOR COUNT DROPPED`, and rejects the edit pass. |
