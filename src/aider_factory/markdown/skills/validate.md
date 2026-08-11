# SKILL: Evidence Auditor (`aider-validate`)

`aider-validate` is a deterministic, exact-substring evidence auditor and semantic claim verifier. It ensures that claims made in generated documents are provably grounded in the source material. It modifies files in-place to update tags or fix quotes, and generates detailed markdown reports of any failures.

It operates in two distinct modes:
1. **Raw Text Validation (`--claims-only`):** Bypasses tags entirely. Semantically verifies raw paragraphs (like READMEs or summaries) against the LanceDB vector database.
2. **Standard Tag Auditing (Default):** Verifies `[evidence]` anchors by proving the quoted text is an exact substring of the OCR source document.

---

## 1. Raw Text Validation (`--claims-only`)

Use this mode to instantly self-validate raw, quote-less text (such as a summary you just wrote) against the project's knowledge base. It chops the document into paragraphs, retrieves the closest source chunks from LanceDB, and scores each paragraph for hallucinations.

*Note: You only need to provide `--file`. If `--report` is omitted, it automatically writes to `.aider_factory/temp/<stem>_claims_report.md`.*

```bash
# Validate a markdown file (prints a detailed report to the terminal)
aider-validate --claims-only --file README.md

# Validate silently (suppresses stdout; only writes the report to disk)
aider-validate --claims-only --no-print --file README.md

# Validate against a specific global database collection
aider-validate --claims-only --file README.md --collection ~/projects/alpha/.aider_factory/markdown/lanceDB/alpha_docs
```

---

## 2. Standard Tag Auditing

Use this mode when auditing formal literature reviews or reports that utilize `[evidence] "quote"` tags. 
*Note: In this mode, `--file`, `--source`, and `--report` are all strictly required.*

```bash
# Run a standard audit (checks exact-substring grounding and generates a failure report)
aider-validate --file review.md --source source_ocr.md --report report.md --tag evidence
```

### Deterministic Autofix (`--autofix`)
Before escalating failing quotes to a model debate, run the deterministic autofix. It mechanically stitches together ellipsis-spliced quotes (`...`) into continuous verbatim spans if they exist in the source, converting them to `[fixed]` in-place. It costs zero tokens.
```bash
aider-validate --file review.md --source source_ocr.md --report report.md --autofix
```

### Finalize Unsupported (`--finalize-unsupported`)
Used as a terminal step. It scans the document and promotes grounded `[evidence]` tags to `[validated]` or `[fixed]`. If a `--baseline-ledger` is provided and indicates an agreed debate, it demotes still-failing tags to `[unsupported]`.
```bash
aider-validate --file review.md --source source_ocr.md --report report.md --finalize-unsupported --baseline-ledger .aider_factory/logs/debates/review.debate.json
```

---

## 3. Advanced Flags & Tuning

If the pipeline YAML does not auto-discover the database, or if you need to override the strictness of the semantic region checks, you can pass these flags (or set their corresponding `ORACLE_*` environment variables):

* **Database Targeting:**
  * `--db <path>`: Path to the LanceDB directory.
  * `--collection <name>`: The specific table/collection to query.
* **Region Checking (Cosine/Entailment):**
  * `--region-threshold <float>`: Cosine similarity cutoff (default: `0.60`).
  * `--region-margin <int>`: Extra lines of context around matches (default: `2`).
  * `--top-k <int>`: Source chunks retrieved per failing quote (default: `5`).
* **State Tracking (DAG Orchestration):**
  * `--ledger <path>`: JSON file to track the "no-progress guard" across loop attempts.

---

## Agent Best Practices

1. **Self-Correction:** If you write a summary or documentation file, run `aider-validate --claims-only --file <your_file.md>` immediately afterward to ensure you haven't hallucinated any claims.
2. **Never Write Grounding Tags:** When writing or editing formal reports, **only** write `[evidence]`. **Never** write `[validated]`, `[fixed]`, or `[unsupported]`. Only the `aider-validate` tool has the authority to promote or demote tags.
3. **Autofix First:** If you are asked to fix failing quotes in a review, always run `aider-validate ... --autofix` first. It fixes the most common mechanical errors (ellipsis splices) instantly without needing to reason about the text.
