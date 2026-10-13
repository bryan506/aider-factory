# High-Performance Inference Servers, Routing & Models Configuration

> **Context Anchor & Authoring Directive:**  
> This document is the authoritative master specification for high-performance LLM/vision inference serving, dynamic endpoint prefix routing, context arithmetic, and model settings overrides within the AI Factory pipeline.  
> **Source References:** `factory_service_manual.md` (`## Operating System & Core Dependencies`, `## High-Performance Inference Servers`, `### Understanding Model Prefix Routing`, `### llama.cpp Architecture Overview`, `### Aider Configuration: .aider.conf.yml`, `### Aider Model Overrides: .aider.model.settings.yml`, `### Aider Operational Flags and Chat History`, `## Appendix A: Required Environment Variables`, `### Verifying Service Health`, `### Common Errors and Fixes`).  
> **Codebase References:** `src/aider_factory/default_configs/env.yml`, `src/aider_factory/default_configs/aider.conf.yml`, `src/aider_factory/default_configs/aider.model.settings.yml`, `src/aider_factory/python/env_utils.py`, `src/aider_factory/python/orchestrate.py`, `src/aider_factory/python/apply_agent.py`.

---

## 1. Executive Overview & Foundational Invariants

The AI Factory pipeline orchestrates multi-agent coding, reasoning, and document ingestion pipelines by multiplexing requests across heterogeneous local inference servers (`llama.cpp`, `ollama`) and remote cloud providers (Google Gemini, Anthropic Claude, OpenAI, OpenRouter, Groq). Local inference provides zero-cost, zero-latency-penalty iteration and strict on-premises data privacy, while cloud endpoints supply massive context windows and advanced multi-modal capabilities.

### Foundational Invariants

1. **Deterministic Prefix Routing & Zero-Hardcoded URLs**: Model identifiers determine backend dispatch via Aider prefix parsing (`openai/`, `ollama/`, `lm_studio/`, `gemini/`, `anthropic/`). Target endpoints are injected via standard environment variables (`OPENAI_API_BASE`, `OLLAMA_API_BASE`, `LM_STUDIO_API_BASE`), preventing hardcoded URLs from contaminating prompts.
2. **Simultaneous Dual-Endpoint Injection**: Whenever an editor endpoint (`editor_api` or `editor_api_base`) is defined, the runtime environment simultaneously sets both `OLLAMA_API_BASE` and `LM_STUDIO_API_BASE` to that exact address in `orchestrate.py` and `apply_agent.py`. This guarantees transparent routing regardless of whether models use `ollama/` or `lm_studio/` prefixes.
3. **Strict Context Slot Partitioning**: Local `llama-server` instances divide their total allocation evenly across parallel slots. A request exceeding the per-slot limit ($C_{\text{slot}} = \lfloor \frac{C_{\text{total}}}{N_{\text{parallel}}} \rfloor$) triggers an unrecoverable `400 Bad Request`.
4. **Case-Sensitive Alias Registry (`models.ini`)**: Multi-model `llama-server` dispatch relies on strict, case-sensitive matching against `models.ini` section headers. Model identifiers in `.env.yml` must match `models.ini` byte-for-byte (e.g., `openai/qwen3.6-27b-90k:LATEST` matches `[qwen3.6-27b-90k:LATEST]`).
5. **Strict Local vs Cloud Weak Model Isolation**: Cloud models (`gemini/`, `anthropic/`, `claude/`, `openai/gpt-`, `o1`, `o3`) must never receive a local API base URL. The runtime utility `is_local_model()` checks all weak model assignments, forcing `weak_model_api_base = None` for cloud models to prevent socket failures.
6. **Reasoning Budget Control & Deterministic Oracle Output**: Local reasoning models streaming `<think>` tokens can destabilize regex-gated scripts. Setting `think: false`, `thinking_tokens: 0`, and `reasoning_effort: low` via `.aider.model.settings.yml` ensures deterministic output for RAG and debate arbiters.
7. **Session-Scoped Overrides (`ensure_model_settings()`)**: Runtime endpoint adjustments dynamically upsert entries into `.aider_factory/sessions/<session_id>/.aider.model.settings.yml` using temporary files, avoiding destructive modifications to workspace settings.

---

## 2. System Topology & Lifecycle Flowcharts

### 2.1 Dual Inference Server Architecture
To eliminate lock contention between sustained reasoning and multi-page vision ingestion, inference workloads are split across two dedicated `llama-server` ports:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          DUAL INFERENCE SERVER ARCHITECTURE                            │
├──────────────────────────────────────────┬─────────────────────────────────────────────┤
│ Primary Reasoning Router (Port 8081)     │ Vision, OCR & Embedding Server (Port 8080)  │
├──────────────────────────────────────────┼─────────────────────────────────────────────┤
│ • Systemd: llama-pair-router.service     │ • Systemd: llama-vision.service             │
│ • Roles: Architect, Editor, Oracle,      │ • Roles: GLM-OCR, Docling, BGE-M3,          │
│   Weak Model, Deliberation Arbiter       │   Qwen-Embedding                            │
│ • Concurrency: --parallel 3 (or 4)       │ • Concurrency: --parallel 2 to 4            │
│ • Routing Target: architect_api_base,    │ • Routing Target: ocr_api_base,             │
│   editor_api, weak_model_api_base        │   embed_api_base                            │
│ • Context: 90,112 tokens (3x 30k slots)   │ • Context: 32,768 tokens (2x 16k slots)     │
└──────────────────────────────────────────┴─────────────────────────────────────────────┘
```

### 2.2 Prefix Routing & Endpoint Dispatch DAG

```text
                     [Model Identifier: model_name]
                                   │
               ┌───────────────────┴───────────────────┐
               ▼                                       ▼
       [Cloud Provider?]                       [Local / Custom?]
  (gemini/, anthropic/, openrouter/)      (openai/, ollama/, lm_studio/, bare)
               │                                       │
     ┌─────────┴─────────┐                   ┌─────────┴─────────┐
     ▼                   ▼                   ▼                   ▼
[Direct Litellm /   [API Keys via       [openai/ Prefix]   [ollama/ or lm_studio/]
 Aider Native]      resolve_api_key()]       │                   │
     │                   │                   ▼                   ▼
     │                   │           OPENAI_API_BASE =     OLLAMA_API_BASE =
     │                   │           architect_api_base    editor_api
     │                   │                   │             LM_STUDIO_API_BASE =
     │                   │                   │             editor_api
     └─────────┬─────────┘                   └─────────┬─────────┘
               │                                       │
               └───────────────────┬───────────────────┘
                                   ▼
             [Subprocess Execution: Aider / Litellm / Requests]
```

### 2.3 `llama-server` Slot Allocation Lifecycle

```text
[Incoming HTTP Request] ──► [Endpoint: /v1/chat/completions]
                                   │
                    [Check Slot Context Budget]
                                   │
         ┌─────────────────────────┴─────────────────────────┐
         ▼                                                   ▼
 [Tokens <= C_slot]                                  [Tokens > C_slot]
         │                                                   │
 [Assign Free Slot]                                  [HTTP 400 Bad Request]
         │                                           "exceeds available context"
 [Evaluate & Stream Tokens]
         │
 [Release Slot & Cache KV]
```

---

## 3. Technical Mechanics & Mathematical Formulations

### 3.1 Mathematical Formulations

#### 1. Context Slot Partitioning
`llama-server` allocates a global context buffer $C_{\text{total}}$ (`--ctx-size`) and divides it among $N_{\text{parallel}}$ concurrency slots (`--parallel`):

$$C_{\text{slot}} = \left\lfloor \frac{C_{\text{total}}}{N_{\text{parallel}}} \right\rfloor$$

When $C_{\text{total}} = 90{,}112$ and $N_{\text{parallel}} = 3$:

$$C_{\text{slot}} = \left\lfloor \frac{90{,}112}{3} \right\rfloor = 30{,}037 \text{ tokens}$$

#### 2. Usable Prompt Headroom
The maximum allowable tokens for prompt context $T_{\text{prompt}}$ (system prompt, repo-map, read files, conversation history) depends on generation reserve $T_{\text{max\_gen}}$, system instructions $T_{\text{sys}}$, and safety margin $T_{\text{headroom}}$:

$$T_{\text{prompt}} = C_{\text{slot}} - (T_{\text{max\_gen}} + T_{\text{sys}} + T_{\text{headroom}})$$

Where typically $T_{\text{max\_gen}} = 4{,}096$, $T_{\text{sys}} = 1{,}024$, and $T_{\text{headroom}} = 512$, yielding:

$$T_{\text{prompt}} \le 30{,}037 - (4{,}096 + 1{,}024 + 512) = 24{,}405 \text{ tokens}$$

#### 3. KV Cache VRAM Footprint
Total VRAM required for KV cache memory $M_{\text{KV}}$ across all attention layers $L$, hidden dimension $D_{\text{model}}$, total context $C_{\text{total}}$, and bytes per weight element $B_{\text{element}}$:

$$M_{\text{KV}} = 2 \times L \times D_{\text{model}} \times C_{\text{total}} \times B_{\text{element}}$$

For FP16 KV-cache ($B_{\text{element}} = 2$), a model with $L = 64$ and $D_{\text{model}} = 5{,}120$ requires:

$$M_{\text{KV}} = 2 \times 64 \times 5{,}120 \times 90{,}112 \times 2 \approx 118{,}118{,}410{,}240 \text{ bytes} \approx 118.1 \text{ GB}$$

Applying 8-bit quantization (`--ctk q8_0 --ctv q8_0`, $B_{\text{element}} = 1$) cuts this footprint to $\approx 59.05 \text{ GB}$.

#### 4. Character Error Rate (CER) OCR Verification Gate
During document ingestion in `rag_manager.py`, OCR hypothesis quality is evaluated against digital text using Normalized Levenshtein Edit Distance:

$$\text{CER}(R, H) = \frac{\text{Levenshtein}(R_{\text{norm}}, H_{\text{norm}})}{|R_{\text{norm}}|}$$

Where $R_{\text{norm}}$ and $H_{\text{norm}}$ are alphanumeric-normalized strings. The retry and fallback thresholds are governed by:
- $\text{CER} \le \tau_{\text{retry}}$ (default $0.05$): OCR passes verification.
- $\text{CER} > 0.40$ with $|R_{\text{norm}}| > 50$: Fallback directly to the native PDF text layer.

---

### 3.2 Routing & Environment Mechanics in `env_utils.py`

#### Model Classification (`is_local_model`)
Determines whether a model should be treated as a local custom endpoint or delegated to cloud providers:
- Evaluates provider prefixes: `gemini/`, `google/`, `anthropic/`, `claude/`, `openrouter/`, `groq/`, `deepseek/`, `mistral/`, `cohere/`, `bedrock/`, `vertex_ai/`, `azure/`.
- Evaluates bare model prefixes: `claude-`, `command-`, `deepseek-`, `mistral-`.
- Strips leading `openai/` and inspects standard cloud names: `gpt-`, `o1`, `o3`, `chatgpt`, `text-embedding`, `dall-e`, `tts-`, `whisper-`, `babbage`, `davinci`.
- Returns `False` if matched, `True` for custom local models.

```python
def is_local_model(model_name: Optional[str]) -> bool:
    if not model_name or not isinstance(model_name, str):
        return True
    m = model_name.strip().lower()
    cloud_prefixes = (
        "gemini/", "google/", "anthropic/", "claude/", "openrouter/",
        "groq/", "deepseek/", "mistral/", "cohere/", "bedrock/",
        "vertex_ai/", "azure/",
    )
    if any(m.startswith(p) for p in cloud_prefixes):
        return False
    bare_cloud = ("claude-", "command-", "deepseek-", "mistral-")
    if any(m.startswith(p) for p in bare_cloud):
        return False
    bare = m[7:] if m.startswith("openai/") else m
    openai_cloud_prefixes = (
        "gpt-", "o1", "o3", "chatgpt", "text-embedding",
        "dall-e", "tts-", "whisper-", "babbage", "davinci",
    )
    if any(bare.startswith(p) for p in openai_cloud_prefixes):
        return False
    return True
```

#### Endpoint Validation (`is_valid_endpoint`)
Filters empty, placeholder, or invalid URLs:
- Checks for dummy strings (`sk-dummy`, `none`, `null`).
- Rejects template placeholders (`<...>`, `your-router-host`).
- Requires valid URL prefixes (`http://` or `https://`).

```python
def is_valid_endpoint(url: Optional[str]) -> bool:
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if is_dummy_key(u):
        return False
    if "<" in u or ">" in u or "your-router-host" in u:
        return False
    return u.startswith(("http://", "https://"))
```

#### Dual-Endpoint Injection
`orchestrate.py` and `apply_agent.py` eliminate routing mismatches between Ollama and LM Studio by simultaneously injecting both variables when configuring the subprocess environment:

```python
if task.editor_api_base:
    env["OLLAMA_API_BASE"] = task.editor_api_base
    env["LM_STUDIO_API_BASE"] = task.editor_api_base
```

#### Settings Synchronization (`ensure_model_settings`)
Non-destructively upserts model settings into `.aider.model.settings.yml` using temporary files:
1. Loads base model configurations from `.aider_factory/.aider.model.settings.yml` or repo root.
2. Registers alias variants (e.g., both bare `qwen2.5-coder` and `openai/qwen2.5-coder`).
3. Writes the updated dictionary to a temporary file in the target directory and replaces the destination atomically (`os.replace`), preventing concurrent read corruption.

```python
def ensure_model_settings(
    target_path: str,
    models_to_configure: list[dict],
    base_settings_path: Optional[str] = None,
) -> str:
    # Loads existing dictionary from base or target
    # Upserts normalized names: [name, bare_name, openai/name]
    # Writes to temporary file: tempfile.mkstemp(dir=target_dir, suffix=".tmp")
    # Atomically swaps: os.replace(tmp_path, target_path)
    ...
```

---

## 4. Exhaustive CLI & Parameter Reference

### 4.1 Server Launch Parameters (`llama-server`)

```bash
# Primary Reasoning Router (ROCm / AMD GPU Acceleration)
llama-server \
  --models-from-config /etc/llama-cpp/models.ini \
  --port 8081 \
  --host 0.0.0.0 \
  --ctx-size 90112 \
  --parallel 3 \
  --n-gpu-layers 999 \
  --split-mode row \
  --ctk q8_0 \
  --ctv q8_0 \
  --slots \
  --metrics

# Vision, OCR & Embedding Server (CUDA / NVIDIA Acceleration)
llama-server \
  --models-from-config /etc/llama-cpp/vision_models.ini \
  --port 8080 \
  --host 0.0.0.0 \
  --ctx-size 32768 \
  --parallel 2 \
  --n-gpu-layers 999 \
  --cont-batching
```

### 4.2 Systemd Daemon Management

```bash
# Verify Daemon Status
systemctl status llama-pair-router.service
systemctl status llama-vision.service

# Restart Services After Model Configuration Updates
sudo systemctl restart llama-pair-router.service
sudo systemctl restart llama-vision.service

# Live Log Telemetry Stream
journalctl -u llama-pair-router.service -f --no-tail
```

### 4.3 HTTP Endpoint Probe Matrix

| Command | Target | Expected Status | Purpose |
| :--- | :--- | :--- | :--- |
| `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8081/health` | Router | `200` | Basic liveness probe. |
| `curl -s http://localhost:8081/v1/models \| jq .` | Router | `200` | Lists active model aliases. |
| `curl -s http://localhost:8081/slots \| jq .` | Router | `200` | Displays context utilization per slot. |
| `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/health` | Vision Server | `200` | OCR server liveness probe. |
| `curl -s http://localhost:11434/api/tags \| jq .` | Ollama | `200` | Lists local Ollama models. |
| `curl -s http://localhost:8081/props \| jq .` | Router | `200` | Displays server build flags and hardware offload status. |

---

## 5. Configuration Schema & YAML Knobs

### 5.1 Pipeline Configuration (`.env.yml`)

```yaml
# Global Endpoint Definitions
endpoints:
  architect_api_base: "http://192.168.100.2:8081/v1"   # String: OpenAI-compatible router endpoint
  editor_api: "http://127.0.0.1:11434/v1"               # String: Injected as OLLAMA_API_BASE and LM_STUDIO_API_BASE
  editor_api_fallback: "http://192.168.100.2:8081/v1"  # String: Fallback endpoint for test escalation
  weak_model_api_base: "http://192.168.100.2:8081/v1"  # String: Endpoint for repo-map / commit summaries
  ocr_api_base: "http://192.168.100.2:8080/v1"         # String: Vision OCR server endpoint
  embed_api_base: "http://192.168.100.2:8080/v1"       # String: Vector embedding endpoint
  ranking_api_base: "http://192.168.100.2:8080/v1"     # String: Cross-encoder reranker endpoint

# Global Model Dispatch Definitions
models:
  architect_agent: "openai/qwen3.6-27b-90k:LATEST"     # String: Primary reasoning & planning model
  editor_agent: "ollama/qwen2.5-coder:32b"             # String: Code editing & SEARCH/REPLACE model
  editor_agent_test: "ollama/qwen2.5-coder:32b"        # String: Test suite authoring model
  editor_agent_test_fallback: "openai/qwen3.6-27b-90k:LATEST" # String: Escalation model on test failures
  weak_model: "openai/qwen2.5-coder:7b"                # String: Commit messages & repo map parsing
  rag_agent: "openai/qwen3.6-27b-90k:LATEST"           # String: Knowledge Oracle RAG model
  ocr_agent: "glm-ocr-f16:LATEST"                      # String: Document rasterization & OCR model
  embed_model: "BAAI/bge-m3"                           # String: LanceDB embedding model
  ranking_agent: "BAAI/bge-reranker-large"             # String: Cross-encoder ranking model

# Global RAG Ingestion Controls
rag:
  embed_backend: "openai"                              # Enum: "openai" | "sentence-transformers"
  embed_api_base: "http://192.168.100.2:8080/v1"       # String: Direct HTTP embedding endpoint
  chunk_size_chars: 1500                               # Integer: Target document chunk character size
  chunk_overlap_chars: 300                             # Integer: Chunk overlap boundary
```

### 5.2 Aider Subprocess Configuration (`.aider.conf.yml`)

```yaml
architect: true
model: "openai/qwen3.6-27b-90k:LATEST"
editor-model: "ollama/qwen2.5-coder:32b"
edit-format: "diff"
map-tokens: 2048
map-refresh: "auto"
cache-prompts: true
auto-commits: true
yes-always: true
check-update: false
show-release-notes: false
analytics: false
```

### 5.3 Aider Model Settings Overrides (`.aider.model.settings.yml`)

```yaml
- name: openai/qwen3.6-27b-90k:LATEST
  edit_format: diff
  use_repo_map: true
  examples_as_sys_msg: true     # Locks examples into the system prompt for KV cache preservation
  caches_by_default: true       # Enables prompt prefix caching
  extra_params:
    think: false                # Suppresses thinking token generation
    thinking_tokens: 0          # Enforces 0 reasoning tokens for fast CLI execution
    temperature: 0.1            # Ensures deterministic code generation
    max_tokens: 8192

- name: ollama/qwen2.5-coder:32b
  edit_format: editor-diff
  use_repo_map: false
  examples_as_sys_msg: true
  caches_by_default: false
  extra_params:
    temperature: 0.0
```

### 5.4 Multi-Model Server Registry (`models.ini`)

```ini
[qwen3.6-27b-90k:LATEST]
model = /var/models/qwen3.6-27b-instruct-q4_k_m.gguf
ctx_size = 90112
n_gpu_layers = 999

[glm-ocr-f16:LATEST]
model = /var/models/glm-4v-9b-ocr-f16.gguf
ctx_size = 32768
n_gpu_layers = 999
mmproj = /var/models/glm-4v-9b-ocr-mmproj.gguf
```

---

## 6. Operational Edge Cases, Failure Modes & Telemetry

| Error Signature / Symptom | Root Cause | Diagnosis & Verification | Mitigation / Recovery Procedure |
| :--- | :--- | :--- | :--- |
| **`400 Bad Request: request exceeds the available context size`** | Total prompt tokens exceed the per-slot context budget $C_{\text{slot}}$. | Run `curl http://localhost:8081/slots` to inspect per-slot limits. | Reduce `--parallel`, increase `--ctx-size`, or set `map_tokens: 1024` and `max_chat_history_tokens: 8000`. |
| **`400 Bad Request: model not found`** | Case mismatch between `.env.yml` model name and `models.ini` header. | Compare `curl http://localhost:8081/v1/models` against `.env.yml`. | Ensure matching letter casing (e.g., `LATEST` vs `latest`). |
| **Silent RAG Fallback (`[knowledge base unavailable]`)** | Embedding server port conflict or model eviction under `--models-max 1`. | Check `curl http://localhost:8080/v1/models` and `journalctl -u llama-vision`. | Increase `--models-max 2` or run a dedicated embedding instance. |
| **Stalled Debate Turns / Unresponsive Arbiter** | Reasoning model is outputting thousands of thinking tokens before generation. | Inspect `journalctl -u llama-pair-router -f` for token output. | Add `think: false` and `thinking_tokens: 0` in `.aider.model.settings.yml`. |
| **Socket Connection Refused on Weak Model** | Cloud weak model (`gemini/...`) was erroneously passed a local IP base. | Check environment dump for `WEAK_MODEL_API_BASE`. | Verify `env_utils.is_local_model()` triggers, resetting `weak_model_api_base` to `None`. |
| **OOM / Out of VRAM on Server Startup** | Combined weights and KV cache exceed total GPU memory. | Run `rocm-smi` or `nvidia-smi` during daemon startup. | Enable 8-bit KV caching (`--ctk q8_0 --ctv q8_0`) or lower `--ctx-size`. |
| **Editor Routing Failure on LM Studio Models** | Aider defaults to Ollama endpoint when given `lm_studio/` prefix. | Check active environment variables for `LM_STUDIO_API_BASE`. | Verified by orchestrator dual injection setting both `OLLAMA_API_BASE` and `LM_STUDIO_API_BASE`. |
