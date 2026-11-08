#!/usr/bin/env bash
# rag_rsync.sh — Pass-through rsync wrapper that filters out .git, dotfiles,
# .gitignore/.aiderignore matches, agent harnesses, and non-RAG binary artifacts.
#
# Usage:
#   rsync-rag [rsync_options...] <src>... <dest>
#   rsync-rag ~/R/devenv .aider_factory/markdown/lanceDB/devenv_repo/
#   rsync-rag -ravn -e 'ssh -p 22 -i ~/.ssh/id_ed25519' --progress ./devenv user@host:/path/to/lanceDB/col/

set -euo pipefail

if [[ $# -eq 0 ]] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    cat <<'EOF'
rsync-rag: RAG-filtered rsync pass-through utility for AI Factory collections.

Usage:
  rsync-rag [rsync_options...] <src>... <dest>

Examples:
  rsync-rag ~/R/devenv .aider_factory/markdown/lanceDB/devenv_repo/
  rsync-rag -avn ~/R/devenv .aider_factory/markdown/lanceDB/devenv_repo/
  rsync-rag -rav -e 'ssh -p 22 -i ~/.ssh/id_key' --progress ./devenv user@192.168.11.111:~/project/.aider_factory/markdown/lanceDB/devenv_repo/
EOF
    exit 0
fi

DRY_RUN=0
SKIP_NEXT=0
PARSE_OPTS=1
POSITIONALS=()
for arg in "$@"; do
    if [[ $SKIP_NEXT -eq 1 ]]; then
        SKIP_NEXT=0
        continue
    fi
    if [[ $PARSE_OPTS -eq 0 ]]; then
        POSITIONALS+=("$arg")
        continue
    fi
    case "$arg" in
        --)
            PARSE_OPTS=0
            ;;
        -e|--rsh|--filter|-f|--exclude|--include|--exclude-from|--include-from|--files-from|--max-size|--min-size|--bwlimit|--port)
            SKIP_NEXT=1
            ;;
        --dry-run|-n)
            DRY_RUN=1
            ;;
        -[!-]*)
            if [[ "$arg" == *n* ]]; then
                DRY_RUN=1
            fi
            ;;
        -*)
            ;;
        *)
            POSITIONALS+=("$arg")
            ;;
    esac
done

if [[ ${#POSITIONALS[@]} -lt 2 ]]; then
    echo "❌ [rsync-rag] Error: Requires at least a source and destination argument." >&2
    exit 1
fi

DEST="${POSITIONALS[${#POSITIONALS[@]}-1]}"
if [[ $DRY_RUN -eq 0 ]] && { [[ "$DEST" =~ ^[a-zA-Z]: ]] || [[ ! "$DEST" =~ ^[^/\\]+: ]]; } && [[ "$DEST" != -* ]] && [[ ! -f "$DEST" ]]; then
    mkdir -p "$DEST"
fi

RAG_FILTERS=(
    --filter=':- .gitignore'
    --filter=':- .aiderignore'
    --exclude='.*'
    --exclude='node_modules/'
    --exclude='renv/'
    --exclude='packrat/'
    --exclude='__pycache__/'
    --exclude='venv/'
    --exclude='env/'
    --exclude='build/'
    --exclude='dist/'
    --exclude='target/'
    --exclude='out/'
    --exclude='coverage/'
    --exclude='htmlcov/'
    --exclude='site/'
    --exclude='_site/'
    --exclude='data/'
    --exclude='temp/'
    --exclude='tmp/'
    --exclude='tempFiles/'
    --exclude='tempfiles/'
    --exclude='logs/'
    --exclude='log/'
    --exclude='secrets/'
    --exclude='credentials/'
    --exclude='vendor/'
    --exclude='third_party/'
    --exclude='ai-agent-config/'
    --exclude='cursor-skills/'
    --exclude='skeleton/'
    --exclude='lancedb/'
    --exclude='images/'
    --exclude='AGENTS.md'
    --exclude='AGENTS.md.*'
    --exclude='CLAUDE.md'
    --exclude='GEMINI.md'
    --exclude='CONVENTIONS.md'
    --exclude='README.skeleton.md'
    --exclude='*.rds'
    --exclude='*.rda'
    --exclude='*.RData'
    --exclude='*.parquet'
    --exclude='*.feather'
    --exclude='*.h5'
    --exclude='*.bin'
    --exclude='*.exe'
    --exclude='*.dll'
    --exclude='*.so'
    --exclude='*.dylib'
    --exclude='*.zip'
    --exclude='*.tar'
    --exclude='*.tar.gz'
    --exclude='*.tgz'
    --exclude='*.gz'
    --exclude='*.7z'
    --exclude='*.lock'
    --exclude='package-lock.json'
    --exclude='Cargo.lock'
    --exclude='*.log'
    --exclude='*.map'
    --exclude='*.pyc'
)

RSYNC_BIN="$(command -v rsync || true)"
if [[ "$(uname -s)" == "Darwin" ]] && [[ "$RSYNC_BIN" == "/usr/bin/rsync" ]] && "$RSYNC_BIN" --version 2>&1 | grep -qi openrsync; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SRC_ROOT="$(cd "$SCRIPT_DIR/../src" 2>/dev/null && pwd || true)"
    if [[ -n "$SRC_ROOT" ]] && command -v python3 >/dev/null 2>&1; then
        exec python3 -c "import sys; sys.path.insert(0, '$SRC_ROOT'); from aider_factory.cli import rsync_rag_cli; rsync_rag_cli()" "$@"
    fi
fi

exec rsync -a --prune-empty-dirs "${RAG_FILTERS[@]}" "$@"
