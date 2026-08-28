---
name: aider-validate
description: Audit document claims against source context, verify exact substring evidence anchors, and execute deterministic quote repairs.
---

# SKILL: Evidence Auditor (`aider-validate`)

`aider-validate` is a deterministic evidence auditor and semantic claim verifier. It mathematically verifies that claims in generated documentation or literature reviews are strictly grounded in source materials.

## Operational Contract & Invariants

1. **Extractive Verification Invariant**: In tag audit mode, claims tagged with `[evidence] "..."` must match exact continuous substrings in the source text.
2. **Tag Mutation Boundary**:
   - **Authoring Agent**: Writes only `[evidence] "quote"` anchors beneath key claims.
   - **Deterministic Auditor (`aider-validate`)**: Promotes verified tags to `[validated]` or `[fixed]`, or demotes ungrounded claims to `[unsupported]`.
3. **Zero Context Flooding**: Always use `--no-print` in automated workflows and read the resulting markdown report from disk.

---

## Operational Modes

### 1. Raw Text Claims Validation (`--claims-only`)
Use this mode to self-validate raw, unquoted documentation (e.g., summaries, architectural decisions, READMEs) against the project vector store. It segments text into semantic paragraphs, retrieves the nearest source chunks from LanceDB, and grades entailment using cosine similarity or an optional neural NLI model (e.g., MiniCheck).

```bash
# Validate markdown file silently and review generated report
aider-validate --claims-only --no-print --file docs/summary.md

# Validate with explicit NLI entailment verifier model, custom threshold, and candidate pool depth
aider-validate --claims-only --file docs/summary.md --grounding-model openai/minicheck --entail-threshold 0.5 --recall-k 40 --report reports/claims_report.md
```

### 2. Exact Substring Tag Auditing & Claim Drift Checking
Use this mode when auditing structured documents containing explicit evidence tags (`[evidence] "verbatim quote"`).

```bash
# Standard grounding audit (generates failure report for non-matching quotes)
aider-validate --file docs/review.md --source docs/source.md --report reports/audit_report.md --tag evidence

# Deterministic autofix (mechanically repairs ellipsis-spliced quotes at 0 token cost)
aider-validate --file docs/review.md --source docs/source.md --report reports/audit_report.md --autofix

# Verify surrounding claims even for verbatim grounded quotes (claim drift annotation)
aider-validate --file docs/review.md --source docs/source.md --report reports/audit_report.md --verify-all --grounding-model openai/minicheck

# Finalize tags (promotes grounded tags to [validated]/[fixed]; demotes failing tags to [unsupported] using debate ledger)
aider-validate --file docs/review.md --source docs/source.md --report reports/audit_report.md --finalize-unsupported --baseline-ledger .aider_factory/logs/debates/review.debate.json
```

---

## Parameter & Flag Reference Table

| Flag | Argument | Default | Description |
| :--- | :--- | :--- | :--- |
| `--file <path>` | File Path | *(Required)* | Target document to audit or repair in-place. |
| `--claims-only` | None | `False` | Enables raw semantic claim scoring against LanceDB (omits tag checks). |
| `--no-print` | None | `False` | Suppresses stdout output to preserve agent context window tokens. |
| `--report <path>` | File Path | `.aider_factory/temp/...` | Output destination for structured audit report. |
| `--source <path>` | File Path | `None` | Authoritative ground-truth source document for exact substring matching. |
| `--tag <name>` | String | `evidence` | Specific anchor tag to audit (e.g., `evidence`). |
| `--autofix` | None | `False` | Resolves ellipsis splices and whitespace variations mechanically. |
| `--finalize-unsupported` | None | `False` | Re-labels verified tags to `[validated]` or `[fixed]` and persistent failures to `[unsupported]`. |
| `--baseline-ledger <path>` | File Path | `None` | Path to debate ledger holding quote baseline set for deletion guard and state tracking. |
| `--db <path>` | Directory Path | `None` | Explicit path to LanceDB directory (auto-discovered if omitted). |
| `--collection <name>` | String | `None` | Target vector collection for semantic grounding. |
| `--region-threshold <float>` | Float | `0.60` | Cosine similarity threshold for semantic claim support (env: `ORACLE_REGION_THRESHOLD`). |
| `--region-margin <int>` | Integer | `2` | Lines beyond paragraph boundary included in claim block (env: `ORACLE_REGION_MARGIN`). |
| `--region-paragraphs <int>` | Integer | `0` | Additional paragraphs above/below to expand claim block (env: `ORACLE_REGION_PARAGRAPHS`). |
| `--top-k <int>` | Integer | `5` | Number of candidate context chunks retrieved per claim (env: `ORACLE_TOP_K`). |
| `--recall-k <int>` | Integer | `None` | Candidate pool size retrieved from LanceDB before reranking (env: `ORACLE_RECALL_K`). |
| `--no-rerank` | None | `False` | Disables Stage 2 cross-encoder reranking over retrieved chunks (env: `ORACLE_NO_RERANK`). |
| `--grounding-model <model>` | String | `None` | LLM/NLI verifier model for claim entailment (env: `GROUNDING_AGENT_MODEL`). |
| `--grounding-api-base <url>` | URL | `None` | API base endpoint for grounding model (env: `GROUNDING_AGENT_API_BASE`). |
| `--grounding-api-key <key>` | String | `None` | API key for grounding model (env: `GROUNDING_AGENT_API_KEY`). |
| `--entail-threshold <float>` | Float | `0.5` | Probability threshold for NLI claim support (env: `GROUNDING_ENTAIL_THRESHOLD`). |
| `--verify-all` | None | `False` | Checks surrounding claim blocks even for grounded verbatim quotes (env: `GROUNDING_VERIFY_ALL`). |
| `--ledger <path>` | File Path | `None` | Path to validation attempt ledger for loop progress tracking. |

---

## Canonical Usage Patterns

```bash
# Pattern A: Self-Correction After Drafting Documentation
# 1. Draft architectural documentation or summary
# 2. Run silent claims audit with NLI entailment scoring
aider-validate --claims-only --no-print --file docs/architecture_summary.md --report reports/summary_audit.md --grounding-model openai/minicheck
# 3. Read audit report to identify and correct ungrounded statements
cat reports/summary_audit.md

# Pattern B: Multi-Stage Verification for Literature Reviews
# Step 1: Execute deterministic autofix for mechanical quote errors
aider-validate --file docs/literature_review.md --source docs/source_text.md --report reports/stage1_report.md --autofix

# Step 2: Run claim drift check across verbatim quotes
aider-validate --file docs/literature_review.md --source docs/source_text.md --report reports/stage2_report.md --verify-all --grounding-model openai/minicheck

# Step 3: Finalize grounded claims after debate reconciliation with deletion guard protection
aider-validate --file docs/literature_review.md --source docs/source_text.md --report reports/final_report.md --finalize-unsupported --baseline-ledger .aider_factory/logs/debates/review.debate.json
```

---

## Execution Checklist

- [ ] Execute `aider-validate --claims-only --no-print` on newly authored documentation to verify factuality.
- [ ] During drafting, emit only `[evidence] "..."` tags; leave tag mutation to `aider-validate`.
- [ ] Run `--autofix` before escalating quote mismatches to LLM debate loops.
- [ ] Use `--verify-all` and `--grounding-model` when prose accuracy around exact quotes is critical.
- [ ] Pass `--baseline-ledger` to `--finalize-unsupported` to enforce the quote deletion floor guard.
- [ ] Inspect generated `--report` artifacts on disk rather than capturing large audit dumps in active prompt context.
