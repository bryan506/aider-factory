#!/usr/bin/env bash
# Tier-2 gate + advice (post_validate). If Tier-1 wrote a failures report for this
# document, ask the Knowledge Oracle for grounded corrections. The oracle's reply
# (stdout) is captured by the pipeline and handed to the architect, who plans the
# search/replace fixes for the editor to apply to the review.
#
# Per-document inputs are injected by the pipeline via the environment:
#   ORACLE_COLLECTION        - this paper's LanceDB table (table_name_for(stem))
#   ORACLE_VALIDATION_FILE   - path to the Tier-1 failures report (the gate)
#   ORACLE_REVIEW_FILE       - the review document (for reference)
#   ORACLE_SOURCE_FILE       - the OCR source markdown (for reference)
set -euo pipefail

# No failures report (or empty) -> this paper is grounded -> pass, skip the agent.
[ -n "${ORACLE_VALIDATION_FILE:-}" ] && [ -s "${ORACLE_VALIDATION_FILE}" ] || exit 0

.aider_factory/bash/oracle --collection "${ORACLE_COLLECTION:-}" --file "${ORACLE_VALIDATION_FILE:-}" \
"The [evidence] quotes in the attached report could not be matched to the source knowledge base. \
For EACH listed quote, retrieve the correct verbatim text from the source and return ONLY targeted \
fixes: the exact incorrect [evidence] line followed by its corrected [evidence] line, and reference \
the nearest section header so the location is unambiguous. Do NOT rewrite the document or restate \
unaffected sections. If an adjoining claim is also unsupported by the source, give the minimal \
correction needed. If a quote cannot be grounded in the source at all, state that explicitly."

# Failures existed -> non-zero so the pipeline invokes the architect to apply fixes.
exit 1
