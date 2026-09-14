# LiteLLM Router & Lemonade Server Integration

> **One-stop guide** for configuring aider-factory (pipeline) and aider-helper (interactive assistant) to use a **LiteLLM Router** (custom OpenAI-compatible proxy) backed by a **Lemonade Server** (local model serving platform) as the unified model gateway.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  HARNESS (aider-factory, aider-helper, aider-oracle, aider-apply)   │
│  • Calls litellm.completion(model="openai/<name>", api_base=...)    │
│  • POST /v1/chat/completions                                        │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LiteLLM Router  (e.g. http://<router-host>:4000/v1)                │
│  • Custom communication/routing layer                               │
│  • Single OpenAI-compatible endpoint for ALL harnesses              │
│  • Dispatches requests to the correct backend by model name         │
│  • Models discovered via GET /v1/models                             │
│  • Auth: Bearer token (LITELLM_API_KEY)                             │
│  • Session-affinity via x-litellm-session-id header                 │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Lemonade Server  (e.g. http://<lemonade-host>:11434/v1)            │
│  • One-stop local model serving platform                            │
│  • Downloads & caches open-weight model weights                     │
│  • Configures params (context length, quantization, etc.)           │
│  • Serves models via llama.cpp, vLLM, or other inference engines    │
│  • Manages GPU/CPU allocation automatically                         │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Roles

| Component | Role |
|-----------|------|
| **Lemonade Server** | Local model serving platform. Downloads open-weight model weights, maintains a local cache, configures inference parameters, and serves models through llama.cpp, vLLM, or other engines. One-stop shop for running models locally — no manual GGUF wrangling. |
| **LiteLLM Router** | Custom communication layer. A unified OpenAI-compatible proxy that sits between Lemonade Server (and any other backend) and whatever harness you use. Provides routing, load-balancing, retry logic, session-affinity, and a single `/v1/models` discovery endpoint. Works with aider-factory, opencode, Cursor, or any OpenAI-compatible client. |
| **Harness** | The client tool (aider-factory, aider-helper, etc.) that sends completion requests to the LiteLLM Router. |

**Critical rule:** aider-factory's Python code calls the `litellm` SDK, which speaks the **OpenAI wire format**. The model prefix is always **`openai/`** — never `litellm/`, `lm_studio/`, or `opencode/`. Those are other tools' internal naming conventions.

| Harness / Tool | Model string for the same model |
|----------------|--------------------------------------|
| opencode | `litellm/qwen3.8-flash` |
| Aider CLI (lm_studio provider) | `lm_studio/qwen3.8-flash` |
| **aider-factory / aider-helper** | **`openai/qwen3.8-flash`** |

---

## 2. Prerequisites

- **Lemonade Server** running on a local or network-accessible machine, with desired models downloaded and served.
- **LiteLLM Router** configured to forward requests to the Lemonade Server instance(s) and any other backends (cloud APIs, additional local servers, etc.).
- A valid LiteLLM API token (minted via `make router-key` or the router admin UI).
- Network access from the machine running aider-factory to the router's `/v1/models` and `/v1/chat/completions` endpoints.
- Python 3.10+ with `aider-factory` installed (or the repo checked out).

---

## 3. Environment Variables (add to `~/.zshrc` or `~/.bashrc`)

```bash
# ─── LiteLLM Router (required) ───────────────────────────────────────
export LITELLM_BASE_URL="http://YOUR_ROUTER_IP:4000/v1"
export LITELLM_API_KEY="sk-YOUR_ROUTER_TOKEN"

# ─── aider-helper (interactive assistant) ────────────────────────────
# Tells detect_api_key() to use the router and bypasses the "no key" guard:
export AIDER_HELPER_API_BASE="$LITELLM_BASE_URL"

# Optional: pin a specific default model for aider-helper.
# If unset, auto-discovery picks the first "27b" model from /v1/models.
export AIDER_HELPER_MODEL="openai/qwen3.8-flash"

# ─── Optional: override specific pipeline agents ─────────────────────
# export ORACLE_AGENT_MODEL="openai/qwen3.8-flash"
# export ORACLE_AGENT_API_BASE="$LITELLM_BASE_URL"
```

Reload: `source ~/.zshrc`

### Why each variable matters

| Variable | What it does |
|----------|-------------|
| `LITELLM_BASE_URL` | Points to the LiteLLM Router. Enables `_discover_cluster_config()` during `aider-factory init`; also used by `oracle_agent._ensure_oracle_config()` as a fallback API base. |
| `LITELLM_API_KEY` | The Bearer token sent to the router. Now scanned by `detect_api_key()` as a fallback. |
| `AIDER_HELPER_API_BASE` | Short-circuits `detect_api_key()` to `"CUSTOM_LOCAL"` mode, which triggers the router-aware auth path in `run_query()`. |
| `AIDER_HELPER_MODEL` | Pins the helper's model; prevents reliance on auto-discovery. |

---

## 4. Pipeline Configuration (`.aider_factory/.env_<repo>.yml`)

### 4.1 Endpoints block

Point **all** endpoints at the router. The router internally dispatches to the correct backend:

```yaml
endpoints:
    architect_api_base: "http://YOUR_ROUTER_IP:4000/v1"
    editor_api: "http://YOUR_ROUTER_IP:4000/v1"
    editor_api_fallback: "http://YOUR_ROUTER_IP:4000/v1"
    rag_agent_api: "http://YOUR_ROUTER_IP:4000/v1"
    grounding_agent_api: "http://YOUR_ROUTER_IP:4000/v1"
    ranking_api_base: "http://YOUR_ROUTER_IP:4000/v1"
    ocr_api_base: "http://YOUR_ROUTER_IP:4000/v1"
    embed_api_base: "http://YOUR_ROUTER_IP:4000/v1"
```

> **Note:** If your router does not serve embedding or OCR models, leave those pointing at their dedicated local servers (e.g. `http://<embed-server-host>:8080/v1` for embeddings).

### 4.2 Models block

Every model string must use the **`openai/`** prefix and match the **exact** ID returned by `GET /v1/models`:

```yaml
phases:
  - name: "Code — Implement, Test, Debate-Escalate"
    enabled: true

    models:
        architect_agent: "openai/qwen3.8-flash"
        editor_agent: "openai/Qwen3.8-27B-GGUF-UD-Q4_K_XL:latest"
        editor_agent_test: "openai/qwen3.6-27B-MTP-GGUF-Q4_K_M:latest"
        editor_agent_test_fallback: "openai/qwen3.6-27B-MTP-GGUF-Q4_K_M:latest"
        rag_agent: "openai/qwen3.8-flash"
        ranking_agent: "openai/jina-reranker-v3.5"
        ocr_agent: "openai/unlimited-ocr-bf16:LATEST"
        embed_model: "openai/qwen3-embedding-8b-8k-gpu:LATEST"
        grounding_agent: "openai/minicheck-flan-t5-large"
```

### 4.3 Discovering exact model IDs

```bash
curl -s "$LITELLM_BASE_URL/models" \
  -H "Authorization: Bearer $LITELLM_API_KEY" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for m in sorted(data.get('data', []), key=lambda x: x['id']):
    print(m['id'])
"
```

The strings above **must** match character-for-character (case-sensitive, including `:latest` / `:LATEST` suffixes).

---

## 5. Workspace Scaffold (`aider-helper bootstrap`)

A single deterministic command provisions your project. No LLM calls. No interactive interview.

```bash
aider-helper bootstrap                          # scaffolds in cwd
aider-helper bootstrap --repo /path/to/project  # scaffolds in a different directory
```

### What it does (5 deterministic steps):

| Step | Action | Source |
|------|--------|--------|
| 1 | **Detect keys** | Scans `os.environ` + `.env` files for `LITELLM_API_KEY`, `GEMINI_API_KEY`, `AIDER_HELPER_API_BASE`, etc. |
| 2 | **Detect framework** | Filesystem scan: `pytest.ini` → py, `Cargo.toml` → rs, `package.json` → js, `DESCRIPTION` → R, `go.mod` → go |
| 3 | **Query router** | If `LITELLM_BASE_URL` is set: `GET /v1/models` → selects architect/editor (prefers `"27b"`), embed (`"embed"`), reranker (`"rerank"`) |
| 4 | **Write config** | Regex substitution against bundled `default_configs/env.yml` template. Preserves all inline comments. |
| 5 | **Provision + report** | Creates `.aider_factory/` structure, bash wrappers, git init. Prints structured summary. |

### Zero-key guarantee

If no API key and no router are detected, the command **still produces a valid YAML file** with placeholder endpoints (`http://<your-router-host>:4000/v1`) and prints exactly which environment variables to set next. This is the first-run on-ramp for users who have not yet configured inference infrastructure.

### Model selection logic

When the router is reachable:
- **Architect / Editor**: first model ID containing `"27b"` (case-insensitive), else first available model.
- **Embed**: first model ID containing `"embed"`.
- **Reranker**: first model ID containing `"rerank"`.
- All bare IDs get `openai/` prefix prepended automatically.

When the router is unreachable or unset, template defaults are preserved unchanged.

---

## 6. aider-helper (Interactive Assistant)

### 6.1 Minimum env vars

```bash
export AIDER_HELPER_API_BASE="http://YOUR_ROUTER_IP:4000/v1"
export AIDER_HELPER_MODEL="openai/qwen3.8-flash"   # optional but recommended
export LITELLM_API_KEY="sk-YOUR_TOKEN"
```

### 6.2 Usage

```bash
# Ask a question (terminal mode, no config file needed):
aider-helper query -at "Explain the DAG phase system"

# Ask about your active pipeline config:
aider-helper query -a "What models are configured for the editor?"

# Master mode (loads full YAML docs + skills reference):
aider-helper query -am "How do I add a second phase?"

# Clear session history:
aider-helper query --clear
```

### 6.3 How auth works (internal flow)

```
detect_api_key()
  → AIDER_HELPER_API_BASE set? → return ("CUSTOM_LOCAL", "dummy")

run_query() api_base branch:
  _explicit = LITELLM_API_KEY          ← falls back to real token
  helper_key = resolve_api_key(model, api_base, _explicit)
  if helper_key is real → kwargs["api_key"] = helper_key
  elif _explicit is real → kwargs["api_key"] = _explicit
  else → omit api_key (local llama.cpp ignores auth)
```

---

## 7. aider-oracle (Knowledge Side-Agent)

The oracle reads `ORACLE_AGENT_MODEL` and `ORACLE_AGENT_API_BASE` from env or YAML:

```bash
# One-off query through the router:
export ORACLE_AGENT_MODEL="openai/qwen3.8-flash"
export ORACLE_AGENT_API_BASE="http://YOUR_ROUTER_IP:4000/v1"
aider-oracle --no-rag "What is the leverage formula?"

# With RAG (requires LanceDB + embedding endpoint):
aider-oracle --collection MyDocs "Summarize the key findings"
```

If `LITELLM_BASE_URL` is set, `_ensure_oracle_config()` auto-populates `ORACLE_AGENT_API_BASE` and `ORACLE_EMBED_API_BASE` as fallbacks.

---

## 8. Session ID & KV-Cache Stickiness

All components inject `x-litellm-session-id` into every request:

```python
custom_headers = {"x-litellm-session-id": _PIPELINE_SESSION_ID}
```

The router uses this header for **session-affinity routing** (pins all turns of a conversation to the same backend instance for KV-cache reuse). To set a custom session ID:

```bash
export LITELLM_SESSION_ID="my-pipeline-run-42"
```

If unset, a UUID is generated per process.

---

## 9. Verification Checklist

```bash
# 1. Router reachable + auth works:
curl -s "$LITELLM_BASE_URL/models" \
  -H "Authorization: Bearer $LITELLM_API_KEY" | python3 -m json.tool | head -20

# 2. aider-helper responds:
aider-helper query -at "Say hello in one word"

# 3. aider-oracle responds (no RAG):
ORACLE_AGENT_MODEL="openai/qwen3.8-flash" \
ORACLE_AGENT_API_BASE="$LITELLM_BASE_URL" \
aider-oracle --no-rag "What is 2+2?"

# 4. Pipeline dry-run (no file edits):
aider-factory .aider_factory/.env.yml --dry-run
```

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `❌ No active LLM API key detected` | `AIDER_HELPER_API_BASE` not set | `export AIDER_HELPER_API_BASE="$LITELLM_BASE_URL"` |
| `AuthenticationError: Invalid proxy server token` | `"sk-dummy"` sent instead of real key | Ensure `LITELLM_API_KEY` is exported; update to latest bootstrap.py (commit `8c1f7a5`+) |
| `model not found` / 404 from router | Model string mismatch | `curl /v1/models` and copy the exact `id` field |
| `litellm.NotFoundError` with `litellm/` prefix | Wrong prefix | Change `litellm/foo` → `openai/foo` |
| Helper hangs / times out | Large model cold-start | Set `AIDER_HELPER_MODEL` to a smaller model for interactive use |
| Embedding calls fail | Router doesn't serve embeddings | Point `embed_api_base` to a dedicated embedding server |

---

## 11. What NOT to Do

- ❌ Do **not** use `litellm/`, `lm_studio/`, `opencode/`, or `ollama/` prefixes in the `.env` YAML models block. These are other tools' conventions. The litellm Python SDK only recognizes `openai/` for OpenAI-compatible endpoints.
- ❌ Do **not** hardcode API keys in the YAML file. Use environment variables.
- ❌ Do **not** point `architect_api_base` directly at a Lemonade Server or raw inference engine if you want the LiteLLM Router's load-balancing, retry, and session-affinity features.
- ❌ Do **not** set `AIDER_HELPER_API_BASE` to a URL without the `/v1` suffix.

---

## 12. Summary (TL;DR)

```bash
# ~/.zshrc
export LITELLM_BASE_URL="http://YOUR_IP:4000/v1"
export LITELLM_API_KEY="sk-YOUR_TOKEN"
export AIDER_HELPER_API_BASE="$LITELLM_BASE_URL"
export AIDER_HELPER_MODEL="openai/qwen3.8-flash"
```

```yaml
# .aider_factory/.env_<repo>.yml
endpoints:
    architect_api_base: "http://YOUR_IP:4000/v1"
    # ... all endpoints → router URL ...

phases:
  - models:
        architect_agent: "openai/qwen3.8-flash"
        editor_agent: "openai/Qwen3.8-27B-GGUF-UD-Q4_K_XL:latest"
        # ... all models → openai/<exact-id-from-/v1/models> ...
```

That's it. `aider-helper`, `aider-factory`, `aider-oracle`, and `aider-apply` all route through the same LiteLLM/Lemonade endpoint.
