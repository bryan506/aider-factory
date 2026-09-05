# Autonomous Context Engineering Audit & Document Optimization Playbook

> **Mission Objective:** Systematically audit, refine, and synthesize project conventions, system prompts, and operational playbooks against an authoritative Context Engineering knowledge base (e.g., via a RAG Oracle). Ensure maximum model compliance, KV-cache prefix stability, positional attention optimization, and zero token bloat.

---

## 0. Workflow Overview & Gated Lifecycle

```
[Phase 1: Query Formulation]
       │
       ▼
[Phase 2: RAG Knowledge Retrieval]
       │
       ▼
[Phase 3: Gap Analysis & Spec Drafting] (Architect)
       │
       ▼
[Phase 4: Oracle Pre-Implementation Audit] (Validator Gate) ───[Rejected]──┐
       │                                                                  │ (Revise Spec)
       ▼ [Approved]                                                       │
[Phase 5: Surgical Implementation] (Editor) <─────────────────────────────┘
       │
       ▼
[Phase 6: Synthesis & Reconciliation] (Optional Consolidation)
       │
       ▼
[Phase 7: Final Verification & Cross-Validation]
```

---

## Phase 1: Targeted Query Formulation (Retrieval Engineering)

Before querying the RAG knowledge base, formulate targeted, high-density queries. Avoid vague questions like _"how to improve prompts"_. Instead, query across these core context engineering dimensions:

### Query Matrix Template

1. **KV-Cache Optimization & Prefix Stability:**

   > `"Prompt engineering patterns for KV-cache optimization immutable static system prefixes append-only dynamic context and deterministic serialization to maximize cache hits."`

2. **Positional Attention & Lost-in-the-Middle Mitigation:**

   > `"Instruction position and attention distribution: mitigating primacy, recency, and 'lost-in-the-middle' effects in long context system instructions."`

3. **Multi-Persona Role Isolation & State Hand-Offs:**

   > `"Preventing role bleed and instruction leakage in multi-persona prompts: separating planning, implementation, validation, and testing contexts."`

4. **Negative Constraints vs. Affirmative Boundaries:**

   > `"Empirical compliance rates of negative constraints (NEVER, DO NOT) versus affirmative operational boundaries in transformer attention."`

5. **Self-Healing Error Feedback & Anti-Oscillation:**

   > `"Self-healing error feedback loops, compiler diagnostic injection, and prompt pruning to prevent infinite loop oscillation."`

6. **Context Window Budgeting & The Sentinel Invariant:**
   > `"Active context window utilization degradation thresholds (70% rule), dynamic token budgeting, and preserving protected sentinel sets during compaction."`

---

## Phase 2: RAG Knowledge Retrieval

Execute the formulated queries against the vector knowledge base using hybrid retrieval (dense semantic search + lexical BM25/reranking).

```bash
# Example Oracle Execution
aider-oracle --collection <COLLECTION_PATH> "<TARGET_QUERY>"
```

**Extraction Checklist from Oracle Output:**

- [ ] Empirical utilization bounds (e.g., 70% threshold).
- [ ] Required prompt topology (Primacy $\to$ Middle $\to$ Recency).
- [ ] Schema enforcement contracts and AST anchor rules.
- [ ] Concrete negative-to-affirmative replacement patterns.

---

## Phase 3: Gap Analysis & Spec Drafting (Architect Role)

Audit the target document against the retrieved textbook principles. Identify anti-patterns and draft the improvement blueprint.

### Document Audit Checklist

1. **Primacy Check**: Are immutable invariants, role boundaries, and security rules at the very top?
2. **Recency Check**: Are output schemas, response templates, and completion checklists locked at the terminal position?
3. **Negative Constraint Check**: Is every "DO NOT" paired with an affirmative replacement (e.g., replace deleted lines with `# Removed`)?
4. **Generalization Check**: Is the document free from domain lock-in (unless domain-specific logic is explicitly requested)?
5. **Syntactic Anchor Check**: Are markdown headers rigid and deterministic for regex/AST parsers?
6. **Token Hygiene Check**: Are orphaned sections, conversational filler, and redundant explanations stripped out?

### Required Output of Phase 3:

Draft a complete Markdown proposal with a clear diff summary and rationale grounded in Oracle citations.

---

## Phase 4: Oracle Pre-Implementation Audit (Validator Gate)

**HARD GATE:** Before applying modifications to files, pass the proposed draft back to the Oracle for formal verification.

```bash
aider-oracle --collection <COLLECTION_PATH> --file <SCRATCHPAD_DRAFT> \
  "Audit this agent's proposed improvements against the context engineering corpus. Verify compliance with primacy/recency placement, affirmative constraints, and schema determinism."
```

- **If Rejected:** Return to Phase 3, address specific Oracle critiques, and re-audit.
- **If Approved (`Verdict: YES`):** Proceed to Phase 5.

---

## Phase 5: Surgical Implementation (Editor Role)

Apply the approved changes to the target files adhering strictly to the **Minimal-Delta Invariant**:

- **No Premature Editing:** Only modify files explicitly declared in the scope analysis.
- **Empty Search Invariant:** When creating or wiping a file, ensure search blocks are empty.
- **Affirmative Comment Invariant:** When deleting code or instructions, replace them with an explicit comment (`# Removed` / `// Removed`).
- **No Unresolved Placeholders:** Ensure syntax examples contain zero `TODO`, `NULL`, `None`, or `"if needed"` placeholders.

---

## Phase 6: Synthesis & Reconciliation (Optional Consolidation)

When two or more related instruction documents exist (e.g., a conventions file and an execution playbook):

1. **Extract Unique Strengths:** Merge structural schema anchors from the conventions file with operational lifecycle gates from the playbook.
2. **Eliminate Cross-File Redundancy:** Consolidate shared concepts (Pillars, Invariants, Verification Matrices) into a single authoritative file (e.g., `CONVENTIONS_REVISED.md`).
3. **Preserve High Information Density:** Ensure the reconciled file is shorter in line count but denser in actionable constraints than the sum of its source files.

---

## Phase 7: Final Verification & Close-Out

Run the final verification matrix before closing the task:

| Step                   | Verification Criteria                                                              | Status |
| :--------------------- | :--------------------------------------------------------------------------------- | :----- |
| **1. Parse Check**     | Regex and AST anchors (`## Scope Analysis`, `### [Task ID: ...]`) extract cleanly. | [ ]    |
| **2. Prefix Parity**   | System prompt prefix is 100% static and byte-invariant for KV-cache reuse.         | [ ]    |
| **3. Recency Check**   | File terminates with an actionable markdown task checklist (`- [ ]`).              | [ ]    |
| **4. Zero Bloat**      | Redundant prose eliminated; high token-to-information ratio achieved.              | [ ]    |
| **5. Oracle Sign-off** | Final document verified as fully compliant with context engineering corpus.        | [ ]    |

---

## Section 8: Empirical Findings — Chat History Summarization Across Aider Modes

> **Date**: 2025-09-04 | **Aider version**: aider-chat (latest via uv) | **Test models**: Cloud `gemini/` for main/editor; local `qwen3.8-27B-90k-udq4km` (llama.cpp via LM Studio) as `weak-model` for summarization.  
> **Test artifacts**: `src/aider_factory/tests/aider_factory_tests/end-to-end/test_e2e_max_chat_history_tokens.py`, `test_e2e_architect_summarization.py`  
> **Observation method**: Live llama.cpp inference logs (`journalctl -u llama-server`), aider `--verbose` output, `/tokens` snapshots.  
> **Status**: All tests pass. These are the first known public E2E probes of aider's summarization trigger mechanics per-mode.

---

### 8.1 Per-Mode Summarization Behavior Matrix

| Trigger | Coder Mode (`--code`) | Architect Mode (`--architect`) | Evidence |
|:---|:---|:---|:---|
| `/clear` command | ✅ Summarizes via weak model | ✅ Summarizes via weak model | llama.cpp: LRU slot, 18,548 prompt → 819 gen tokens |
| `max-chat-history-tokens` threshold | ✅ Fires (confirmed in prior suite) | ❌ **Does NOT fire** at 40k | Live session: 64,432 chat history with 40k threshold set; no summarization until manual `/clear` |
| `--message --exit` (non-interactive) | ⚠️ Asyncio shutdown race | ⚠️ Asyncio shutdown race | `cannot schedule new futures after shutdown` in stderr; summarization never completes |
| `--architect` two-phase (architect→editor) | N/A | ❌ Threshold check appears to guard only one phase | Architect path accumulates unchecked; editor path may be the only guarded path |

---

### 8.2 The 440-Token vs 18,548-Token Distinction

**Critical finding**: In architect mode with no commits and a cloud main model, every llama.cpp inference is the weak model. However, not all weak-model calls are summarization.

| Signal | 440-token calls (×5, pre-`/clear`) | 18,548-token call (post-`/clear`) |
|:---|:---|:---|
| Slot selection | LCP (`f_sim_best = 1.000`) | **LRU** (zero cache reuse) |
| Prompt eval | 4 tokens / 140ms | 18,548 tokens / 27.7s |
| Generation | 198 tokens / 1.7s | 819 tokens / 31.9s |
| Total | 202 tokens / 1.9s | 19,371 tokens / 60.5s |
| Graphs reused | +9 per turn (incremental) | +234 (fresh allocation) |
| Draft acceptance | 0.856 (template-fitting) | 0.740 (novel content) |
| **Classification** | Fixed-template probe / token-count check | **Genuine summarization** |

**Interpretation**: The 440-token calls are aider's internal weak-model probe (likely a token-counting or health-check invocation with a static prompt template). They do NOT represent summarization of conversation content. The 18,548-token call is the first and only real summarization, triggered exclusively by `/clear`.

---

### 8.3 The `/clear` → 24k Token Math (Live Session Verification)

```
Before /clear:
  Chat history:  64,432 tokens
  File context:  20,013 tokens (6 read-only files)
  Total sent:    84,445 tokens
  ERROR: 97,723 > 90,112 (model context window)

After /clear + next prompt + response:
  Chat history:  24,918 tokens
  File context:  20,013 tokens (unchanged)
  Total sent:    44,931 tokens
```

**Breakdown of 24,918 chat history post-clear**:
- Weak model summary of 64k history: ~2,000–3,000 tokens
- New user prompt (pasted logs + question): ~19,000–20,000 tokens
- Assistant response: ~2,200 tokens
- **Total: ~24,918** ✅ Math verified.

The 44k "sent" includes the 20k read-only file context that is **always** in the window (system prompt + file contents). This is not "chat history" and is not affected by `/clear`.

---

### 8.4 The `--message --exit` Asyncio Race (DISPROVEN as viable test path)

**Finding**: Running aider with `--message "prompt" --exit` in architect mode produces:

```
RuntimeError: cannot schedule new futures after shutdown
```

The summarization coroutine is scheduled but the event loop tears down before it completes. This makes `--message --exit` **unusable** for testing summarization behavior. Only interactive stdin-driven sessions (or PTY via `script -qfe`) allow the summarization coroutine to complete.

**Status**: DISPROVEN as a test vector. Use interactive mode with threaded stdin feeder instead.

---

### 8.5 The Observability Gap

**Finding**: In interactive architect mode, aider does NOT log to stdout/stderr when:
- The threshold is evaluated
- The weak model is invoked for summarization
- Summarization completes or is skipped

The only observable signal is the llama.cpp inference log on the server side. Aider's `--verbose` flag logs token counts but does not explicitly state "summarization triggered" or "threshold crossed." This makes black-box testing of the threshold mechanism extremely difficult without server-side inference telemetry.

**Workaround**: Monitor `journalctl -u llama-server` or the LM Studio console for LRU-selected large-token inferences as the definitive proof of summarization.

---

### 8.6 Threshold Propagation Chain (UNCONFIRMED — Requires `--verbose` Verification)

The `max_chat_history_tokens` value must survive this chain to reach aider's internal check:

```
env.yml (toggles.max_chat_history_tokens: 40000)
    → run_workflow.py (_parse_toggles, Task dataclass)
        → orchestrate.py (_aider_ask_turn, CLI arg construction)
            → --max-chat-history-tokens 40000 (subprocess arg)
                → aider internal ChatSummary.check()
```

**Unverified**: Whether the value actually arrives at aider's threshold check in architect mode, or whether architect mode's two-phase request structure (architect call + editor call) causes the threshold to be evaluated against only one phase's history while the other phase accumulates unchecked.

**Next diagnostic**: Launch session with `--verbose`, run `/tokens` every turn, and grep aider's stderr for any mention of `max_chat_history_tokens` or `summariz`.

---

### 8.7 Confirmed Root Cause of Live Session Context Overflow

| Factor | Value | Impact |
|:---|:---|:---|
| Model context window | 90,112 tokens | Hard ceiling |
| Read-only file context | ~20,000 tokens | Always present, not summarizable |
| Effective conversation budget | ~70,000 tokens | Remaining for chat history + generation |
| `max_chat_history_tokens` (set) | 40,000 | Should trigger at 40k |
| Actual chat history at crash | 64,432 | **24k past threshold** |
| Auto-summarization fired? | **No** | Threshold mechanism bypassed |

**Conclusion**: The threshold was correctly configured at 40k but was never enforced by aider's runtime in architect mode. The conversation grew to 64k+ without triggering auto-summarization, eventually exceeding the model's 90k hard limit when combined with file context and the current request payload. Manual `/clear` is the only working mitigation until the threshold mechanism is verified/fixed.

---

### 8.8 Recommended Configuration for Architect-Mode Sessions

```yaml
# .aider_factory/.env.yml — phase toggles
toggles:
  max_chat_history_tokens: 40000   # Must be < (model_window - file_context - generation_headroom)
                                   # For 90k window: 90112 - 20000 - 5000 = 65112 max safe
                                   # Set to 40000 for conservative margin

# .aider_factory/.aider.conf.yml
max-chat-history-tokens: 40000     # Belt-and-suspenders: also set in aider's native config
weak-model: "openai/qwen3.8-27B-90k-udq4km"  # Must be routable for summarization
```

**Operational rule**: In architect mode, treat `/clear` as a mandatory periodic maintenance command. Do not rely on threshold auto-summarization until confirmed working via `--verbose` telemetry.

---

### 8.9 Test Artifacts (Permanent Regression Suite)

| Test File | Status | Proves |
|:---|:---|:---|
| `test_e2e_max_chat_history_tokens.py` | ✅ Passes | `/clear` triggers summarization in coder mode; `--message --exit` fails with asyncio race |
| `test_e2e_architect_summarization.py` | ✅ Passes | `/clear` triggers summarization in architect mode; threshold does NOT auto-fire; 440-token calls are not summarization |

These tests require a running local model server (LM Studio / llama.cpp) as the weak model and a cloud API for the main model. They are **not** mock-based; they assert against real OS exit codes and live llama.cpp inference telemetry.

---
