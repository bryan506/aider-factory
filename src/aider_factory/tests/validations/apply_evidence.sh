#!/usr/bin/env bash
# Deliberation APPLY gate (test_cmd for the apply iterate job).
#
# 1. Strict validation: the validator assigns grounding tags deterministically
#    ([evidence] -> [validated] if original/grounded, [fixed] if edited+grounded) and
#    enforces the deletion guard (anchor count vs the debate's quote_baseline). It exits
#    1 iff any quote is still ungrounded.
# 2. If quotes remain ungrounded, the Knowledge Oracle supplies the EXACT verbatim
#    corrections (role split: oracle = ground-truth supplier, architect = applier). Its
#    stdout is captured by the pipeline and handed to the architect, who edits ONLY the
#    quote text (never tags) per apply_evidence_template.md.
#
# Per-document inputs injected by the pipeline via the environment:
#   ORACLE_RAG_DB_DIR / ORACLE_COLLECTION   - this paper's LanceDB table
#   ORACLE_REVIEW_FILE                       - the review being healed
#   ORACLE_SOURCE_FILE                       - the OCR source (ground truth)
#   ORACLE_VALIDATION_FILE                   - the gate report to write/read
#   ORACLE_BASELINE_LEDGER                   - debate ledger (quote_baseline; deletion guard)
#   ORACLE_VALIDATION_TAG                    - authored quote tag (default: evidence)
#   ORACLE_REGION_THRESHOLD/MARGIN/TOPK      - region-check params
set -uo pipefail

VALIDATE_CMD=".aider_factory/bash/validate"
if [ ! -f "$VALIDATE_CMD" ]; then
  VALIDATE_CMD="aider-validate"
fi

ORACLE_CMD=".aider_factory/bash/oracle"
if [ ! -f "$ORACLE_CMD" ]; then
  ORACLE_CMD="aider-oracle"
fi

$VALIDATE_CMD \
  --file "${ORACLE_REVIEW_FILE:-}" --source "${ORACLE_SOURCE_FILE:-}" \
  --report "${ORACLE_VALIDATION_FILE:-}" --baseline-ledger "${ORACLE_BASELINE_LEDGER:-}" \
  --db "${ORACLE_RAG_DB_DIR:-}" --collection "${ORACLE_COLLECTION:-}" \
  --tag "${ORACLE_VALIDATION_TAG:-evidence}" \
  --region-threshold "${ORACLE_REGION_THRESHOLD:-0.60}" \
  --region-margin "${ORACLE_REGION_MARGIN:-2}" \
  --region-paragraphs "${ORACLE_REGION_PARAGRAPHS:-0}" \
  --top-k "${ORACLE_REGION_TOPK:-5}"
rc=$?

# Exit 0 = all grounded (or flagged [unsupported]) -> stop, apply step succeeds.
[ "$rc" -eq 0 ] && exit 0

# Still ungrounded -> the oracle supplies EXACT verbatim corrections for the architect.
$ORACLE_CMD --collection "${ORACLE_COLLECTION:-}" --file "${ORACLE_VALIDATION_FILE:-}" \
"For EACH [evidence] quote in the report below (shown with its review passage and the closest \
SOURCE CHUNKS), return the EXACT verbatim correction the architect must use to replace it: one \
or two CONTINUOUS sentences copied character-for-character from a source chunk (no ellipses, no \
stitching). If a claim needs two separated spans, give two separate verbatim quotes. If NO \
source chunk supports the claim, reply exactly 'UNSUPPORTED' for that quote. Reference each by \
its nearest section header. Output ONLY these corrections; do not rewrite the document."

# Ungrounded quotes remain -> non-zero so the pipeline invokes the architect to apply fixes.
exit 1
