---
name: evidence-tags
description: Protocol and syntax rules for embedding extractive [evidence] quote anchors beneath factual claims in generated documentation.
---

# SKILL: Evidence Grounding Anchors (`[evidence]`)

This skill defines the affirmative protocol for grounding key claims, figures, requirements, and findings in generated documentation or reports. Attaching extractive evidence anchors ensures outputs are mathematically verifiable against source context by automated audit tools (`aider-validate`).

## Operational Contract & Invariants

1. **Extractive Sourcing**: Every anchor must be an exact, character-for-character copy of continuous source text (`CONTEXT`). Quote the source text first, then make the claim.
2. **Anchor Placement & Formatting**: Place the anchor on its own line immediately beneath the supported claim, or inline within paragraph/bullet text:
   - *Standalone Block*: `[evidence] "exact words copied from source context"`
   - *Backticked Tag*: `` `[evidence]` "exact words copied from source context" ``
   - *Inline Anchor*: `The metric increased by 14%. [evidence] "The metric increased by 14% across trials."`
3. **Tag Authoring Discipline**: The authoring agent writes exclusively `[evidence]` tags. Tag promotion (`[validated]`, `[fixed]`) and demotion (`[unsupported]`) are performed exclusively by `aider-validate`.
4. **Tag State Machine**:
   - `[evidence]`: Initial authored state produced by agents.
   - `[validated]`: Exact verbatim substring verified against source text by `aider-validate`.
   - `[fixed]`: Healed anchor repaired via deterministic stitching (`--autofix`) or iterative agent edit.
   - `[unsupported]`: Terminal ungrounded tag assigned via `aider-validate --finalize-unsupported` following deliberation agreement.
5. **Preservation Invariant**: Retain all existing quote anchors when applying targeted text edits.

---

## Anchor Classification Rules

### 1. Claims Requiring Evidence Anchors
- **Quantitative Metrics & Results**: Numeric metrics, percentages, sample sizes, benchmark figures, and statistical coefficients.
- **Formal Specifications**: Architectural models, equations, algorithm definitions, and protocol formulas.
- **Environmental & Data Facts**: Dataset specifications, sample timeframes, frequencies, and hardware configurations.
- **Authoritative Constraints**: System requirements, published assumptions, and core paper-derived rules.

### 2. Claims Excluded from Anchoring
- Synthesized conclusions, forward-looking recommendations, and editorial judgments. (These must logically rest upon anchored facts).

---

## Affirmative Quotation Protocols

| Aspect | Operational Requirement | Failure Mode Prevented |
| :--- | :--- | :--- |
| **Exact Substring** | Copy character-for-character, preserving original formatting and OCR artifacts. | Substring mismatch in validator. |
| **Span Length** | Select a single unbroken continuous span (1–2 sentences, ~20–50 words, or one equation). | Context boundary overrun. |
| **Continuous Copy** | Select shorter spans instead of joining fragments with ellipses (`...`). | Splicing rejection during regex audit. |
| **Density Limit** | Emit 1 quote per claim (maximum 2). | Active context bloat. |
| **Missing Evidence** | When no exact span exists in source context, state: `Not specified in paper.` | Hallucinated citations (matches validator `_SENTINEL`). |
| **Ellipsis Auto-Stitch** | While manual quotes avoid `...`, `aider-validate --autofix` automatically stitches multi-fragment quotes if the source gap is $\le 200$ chars. | Broken quote spans across formatting breaks. |
| **Quote Escaping** | If the source span contains internal double quotes (`"`), trim bounds to avoid quotes. | Tag parser syntax errors. |
| **OCR Uncertainty** | For degraded text or formulas, append `(OCR-uncertain)` after the tag line. | Ambiguous audit flags. |

---

## Tooling & Validation Pathways (`aider-validate`)

`aider-validate` operates deterministically over authored documentation and OCR sources:

```bash
# 1. Deterministic Evidence Audit & Ellipsis Auto-Stitching
aider-validate --file review.md --source source_ocr.md --report report.md --autofix

# 2. Raw Text / Paragraph Hallucination Audit (No [evidence] Tags Required)
aider-validate --file summary.md --claims-only

# 3. Terminal Promotion / Demotion Following Deliberation
aider-validate --file review.md --source source_ocr.md --finalize-unsupported --baseline-ledger logs/debates/review.debate.json

# 4. Custom Embedding and Reranking Parameters
aider-validate --file review.md --source source_ocr.md --report report.md --region-threshold 0.65 --top-k 10 --recall-k 50
```

### Key CLI Flags

| Flag | Purpose | Default |
| :--- | :--- | :--- |
| `--file <path>` | Target document (review/report) to audit. | *(Required)* |
| `--source <path>` | Markdown source of truth (OCR document). | *(Required unless `--claims-only`)* |
| `--report <path>` | Diagnostic report output path for ungrounded claims. | *(Optional)* |
| `--autofix` | Deterministically stitches `...` quote fragments ($\le 200$ char gap) into `[fixed]`. | `False` |
| `--claims-only` | Audits raw text paragraphs using semantic chunking and entailment models. | `False` |
| `--finalize-unsupported` | Demotes agreed-ungrounded anchors to `[unsupported]` and promotes grounded anchors. | `False` |
| `--tag <name>` | Custom anchor tag family name. | `evidence` |
| `--region-threshold <float>` | Minimum cosine similarity threshold for region grounding. | `0.60` |
| `--no-rerank` | Disables Stage 2 CrossEncoder reranking. | `False` |
| `--recall-k <int>` | Stage 1 candidate pool size before reranking. | Auto-scaled |
| `--top-k <int>` | Maximum source chunks retrieved per claim. | `5` |

---

## Canonical Usage Pattern

```markdown
## Performance & Memory Analysis

The cache eviction policy uses a two-stage least-recently-used buffer with a 256MB boundary.
[evidence] "The eviction pipeline maintains a dual-stage LRU ring buffer bounded at 256MB capacity."

Mean query latency under peak load dropped to 14.2ms.
`[evidence]` "Under sustained 10k RPS load, median query latency reached 14.2ms across all nodes."

Thermal throttling threshold is not documented in the specification.
[evidence] "Not specified in paper."

The objective loss formulation incorporates penalty term $\lambda$:
[evidence] "The regularized loss is defined as $\mathcal{L}_{\text{total}} = \mathcal{L}_{\text{task}} + \lambda \|\theta\|_2^2$." (OCR-uncertain)
```

---

## Execution Checklist

- [ ] Locate exact supporting sentence in source context before authoring the factual claim.
- [ ] Copy unbroken continuous spans without unnecessary ellipsis stitching (`...`).
- [ ] For absent evidence, use the exact sentinel: `[evidence] "Not specified in paper."`.
- [ ] Annotate mathematical expressions or degraded text with trailing `(OCR-uncertain)`.
- [ ] Emit only `[evidence]` tags and let `aider-validate` handle tag validation and promotion (`[validated]`, `[fixed]`, `[unsupported]`).
- [ ] Run `aider-validate --file <doc> --source <src> --report <rpt> --autofix` to verify and auto-repair.
