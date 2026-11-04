#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

for bin in aider-helper aider-oracle aider-research aider-validate; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "Error: $bin is not installed or not in PATH."
        echo "Please install it using: uv tool install --force git+https://github.com/bryan506/aider-factory.git"
        exit 1
    fi
done

mkdir -p temp reports docs samples

for f in "samples/sample_microstructure.pdf" "docs/strategy_memo_positive.md" "docs/strategy_memo_negative.md"; do
    if [ ! -f "$f" ]; then
        echo "Error: $f does not exist."
        exit 1
    fi
done

if [ ! -f "docs/strategy_memo.md" ]; then
    cp docs/strategy_memo_positive.md docs/strategy_memo.md
fi

if [ -z "${GEMINI_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${LITELLM_API_KEY:-}" ]; then
    export OPENAI_API_KEY="sk-dummy"
fi

export ORACLE_EMBED_MODEL="BAAI/bge-m3"
export ORACLE_EMBED_BACKEND="sentence-transformers"
export ORACLE_EMBED_API_BASE=""

aider-helper bootstrap

# Ensure .aider_factory/.env.yml exists for standard CLI auto-discovery
REPO_NAME="$(basename "$SCRIPT_DIR" | tr ' ' '_')"
if [ -f ".aider_factory/.env_${REPO_NAME}.yml" ] && [ ! -f ".aider_factory/.env.yml" ]; then
    cp ".aider_factory/.env_${REPO_NAME}.yml" ".aider_factory/.env.yml"
    echo "Linked .aider_factory/.env_${REPO_NAME}.yml -> .aider_factory/.env.yml"
elif [ ! -f ".aider_factory/.env.yml" ]; then
    GENERATED_CONFIG=$(find .aider_factory -maxdepth 1 -name ".env_*.yml" 2>/dev/null | head -n 1 || true)
    if [ -n "$GENERATED_CONFIG" ]; then
        cp "$GENERATED_CONFIG" ".aider_factory/.env.yml"
        echo "Linked $GENERATED_CONFIG -> .aider_factory/.env.yml"
    fi
fi

# Sanitize any scaffolded placeholder or router embed_api_base from all env configs for local sentence-transformers
python3 -c '
import glob, yaml
for p in glob.glob(".aider_factory/.env*.yml"):
    raw = open(p, "r", encoding="utf-8").read().replace("http://<your-router-host>:4000/v1", "")
    cfg = yaml.safe_load(raw) or {}
    if isinstance(cfg, dict):
        if isinstance(cfg.get("endpoints"), dict):
            cfg["endpoints"].pop("embed_api_base", None)
        if isinstance(cfg.get("rag"), dict):
            cfg["rag"]["embed_model"] = "BAAI/bge-m3"
            cfg["rag"]["embed_backend"] = "sentence-transformers"
            cfg["rag"].pop("embed_api_base", None)
        for ph in (cfg.get("phases") or []):
            if isinstance(ph, dict):
                if isinstance(ph.get("endpoints"), dict):
                    ph["endpoints"].pop("embed_api_base", None)
                pr = ph.setdefault("rag", {})
                if isinstance(pr, dict):
                    pr["embed_model"] = "BAAI/bge-m3"
                    pr["embed_backend"] = "sentence-transformers"
                    pr.pop("embed_api_base", None)
        open(p, "w", encoding="utf-8").write(yaml.safe_dump(cfg, sort_keys=False))
' 2>/dev/null || true

chmod +x 01_setup_workspace.sh 02_research_and_rag.sh 03_draft_and_validate.sh
