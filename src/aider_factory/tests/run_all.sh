#!/usr/bin/env bash
# Canonical test runner: uses aider's venv (lancedb, tree_sitter_language_pack,
# sentence-transformers) and runs from the repo root so tests' project-relative
# paths (".aider_factory/python", "temp/") resolve. Runs ALL tests, reports, then
# exits non-zero if any failed.
# Dynamically resolve the python interpreter of the aider-factory uv tool or virtualenv
if [ -z "$AIDER_PY" ]; then
    if [ -f "$HOME/.local/share/uv/tools/aider-factory/bin/python" ]; then
        AIDER_PY="$HOME/.local/share/uv/tools/aider-factory/bin/python"
    elif [ -f "$HOME/.local/share/uv/tools/aider-chat/bin/python" ]; then
        AIDER_PY="$HOME/.local/share/uv/tools/aider-chat/bin/python"
    elif [ -n "$VIRTUAL_ENV" ] && [ -f "$VIRTUAL_ENV/bin/python" ]; then
        AIDER_PY="$VIRTUAL_ENV/bin/python"
    else
        AIDER_PY=$(which python3 || which python)
    fi
fi
cd "$(dirname "$0")/../../.." || exit 1          # -> repo root
fail=0; failed=()
for f in src/aider_factory/tests/aider_factory_tests/test_*.py src/aider_factory/tests/aider_factory_tests/end-to-end/test_e2e_*.py; do
    [ -e "$f" ] || continue
    echo "── $f"
    timeout 600 "$AIDER_PY" "$f" || { fail=1; failed+=("$f"); echo "❌ FAILED $f"; }
done
if [ "$fail" -eq 0 ]; then
    echo "🎉 All tests passed."
else
    echo "Failures: ${failed[*]}"; exit 1
fi
