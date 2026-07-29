#!/usr/bin/env bash
# Cleans up ephemeral artifacts (images, validations) for a specific RAG collection.
# Debate logs live under .aider_factory/logs/debates/ and are cleaned separately.
# Usage: ./clean_lancedb_runs.sh <collection_name>

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <collection_name>"
    echo "Example: $0 summer_intern_papers"
    exit 1
fi

COLLECTION="$1"

# Resolve the absolute path of the collection directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTEXT_DIR="${SCRIPT_DIR}/markdown/lanceDB/${COLLECTION}"

if [ ! -d "${CONTEXT_DIR}" ]; then
    echo "Error: Collection directory does not exist at ${CONTEXT_DIR}"
    exit 1
fi

echo "Cleaning artifacts for collection: '${COLLECTION}'..."

# 1. Clean OCR images directory completely
IMAGE_DIR="${CONTEXT_DIR}/images"
if [ -d "${IMAGE_DIR}" ]; then
    echo " -> Removing images directory: ${IMAGE_DIR}"
    rm -rf "${IMAGE_DIR}"
fi

# 2. Clean validation logs (fixed location, not per-collection)
VALIDATION_DIR="${SCRIPT_DIR}/logs/validations"
if [ -d "${VALIDATION_DIR}" ]; then
    echo " -> Emptying validation logs: ${VALIDATION_DIR}"
    rm -rf "${VALIDATION_DIR:?}"/*
fi

# 3. Clean debate logs (fixed location, not per-collection)
DEBATE_DIR="${SCRIPT_DIR}/logs/debates"
if [ -d "${DEBATE_DIR}" ]; then
    echo " -> Emptying debate logs: ${DEBATE_DIR}"
    rm -rf "${DEBATE_DIR:?}"/*
fi

echo ""
echo "✅ Cleanup complete. LanceDB tables, PDF/MD sources, and chat histories remain untouched."
