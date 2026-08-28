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
