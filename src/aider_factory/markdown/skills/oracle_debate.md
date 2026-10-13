---
name: aider-oracle-debate
description: Execute multi-turn adversarial deliberation, referee arbitration, and technical specification formulation between Architect and Oracle.
---

# SKILL: Knowledge Oracle Deliberation & Debate (`aider-oracle --debate`)

`aider-oracle --debate` runs a refereed, non-interactive Ask-mode deliberation between the Architect (Aider) and the Knowledge Oracle (LiteLLM) to stress-test designs and formulate actionable specifications before writing code.

> **Note on General RAG & Ingestion:** For one-shot queries, fact verification, or LanceDB collection maintenance, see [`aider-oracle`](oracle.md).

---

## Operational Contract & Invariants

1. **Ask-Mode & Zero-Edit Invariant**: The Architect is invoked strictly in Aider Ask mode (`--edit-format ask`). No code edits or git commits are made during deliberation.
2. **Deterministic-First Arbitration**: Termination is governed strictly by deterministic Python token parsing (`deliberate.py`), not model self-certification.
3. **High-Watermark Retention**: Brief closing turns or delta summaries cannot overwrite a comprehensive multi-task specification formulated in earlier turns.
4. **Sanitized Output**: Downstream verdict files strip Aider startup banners (`chat (read-only)...`, `► THINKING`) to deliver clean markdown specifications starting at recognized section headers.
5. **Artifact Parity**: Every debate writes all three companion files to `.aider_factory/logs/debates/`:
   - `<stem>.verdict{r_suf}.md` (Resolution specification and status header)
   - `<stem>.debate{r_suf}.md` (Full readable back-and-forth transcript)
   - `<stem>.debate{r_suf}.json` (Structured ledger with turn hashes and verdicts)
   and archives chat history into `.aider_factory/logs/chat_history/`.

---

## Command Reference & Operational Flags

| Flag | Argument | Description |
| :--- | :--- | :--- |
| `--debate` | `code` \| `review` | Selects domain instruction set (`code` default). |
| `--loops` | `<int>` (Default: 3) | Maximum turn iterations per debate round. |
| `--rounds` | `<int>` (Default: 1) | Outer debate rounds (cycles personas and instructions). |
| `--persist` | *(None)* | Suppresses early exit on intermediate turns to explore deeper audit tiers. |
| `--stem` | `<name>` | Explicit stem prefix for debate artifact files. |
| `--oracle-persona(s)` | `<path(s)>` | Comma-separated persona file(s) for the Oracle. |
| `--architect-persona(s)` | `<path(s)>` | Comma-separated persona file(s) for the Architect. |
| `--oracle-file(s)` | `<path(s)>` | Comma-separated tactical instruction file(s) for the Oracle. |
| `--architect-file(s)` | `<path(s)>` | Comma-separated tactical instruction file(s) for the Architect. |
| `--file` | `<path>` | Ingests shared problem context (e.g. diffs or issue specs) visible to **both** agents. |
| `--no-pass-history` | *(None)* | Wipes conversation memory between debate rounds. |
| `--pass-history` | *(None)* | Preserves conversation context across rounds (default). |
| `--clear` | *(None)* | Clears active debate session memory and cache files. |

---

## Canonical Usage Examples

### 1. Fast-Path 1-Round Pre-Edit Consensus
```bash
aider-oracle --debate code --loops 3 "Propose a thread-safe connection pool for src/db.py"
```

### 2. Deep 4-Tier Audit with Shared Diff Context
```bash
aider-oracle --no-rag --debate --loops 8 --rounds 2 --persist \
  --oracle-personas .aider_factory/markdown/templates/agent_persona/critic.md,.aider_factory/markdown/templates/agent_persona/judge.md \
  --architect-personas .aider_factory/markdown/templates/agent_persona/combined_reviewer_critic.md,.aider_factory/markdown/templates/agent_persona/code-reviewer.md \
  --oracle-files .aider_factory/markdown/templates/debate_instruct/oracle_contract_audit_r1.md,.aider_factory/markdown/templates/debate_instruct/oracle_adversarial_hardening_r2.md \
  --architect-files .aider_factory/markdown/templates/debate_instruct/architect_contract_spec_r1.md,.aider_factory/markdown/templates/debate_instruct/architect_execution_spec_r2.md \
  --file .notes_diff.txt \
  "Audit process lifecycle, timeout watchdogs, credential propagation, and disk cache invalidation."
```

### 3. Review & Grounding Debate
```bash
aider-oracle --debate review --loops 4 --collection research_papers "Verify factual grounding in draft_review.md"
```

---

## Artifact Layout & Verification Checklist

- [ ] Check output artifacts in `.aider_factory/logs/debates/`:
  - `<stem>_<timestamp>.verdict.md`
  - `<stem>_<timestamp>.debate.md`
  - `<stem>_<timestamp>.debate.json`
- [ ] Confirm `STATUS: agreed` and `GATE: draft` in `<stem>...verdict.md` before applying to code.
- [ ] Verify chat history archived in `.aider_factory/logs/chat_history/<stem>_<timestamp>_debate_history.md`.
