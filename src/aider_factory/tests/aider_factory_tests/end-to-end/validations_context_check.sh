#!/usr/bin/env bash
# Unified evidence heal trigger (test_cmd for the iterate heal job).
#
# Each outer-loop attempt:
#   1. Deterministically RE-VALIDATE the review: every [evidence] quote that is a
#      verbatim substring of the OCR source is relabeled [validated] in place; every
#      failing quote (a tripwire) is written to the report WITH its review passage,
#      a semantic region-grounding score, and the closest SOURCE CHUNKS.
#   2. If quotes remain unresolved AND progress is still possible, ask the Knowledge
#      Oracle to judge each one against its source chunks. The oracle reply (stdout)
#      is captured by the pipeline and handed to the architect, who heals the quote
#      AND any hallucinated surrounding claim and relabels the anchor [fixed].
#
# Per-document inputs are injected by the pipeline via the environment:
#   ORACLE_RAG_DB_DIR        - lancedb directory for this collection
#   ORACLE_COLLECTION        - this paper's LanceDB table (table_name_for(stem))
#   ORACLE_REVIEW_FILE       - the review document being validated/healed
#   ORACLE_SOURCE_FILE       - the OCR source markdown (ground truth)
#   ORACLE_VALIDATION_FILE   - the heal report to write/read (the gate)
#   ORACLE_LEDGER_FILE       - per-doc JSON ledger (no-progress guard state)
#   ORACLE_VALIDATION_TAG    - authored quote tag (default: evidence)
#   ORACLE_REGION_THRESHOLD  - cosine similarity below which a region is flagged
#   ORACLE_REGION_MARGIN     - +/- review lines added to the claim block
#   ORACLE_REGION_TOPK       - source chunks retrieved per tripped quote
# VALIDATION_ATTEMPT (set by orchestrate) resets the ledger on attempt 0.
set -uo pipefail

.aider_factory/bash/validate \
  --file "${ORACLE_REVIEW_FILE:-}" --source "${ORACLE_SOURCE_FILE:-}" \
  --report "${ORACLE_VALIDATION_FILE:-}" --ledger "${ORACLE_LEDGER_FILE:-}" \
  --tag "${ORACLE_VALIDATION_TAG:-evidence}" \
  --db "${ORACLE_RAG_DB_DIR:-}" --collection "${ORACLE_COLLECTION:-}" \
  --region-threshold "${ORACLE_REGION_THRESHOLD:-0.60}" \
  --region-margin "${ORACLE_REGION_MARGIN:-2}" \
  --top-k "${ORACLE_REGION_TOPK:-5}"
rc=$?

# Exit 0 from the validator = stop the loop: everything grounded, OR the no-progress
# guard tripped (residual left in the report for manual review).
[ "$rc" -eq 0 ] && exit 0

# Still-failing with progress possible -> ask the oracle to judge each remaining
# quote against the SOURCE CHUNKS shown in the report.
.aider_factory/bash/oracle --collection "${ORACLE_COLLECTION:-}" --file "${ORACLE_VALIDATION_FILE:-}" \
"Each item below is an [evidence] quote that did NOT match the source verbatim, shown with the \
review passage it sits in and the closest SOURCE CHUNKS. For EACH item, using ONLY those chunks: \
(a) return the corrected quote as an EXACT verbatim substring of a chunk; (b) if the surrounding \
review claim misstates the source, return the corrected claim grounded in the chunks; (c) if the \
chunks do NOT support the claim at all, reply exactly 'UNSUPPORTED' for that item. Reference each \
by its nearest section header. Return ONLY these targeted results; do not rewrite the document."

# Failures remain -> non-zero so the pipeline invokes the architect to apply fixes.
exit 1
