# `aider-oracle-debate` — Adversarial Deliberation, Trinary Arbitration & Specification Formulation

## 1. Executive Overview & Architectural Philosophy

The deliberation subsystem (`aider-oracle --debate`) resolves premature agreement and hallucinated plans by decoupling:
1. **Generation (LLM Agents)**: The Oracle (domain expert/verifier via LiteLLM) and the Architect (code planner via Aider) debate from asymmetric personas.
2. **Arbitration (Deterministic Python Code)**: A zero-LLM referee (`deliberate.py`) evaluates pure string tokens, hashes proposals, detects deadlocks, and enforces state machine rules.

### Core Architectural Invariants

- **Deterministic-First Authority**: Termination is governed exclusively by deterministic token matching (`oracle_verdict`) and hash comparison (`proposal_hash`). An LLM cannot self-certify its proposal.
- **Strict State Isolation & Zero Blast Radius**: Deliberations run in Aider Ask mode (`--edit-format ask`). No code edits or git commits are made during deliberation.
- **High-Watermark Plan Retention (`deliberate.update_high_watermark_proposal`)**: Compares discrete task counts (`### [Task ID:`) across turns. If turn $N$ outputs fewer tasks than turn $N-1$ (e.g. closing delta chatter), the engine preserves the comprehensive turn $N-1$ plan.
- **The Cumulative Plan Invariant (Invariant 6)**: Architect instruction templates strictly mandate that every plan turn must be cumulative and exhaustive—never delta-only fragments.
- **3-Tier Fallthrough Proposal Sanitizer (`deliberate.sanitize_proposal_text`)**:
  - Tier 1: Anchors to earliest recognized section header (`## Scope Analysis`, `## Implementation Plan`, `### [Task ID:`, etc.).
  - Tier 2: Strips leading Aider startup noise (`chat (read-only)...`, `► THINKING`).
  - Tier 3: Zero-drop safety net returning raw text if candidate is empty.
- **The `draft` Gate Token & Autonomous Fail-Safe**:
  - Pre-edit debates run with `draft_mode: True`. `write_verdict` writes `GATE: draft`.
  - `verdict_is_actionable()` returns `True` iff `STATUS: agreed` and `GATE: draft`.
  - If a pre-edit debate terminates in `deadlock` or `exhausted`, `orchestrate.py` logs `⏸️ HELD FOR HUMAN` and halts the downstream editing task.
- **Deterministic Timestamped Stems & Full Artifact Parity**:
  - Stems follow `<target>_<session>_<YYYYMMDD_HHMMSS>` for pipeline runs and `<stem>_<YYYYMMDD_HHMMSS>` for CLI debates.
  - Every debate round writes `<stem>.verdict{r_suf}.md`, `<stem>.debate{r_suf}.md`, and `<stem>.debate{r_suf}.json` into `.aider_factory/logs/debates/`.
  - Chat history is isolated to `.aider_factory/.debate_aider_history_<stem>.md` during execution, then permanently archived to `.aider_factory/logs/chat_history/<stem>_<timestamp>_debate_history.md`.

---

## 2. System Topology & Deliberation Lifecycle

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              ADVERSARIAL DEBATE TOPOLOGY                               │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│  [User Query / Issue] ──► [Turn 0: Oracle Pre-Assessment (System Primacy: CONVENTIONS)]│
│                                       │                                                │
│         ┌─────────────────────────────┴─────────────────────────────┐                  │
│         ▼                                                           ▼                  │
│  ┌──────────────┐             [Turn Telemetry Banner]        ┌─────────────┐           │
│  │  Architect   │ ◄─── [DEBATE STATUS: Turn X/Y (Round R/N)] ──► │   Oracle    │           │
│  │ (Aider Ask)  │                                            │  (LiteLLM)  │           │
│  └──────┬───────┘                                            └──────┬──────┘           │
│         │ PROPOSAL: <one-line summary>                              │                  │
│         ▼                                                           ▼                  │
│    proposal_hash()                                            oracle_verdict()         │
│         │                                                           │                  │
│         └─────────────────────────────┬─────────────────────────────┘                  │
│                                       ▼                                                │
│                         [deliberate.consensus_state()]                                 │
│                                       │                                                │
│               ┌───────────────────────┼───────────────────────┐                        │
│               ▼                       ▼                       ▼                        │
│           "agreed"                "continue"              "deadlock"                   │
│              │                        │                       │                        │
│       Is persist=True                 │                Halt loop immediately;          │
│       and Turn < Max?                 │                Actionable = False              │
│         ┌────┴────┐                   │                                                │
│        YES        NO                  │                                                │
│         │          │                  │                                                │
│  Rotate prompt     └─────────► Advance to Round R+1 or Merge;                          │
│ (Next Audit Tier)               Actionable = True                                      │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Two-Round Divergence & Convergence Protocol

When running multi-round deliberations (`--rounds 2`), distinct specialist personas cycle across rounds:

### Round 1: Divergent Stress-Testing & Defense
- **Oracle (`critic.md`)**: The Skeptic. Probes failure triggers across contracts, boundaries, and concurrency.
- **Architect (`combined_reviewer_critic.md`)**: The Systems Architect. Defends valid code with citations, applies architectural deepening, and applies the deletion test.
- **Tactical Instructions**: `oracle_contract_audit_r1.md` $\longleftrightarrow$ `architect_contract_spec_r1.md`.

### Round 2: Convergent Synthesis & Task Formulation
- **Oracle (`judge.md`)**: The Impartial Arbiter. Scores proposals on a 1–10 rubric and audits test integrity against gamed assertions.
- **Architect (`code-reviewer.md`)**: The Implementer. Applies the YAGNI gate and formulates atomic `### [Task ID: XXX]` specifications.
- **Tactical Instructions**: `oracle_adversarial_hardening_r2.md` $\longleftrightarrow$ `architect_execution_spec_r2.md`.

---

## 4. Configuration Schema & YAML Knobs

Debates are configured in pipeline YAML files (`.env.yml`):

```yaml
    oracle:
        pre_edit_debate:
            enabled: true
            insert_debate: [0, 1, 1]              # Triggers debate before Job 2 and Job 3
            loops: 3                              # 3 turns per round
            rounds: 2                             # 2 outer rounds: cycles personas and collections
            pass_history: true                    # Carry debate context and KV cache to next round
            persist: false                        # Conclude once consensus is reached
            oracle_persona:
                - "markdown/templates/agent_persona/critic.md"
                - "markdown/templates/agent_persona/judge.md"
            architect_persona:
                - "markdown/templates/agent_persona/combined_reviewer_critic.md"
                - "markdown/templates/agent_persona/code-reviewer.md"
            oracle_file:
                - "markdown/templates/debate_instruct/oracle_contract_audit_r1.md"
                - "markdown/templates/debate_instruct/oracle_adversarial_hardening_r2.md"
            architect_file:
                - "markdown/templates/debate_instruct/architect_contract_spec_r1.md"
                - "markdown/templates/debate_instruct/architect_execution_spec_r2.md"
            job_debate_template:
                - ""
                - "markdown/templates/code_quality_audit.md"
                - "markdown/templates/testing_debate.md"
            job_debate_collection:
                - ""
                - ["working_repo_lib", ""]        # R1 queries vector DB; R2 is pure AST (no_retrieve)
                - ""
```

---

## 5. CLI Invocation Reference

```bash
# Standalone CLI debate targeting code modification
aider-oracle --debate code --loops 4 --rounds 2 \
  --oracle-personas critic.md,judge.md \
  --architect-personas combined_reviewer_critic.md,code-reviewer.md \
  --file shared_spec.md \
  "Audit concurrency safety in src/engine.py"

# Persist exploration across all 4 tiers without early exit
aider-oracle --no-rag --debate --loops 8 --rounds 2 --persist "<prompt>"
```
