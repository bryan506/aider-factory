# Pipeline DAG & Autonomous Debates

## 1. Executive Overview & Foundational Invariants

The AI Factory orchestrates an industrial-grade, 4-stage software engineering Directed Acyclic Graph (DAG) via `run_workflow.py` and `orchestrate.py`. It integrates granular pre-edit debate insertion, dynamic strategy injection, and OS-level stream multiplexing to ensure deterministic, reproducible, and fully observable autonomous execution.

**Foundational Invariants:**
- **Deterministic-First Execution:** The pipeline relies on strict exit codes and deterministic text hashing before engaging LLM judgment.
- **Zero-Loss Observability:** All sub-agent and subprocess streams are intercepted at the OS file-descriptor level.
- **Stateless Node Execution:** Each DAG node reads its inputs from disk, allowing phases to be split, skipped, or combined without context loss.
- **Three-Tier Observability:** Every execution is preserved across three synchronized tiers: (1) Live interactive ANSI streaming, (2) Master terminal recording logs, and (3) Structured disk artifacts.
- **Deterministic Financial Accounting:** Every token sent and received is parsed, aggregated, and logged into a USD cost ledger.

## 2. System Topology & Lifecycle Flowcharts

The pipeline divides software development into four discrete, testable nodes, with optional Oracle consultation inserted at specific boundaries.

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   THE 4-STAGE AUTONOMOUS DAG                                    │
├───────────────────┬───────────────────┬─────────────────────────┬───────────────────────────────┤
│ STAGE 1:          │ STAGE 2:          │ STAGE 3:                │ STAGE 4:                      │
│ Implementation    │ Spec Audit        │ Write Tests             │ Self-Healing Loop             │
│ (`run_job_one`)   │ (`run_job_two`)   │ (`run_job_three`)       │ (`iterate_test`)              │
├───────────────────┼───────────────────┼─────────────────────────┼───────────────────────────────┤
│ • Architect plans │ • Senior reviewer │ • Writes unit tests for │ • Re-runs test suite          │
│ • Editor writes   │   spec audit      │   new implementation    │ • Captures failure logs       │
│   initial code    │ • Strategy-locked │ • Broad-scope coverage  │ • Auto-fixes code in a loop   │
│ • Pre-Debate: J1  │ • Pre-Debate: J2  │ • Pre-Debate: J3        │ • Escalation Debate           │
└───────────────────┴───────────────────┴─────────────────────────┴───────────────────────────────┘
```

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
Before modifying files in Job 1, Job 2, or Job 3, the Architect can consult the Knowledge Oracle.
- **3-Tuple Normalization (`_parse_insert_debate`)**: Converts inputs (e.g., `[1, 0, 1]` or `"1, 0, 0"`) into a strict boolean tuple `(bool(j1), bool(j2), bool(j3))`.
- **Template Routing (`_resolve_job_debate_template`)**: Index-matches the active job number to the template list, falling back to index 0 if the list is shorter than the job index.
- **Collection Routing (`_resolve_job_debate_collection`)**: Points each debate turn at a dedicated LanceDB collection directory, falling back to the phase's default collection.

### 3.2 Dynamic Strategy Injection (`_render_validate_template`)
When transitioning from Phase 0 (Planning) to Phase 1 (Execution), `_render_validate_template()` ensures the senior code reviewer in Job 2 audits code against exact specifications:
1. Discovers `strategy_template.md` (or completed markdown outputs from prior phases).
2. Reads the default audit template (`markdown/templates/validate.md`).
3. Injects the strategy text directly into the `## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS` placeholder via regex substitution.
4. Saves the rendered template to `.aider_factory/temp/<stem>_validate_rendered.md` for execution.

### 3.3 Multi-Round Escalation Reflexion (`escalation_debate`)
If the test suite fails during Stage 4 (`iterate_test`), the orchestrator triggers an escalation debate:
- **Debate Rounds (`rounds`)**: Chained full debate cycles (Debate $\to$ Apply $\to$ Re-Test).
- **Cross-Round Memory (`pass_round_history`)**: Carries prior turn context and model KV caches across rounds.
- **Ledger Chaining**: Passes `<stem>.job_verdict_r1.md` and `<stem>.job_debate_r1.json` to Round 2. The orchestrator explicitly parses the `prior_ledger` to extract the exact failed proposal from the previous round and injects it into the new prompt, giving the model memory of its past attempts to prevent infinite loops of identical fixes.

### 3.4 OS-Level File Descriptor Multiplexing (`OSTee`)
Standard Python logging drops subprocess stdout/stderr. `run_workflow.py` wraps execution in `OSTee`:
```python
self.orig_stdout_fd = os.dup(1)
self.orig_stderr_fd = os.dup(2)
self.pipe_r, self.pipe_w = os.pipe()
os.dup2(self.pipe_w, 1)
os.dup2(self.pipe_w, 2)
```
A background daemon thread drains the pipe to the real terminal while recording an unbuffered, timestamped log file.

### 3.5 Token & Cost Extraction Regex
At the conclusion of a run, `aggregate_costs.py` parses the master log file using a strict regular expression to extract token counts and USD costs from LiteLLM/Aider output lines. Tokens with metric suffixes (`k`, `M`) are mathematically expanded.

### 3.6 Vector Database & Chunking Telemetry
During document and codebase ingestion, `rag_manager.py` emits continuous diagnostic traces captured by the master log:
- **AST Symbol Resolution:** Logs Tree-Sitter grammar parsing, function/class structural boundaries, and oversized leaf fallback line splits.
- **Docling Extraction Traces:** Logs isolated subprocess status, structural metadata headers, and table extraction boundaries.
- **Vector Transformation:** Logs embedding model calls, endpoint URLs, batch sizes, and returned vector dimensions.
- **Table Construction & Indexing:** Logs table creation, row counts, and automatic `IVF_PQ` Approximate Nearest Neighbor (ANN) index builds.
- **Retrieval Attribution:** Oracle queries log exact chunk IDs, cosine similarities, Reciprocal Rank Fusion (RRF) scores, and unique source file headers to `stderr`.

## 4. Exhaustive CLI & Parameter Reference

| Command / Invocation | Target Alias | Exit Code | Runtime Behavior |
| -------------------- | ------------ | --------- | ---------------- |
| `.aider_factory/bash/factory .env.yml` | Pipeline Launcher | `0` on success, `1` on failure | Parses the YAML, builds the DAG, and executes all enabled phases sequentially. Wraps execution in `OSTee`. |
| `.aider_factory/bash/oracle --debate code --loops 3 "query"` | CLI Debate | `0` | Launches an interactive, multi-turn debate between the Architect and Oracle. |
| `aider-helper query "instruction"` | Config Helper | `0` | Modifies the active pipeline configuration using minimal-delta edits. |
| `uv run src/aider_factory/python/aggregate_costs.py <log_file>` | Cost Aggregation | `0` | Manually parse a master log file and print the total USD cost and token counts. |
| `less -R <log_file>` | Log Replay | `0` | Replay a master log file preserving ANSI color codes. |

### 4.1 Structured Artifact Matrix
| Artifact | Path (relative to `.aider_factory/`) | Purpose |
| :--- | :--- | :--- |
| **Master Replay Log** | `logs/<config_stem>_run_<timestamp>.log` | Byte-for-byte capture of the entire execution. |
| **Oracle Transcript** | `logs/oracle_history/<timestamp>_<task_id>.md` | Oracle Q&A including raw retrieved LanceDB chunks. |
| **Chat Archive** | `logs/chat_history/<timestamp>_<task_id>.md` | Timestamped copy of the Aider Architect/Editor conversation. |
| **Debate Ledger** | `logs/debates/<stem>.debate.json` | Machine-readable turn state and quote baselines. |
| **Oracle Cost Ledger** | `sessions/<slug>/.oracle_session.json.costs.json` | Sidecar tracking cumulative Oracle session USD costs. |

## 5. Configuration Schema & YAML Knobs

```yaml
oracle:
  pre_edit_debate:
    enabled: true
    insert_debate: [1, 0, 0]      # [Job 1: Implement, Job 2: Audit, Job 3: Write Tests]
    loops: 3                      # Debate turns per job
    job_debate_template:          # Specialized template(s)
      - "src/aider_factory/markdown/oracle_pre_plan/strategy_instruct_template.md"
      - "src/aider_factory/markdown/internal/analyze_bugs.md"
    job_debate_collection:        # Specialized vector collection(s)
      - "project_docs"
      - "project_specs"

escalation_debate:
  loops: 4                        # Max architect/oracle turns per debate
  rounds: 2                       # Escalation cycles after test-fix loop exhausts
  pass_history: true              # Persist context across rounds
```

### 5.1 Interactive PTY Capture (`pair_programming`)
When `pair_programming: true` is set in the `.env.yml` toggles, Aider requires a pseudo-terminal (PTY) to support `prompt_toolkit` interactivity. To solve this, the orchestrator wraps Aider in the UNIX `script` utility:

```yaml
phases:
  - name: "Interactive Research"
    toggles:
      pair_programming: true  # Triggers PTY wrapping
```

**Under the hood execution:**
```bash
script -qfe -c "aider --model gemini/gemini-3.6-flash ..." .pair_capture.log
```
This creates a real PTY for Aider while flushing all output to `.pair_capture.log`, which is subsequently absorbed by `OSTee` and the cost aggregator.

## 6. Telemetry, Diagnostics & Operational Edge Cases

| Edge Case / Failure Mode | Root Cause | System Mitigation & Telemetry |
| :--- | :--- | :--- |
| **C-Extension Segmentation Faults** | A lower-level library (e.g., `pyarrow`, `lancedb`) crashes the Python process. | Captured safely by `OSTee`. Because `os.dup2` wires the file descriptors at the kernel level, the segfault trace is successfully written to the master log before the process dies. |
| **Unparseable Cost Lines** | Aider or LiteLLM changes its token output format, breaking `COST_PATTERN`. | `aggregate_costs.py` defaults to `0.0` for unmatched lines. The pipeline continues execution uninterrupted; only the final cost summary is affected. |
| **`E2BIG` (Argument list too long)** | Passing massive code contexts to the Oracle via CLI arguments exceeds Linux kernel buffer limits. | The Orchestrator writes debate prompts to temporary files (`.oracle_prompt_<tmp>.txt`) and executes Oracle calls via `--file <tmp_file>`, bypassing OS limits. |
| **Missing Oracle Telemetry** | Oracle library noise (model loading, HTTP warnings) pollutes the Aider chat. | `oracle_agent.py` forces all telemetry, RAG chunk counts, and cost lines to `sys.stderr`. Only the pure answer is printed to `sys.stdout` for Aider to consume. |
| **Loop Exhaustion** | Stage 4 (`iterate_test`) exhausts its `max_aider_loops` without the test suite passing. | Triggers the escalation debate. If the debate also exhausts its rounds, the task is marked as `FAILED` (or `soft_fail` in review mode). |
| **Deadlock Detection** | The Architect repeats the exact same proposal hash across $\ge 2$ consecutive turns and the Oracle still objects. | The debate state becomes `deadlock` and halts early to save compute. |
