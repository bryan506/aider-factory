# AI Factory Engineering Backlog & Future Tasks

## 1. Instruction-Aware Reranker Prompt Customization (`ranking_prompt`)

### Status: Backlog / Future Enhancement
### Target Components: `oracle_agent.py`, `validator.py`, `.env.yml` schema

---

### Technical Context & Background
Instruction-tuned generative rerankers (such as `Qwen/Qwen3-Reranker-4B` and `Qwen/Qwen3-Reranker-8B`) support domain-specific task framing using the official prompt template:
```text
<Instruct>: {instruction}
<Query>: {query}
```

While standard plain queries achieve high discrimination (>0.99 relevance score) on properly converted GGUF files with `cls.output.weight`, specialized domains (e.g. biomedical citation matching, statutory legal analysis, complex financial covenants) can benefit from configurable instruction prefixes.

---

### Proposed YAML Schema Extension

```yaml
phases:
  - name: "Domain Analysis Phase"
    models:
      ranking_agent: "qwen3-reranker-4b-gpu:LATEST"
    rag:
      ranking_prompt: "Given a financial research query, retrieve relevant quantitative models and formulas that answer the question"
```

---

### Proposed Environment Variable & Execution Path
* `ORACLE_RANKING_INSTRUCT`: Default string prefix applied to queries when using instruction-aware rerankers.
* In `oracle_agent.py` and `validator.py`: If `ranking_prompt` is provided in the configuration or via `ORACLE_RANKING_INSTRUCT`, format the query string before sending the payload to `/v1/rerank` or the local CrossEncoder backend.

---

## 2. Temporal Reasoning, Point-in-Time Gating & Chronological RAG Ranking

### Status: Backlog / Future Architecture
### Target Components: `rag_manager.py`, `oracle_agent.py`, `validator.py`, `.env.yml` schema

---

### Technical Context & Background
Standard vector retrieval operates as a "bag-of-chunks" where passages are ordered purely by semantic similarity, discarding chronology. In high-stakes domains (quantitative finance, clinical records, and legal contracts), this causes **temporal scrambling** (e.g., lookahead bias in backtests, inverted pre-op vs. post-op causality, or citing superseded contract clauses).

Adding temporal awareness allows the Oracle to filter by historical horizons, apply time-decay weighting, and project retrieved context in causal order ($T_1 \to T_2 \to T_3$).

---

### Proposed Schema Extension (`RAGChunk` in `rag_manager.py`)

Extend `RAGChunk` to store extracted timestamps in LanceDB:

```python
class RAGChunk(LanceModel):
    text: str
    vector: Vector(_dim)
    source_file: str
    source_type: str
    language: str = ""
    symbol: str = ""
    line_start: int = 0
    line_end: int = 0
    timestamp: float = 0.0     # Unix epoch timestamp
    date_str: str = ""         # ISO-8601 string (e.g., "2024-05-12T14:30:00Z")
```

**Timestamp Extraction Waterfall:**
1. **Docling / Markdown Frontmatter:** Document publication date or ISO metadata header.
2. **Git Commit History:** `git log -1 --format="%ct" -- <file>`.
3. **Filesystem `mtime`:** `os.path.getmtime(file_path)` fallback.

---

### Proposed YAML Configuration Extension

```yaml
phases:
  - name: "Temporal Analysis Phase"
    rag:
      temporal:
        mode: "chronological"          # "none" | "chronological" | "time_decay" | "point_in_time"
        as_of_date: "2024-01-01"       # Point-in-Time (PIT) hard filter for quant backtests
        time_decay_half_life_days: 180 # Exponential decay half-life
```

---

### Proposed CLI Flags (`aider-oracle`)
* `--sort-time`: Re-orders final top-$K$ reranked chunks in ascending chronological order before prompt assembly.
* `--as-of <YYYY-MM-DD>`: Pushes a LanceDB Arrow filter (`where("timestamp <= ...")`) to eliminate lookahead bias.
* `--time-decay <half_life_days>`: Modulates relevance scores via $S_{final} = S_{semantic} \cdot e^{-\lambda \Delta t}$.

---

### Execution Pipeline in `oracle_agent.py`
1. **Stage 1 (Filter):** If `--as-of` is defined, apply native Arrow predicate to LanceDB KNN query.
2. **Stage 2 (Retrieve & Rerank):** Retrieve `recall_k` candidates and rerank using Jina v3.5 Listwise Cross-Encoder.
3. **Stage 3 (Decay, Optional):** Re-score candidates if `time_decay` is configured.
4. **Stage 4 (Chronological Context Projection):** Re-sort the final top-$K$ chunks by `timestamp` ascending ($T_1 \le T_2 \le \dots \le T_K$) and inject ISO timestamps into the `<chunk>` XML tags so LLM attention naturally follows temporal causality.

---

## 3. Automated `/clear` Vault Swap in Pair-Programming Sessions

### Status: Deferred — Manual Workflow Deemed Sufficient
### Target Components: `orchestrate.py` (pair branch), `run_workflow.py` (PTY launch), `cli.py`
### Prerequisite Reading: `session_management_and_cluster.md` §3 "Interactive Pair-Programming History Management"

---

### Why This Was Deferred

The manual epoch-clear workflow (move `.aider.chat.history.md` → `chat_history/.aider.chat.history_epoch_<ts>.md`, then `touch` a fresh file) takes under 20 seconds and is already documented. The user's shell alias (`af-clear-epoch`) eliminates even that friction.

Automating it requires intercepting `/clear` inside a PTY-wrapped aider process — a non-trivial control-flow insertion that introduces:

- A stdin multiplexing layer (user keystrokes vs. factory sentinel detection)
- A race condition between aider writing the cleared buffer and the factory reading/truncating the file
- A new failure mode: if the swap fails mid-PTY, aider's in-memory state and the on-disk file diverge
- A test matrix (PTY + vault + resume + shared_history toggle) for a 20-second operation

**Cost-benefit verdict:** The code-to-value ratio does not justify implementation today. Revisit only if pair-programming sessions grow to the point where manual clearing becomes a frequent (>3×/session) operational tax, or if a native aider `post_command` hook API becomes available (eliminating the PTY interception entirely).

---

### What a Clean Implementation Would Require

If a future contributor picks this up, the implementation **must** satisfy these constraints:

#### 1. Trigger Detection (Pick One Strategy)

| Strategy | Mechanism | Constraint |
| :--- | :--- | :--- |
| **A: Factory wrapper intercept** | Factory owns the PTY stdin pipe. Before forwarding bytes to aider, scan for a `/clear` line. If detected: forward `/clear\n` to aider, then perform swap_out + touch. | Requires factory to own the `script`/PTY process. Currently `run_workflow.py` launches aider via `script -q /dev/null`. The stdin pipe must be a factory-controlled `subprocess.Popen` stdin, not a raw TTY passthrough. |
| **B: Aider hook (future)** | Register a `post_command` hook in `.aider.conf.yml` that fires a factory callback on `/clear`. | Requires aider ≥ a version supporting `--post-command-hook`. Does not exist today. |
| **C: File-watch sentinel** | Factory polls `.aider.chat.history.md` for a zero-byte or marker-write indicating `/clear` occurred. | Fragile; aider does not write a sentinel marker on `/clear`. Not recommended. |

**Recommended:** Strategy A. It is deterministic, requires no aider modification, and aligns with the existing PTY ownership model.

#### 2. Vault Swap Execution

Reuse the existing `_swap_out_state(stem)` method in `orchestrate.py`. The stem should be:

```python
stem = f"epoch_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
```

This produces vault files like `chat_history/.aider.chat.history_epoch_20250614T120000.md`, consistent with the existing naming convention.

#### 3. Fail-Closed Semantics

```python
# Pseudocode in the PTY stdin wrapper
if detected_clear_command:
    aider_proc.stdin.write(b"/clear\n")
    aider_proc.stdin.flush()
    try:
        factory._swap_out_state(stem)
    except Exception:
        # Do NOT touch a new file if swap failed.
        # Aider's in-memory buffer is already cleared; the on-disk file
        # is stale but harmless (next turn will reload it, which is the
        # pre-fix behavior — no worse than not implementing this feature).
        log.error("Epoch swap failed; history file unchanged.")
        return
    # Only create fresh file on success
    Path(active_hist).touch()
    log.info(f"✓ Epoch archived: {stem}")
```

#### 4. Isolation Gate

The feature **must** be gated behind a discriminator so legacy pair-programming paths are provably untouched:

```yaml
toggles:
  pair_programming: true
  pair_clear_vault_swap: true   # NEW — defaults to false
```

If `pair_clear_vault_swap` is `false` (default), the factory does **not** intercept `/clear` and aider handles it natively (current behavior). Zero blast radius.

#### 5. Required Test Matrix

| Test | Assertion |
| :--- | :--- |
| `/clear` typed → vault file created with timestamp stem | File exists, content matches pre-clear history byte-for-byte |
| `/clear` typed → fresh active file created | `.aider.chat.history.md` exists and is empty (0 bytes) |
| `/clear` typed → aider in-memory buffer cleared | Next aider turn produces no reference to prior conversation |
| `pair_clear_vault_swap: false` → `/clear` typed | No vault file created; aider handles natively (legacy parity) |
| Swap failure (vault dir unwritable) | Fail-closed: no touch, no crash, error logged |
| Multiple `/clear` in same session | Multiple distinct epoch files in vault; each unique timestamp |
| Resume session after epoch clear | `--restore-chat-history` reads the fresh (empty) file; no stale context |

#### 6. Files to Modify

| File | Change |
| :--- | :--- |
| `orchestrate.py` | Add `pair_clear_vault_swap` field to `Task` dataclass; add interception logic in the pair-programming branch of `_execute_task_node` |
| `run_workflow.py` | Ensure PTY stdin is a factory-controlled pipe (not raw TTY) when `pair_clear_vault_swap: true` |
| `session_management_and_cluster.md` | Update the "When Automation Already Handles This" table to flip the ❌ to ✅ when implemented |
| New test file | `test_e2e_pair_clear_vault_swap.py` covering the matrix above |

---

### Decision Log

> **2025-06-14:** Feature scoped and deliberately deferred. Manual `af-clear-epoch` alias provides equivalent outcome in <20s. Implementation cost (PTY stdin multiplexing, race-condition handling, 7-case test matrix) is disproportionate to the ergonomic benefit. Re-evaluate if aider ships a native `post_command` hook or if pair-programming sessions exceed ~50 turns requiring multiple mid-session resets.
