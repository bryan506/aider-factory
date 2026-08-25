# High-Performance Inference Servers, Routing & Models Configuration

> **Context Anchor & Authoring Directive:**  
> This document is the definitive master specification for high-performance LLM/vision inference serving, dynamic endpoint prefix routing, context arithmetic, and model settings overrides.  
> **Source References:** `factory_service_manual.md` under headers `## Operating System & Core Dependencies`, `## High-Performance Inference Servers`, `### Understanding Model Prefix Routing`, `### llama.cpp Architecture Overview`, `### Aider Configuration: .aider.conf.yml`, `### Aider Model Overrides: .aider.model.settings.yml`, `### Aider Operational Flags and Chat History`, `## Appendix A: Required Environment Variables`, `### Verifying Service Health`, `### Common Errors and Fixes`.  
> **Codebase References:** `src/aider_factory/default_configs/env.yml`, `src/aider_factory/default_configs/aider.conf.yml`, `src/aider_factory/default_configs/aider.model.settings.yml`, `src/aider_factory/python/env_utils.py`.  
> **Target Scope to Reconcile:**  
> 1. **Dynamic Prefix Routing Matrix:** Full mechanics of `openai/`, `ollama/`, `lm_studio/`, `gemini/`, `vertex_ai/`, `github_copilot/` routing to `architect_api_base`, `editor_api`, `editor_api_fallback`, and cloud providers.  
> 2. **llama-server Dual Architecture & Context Math:** Router (port 8081) vs Vision/OCR (port 8080), slot arithmetic ($\text{Context Per Slot} = \frac{\text{ctx\_size}}{\text{parallel}}$), case-sensitive alias registry (`models.ini`), and remote clustering.  
> 3. **Model Configuration & Overrides:** Setting `think: false`, `caches_by_default: true`, `examples_as_sys_msg: true`, and reasoning budgets.  
> 4. **Operational Troubleshooting:** Health check commands (`curl`), slot exhaustion, CER-driven context sizing, and systemd units.  
> 5. **Mandatory 6-Section Topology:** Adhere strictly to `implement_docs.md`.

## 1. Executive Overview & Foundational Invariants

The AI Factory pipeline orchestrates multiple AI models simultaneously across diverse inference endpoints. This architecture relies on high-performance local serving (via `llama.cpp` and `ollama`) combined with seamless cloud provider integration.

### Foundational Invariants
- **Deterministic Prefix Routing**: Model traffic is routed automatically based on Aider's native prefix syntax (e.g., `openai/`, `ollama/`). The prefix dictates the API endpoint, bypassing hardcoded URLs in the prompt.
- **Strict Context Division**: Local `llama-server` instances divide their total context size evenly across parallel slots. A request exceeding the per-slot context limit will deterministically fail.
- **Case-Sensitive Alias Registry**: Model aliases in the `models.ini` registry are strictly case-sensitive. The YAML configuration must match the registry exactly (e.g., `glm-ocr-f16:LATEST`).
- **Reasoning Budget Control**: Local models must have their reasoning tokens explicitly disabled (`think: false`) via `.aider.model.settings.yml` when fast, deterministic CLI returns are required (e.g., for the RAG Oracle).

---

## 2. System Topology & Lifecycle Flowcharts

The pipeline typically runs two separate `llama-server` instances to isolate reasoning tasks from heavy vision/embedding workloads.

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          DUAL INFERENCE SERVER ARCHITECTURE                            │
├──────────────────────────────┬─────────────────────────────────────────────────────────┤
│ Primary Router (Port 8081)   │ Vision / OCR & Embedding (Port 8080)                    │
├──────────────────────────────┼─────────────────────────────────────────────────────────┤
│ • Endpoints: architect_api   │ • Endpoints: ocr_api_base, embed_api_base               │
│ • Models: Architect, Oracle  │ • Models: GLM-OCR, bge-m3, qwen-embedding               │
│ • Config: --parallel 3       │ • Config: Parallel OCR slots, dedicated context         │
│ • Purpose: Planning, RAG     │ • Purpose: Document ingestion, vector embedding         │
└──────────────────────────────┴─────────────────────────────────────────────────────────┘
```

### Prefix Routing Flowchart
```text
[Aider Session / Orchestrator]
       │
       ├── Prefix: `openai/` ───────► `architect_api_base` (e.g., http://192.168.100.2:8081/v1)
       │
       ├── Prefix: `ollama/` ───────► `editor_api` (e.g., http://localhost:11434/v1)
       │
       ├── Prefix: `lm_studio/` ────► `editor_api` (e.g., http://localhost:1234/v1)
       │
       └── Prefix: `gemini/` ───────► Direct API Routing (bypasses local endpoints, uses GEMINI_API_KEY)
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### 3.1 Model Prefix Routing Mechanics
The pipeline parses the `models` block in `.env.yml` and dynamically injects `OPENAI_API_BASE`, `OLLAMA_API_BASE`, etc., into the Aider subprocess environment based on the prefix. 

| Prefix | Backend | Endpoint Used | Notes |
| :--- | :--- | :--- | :--- |
| `openai/` | OpenAI-compatible (llama-server, LiteLLM) | `architect_api_base` | Routes to local `llama-server` or remote proxy. |
| `ollama/` | Ollama native API | `editor_api` | Local coding models via `ollama serve`. |
| `lm_studio/` | LM Studio | `editor_api` | Maps to the same editor endpoint. |
| `gemini/` | Google Gemini API | Bypasses endpoints | Uses `GEMINI_API_KEY`. |
| `vertex_ai/` | GCP Vertex AI | Bypasses endpoints | Uses GCP credentials. |
| `github_copilot/` | GitHub Copilot | Bypasses endpoints | Uses Copilot auth. |

### 3.2 Context Slot Arithmetic
`llama-server` divides the total `--ctx-size` evenly across `--parallel` slots. The maximum context available to any single request ($C_{req}$) is defined mathematically as:

$$C_{req} = \lfloor \frac{\text{ctx\_size}}{\text{parallel}} \rfloor$$

If an Architect prompt combined with source files exceeds $C_{req}$, the server will return a `400 Bad Request`. This is highly critical for vision models where image tokens consume massive context, and embedding models where input text length varies.

---

## 4. Exhaustive CLI & Parameter Reference

Service health and model availability must be verified using standard OS and HTTP tools.

| Command | Target | Purpose |
| :--- | :--- | :--- |
| `curl http://localhost:8081/health` | Primary Router | Verify Architect/Oracle server health. |
| `curl http://localhost:8080/health` | Vision/OCR Server | Verify Document ingestion server health. |
| `curl http://localhost:11434/api/tags` | Ollama | List available local Ollama models. |
| `systemctl status llama-pair-router.service` | systemd | Check daemon status for the primary router. |
| `systemctl status llama-vision.service` | systemd | Check daemon status for the vision/embedding server. |
| `journalctl -u llama-pair-router -f` | systemd | Tail live inference logs for the primary router. |

---

## 5. Configuration Schema & YAML Knobs

### 5.1 Pipeline Configuration (`.env.yml`)
The endpoints and models are defined globally or per-phase in `.env.yml`:

```yaml
endpoints:
  architect_api_base: "http://192.168.100.2:8081/v1"
  editor_api: "http://127.0.0.1:11434/v1"
  rag_agent_api: "http://192.168.100.2:8081/v1"
  ocr_api_base: "http://192.168.100.2:8080/v1"

phases:
  - name: "Implementation"
    models:
      architect_agent: "openai/qwen3.5-122b-a10b-90k:latest"
      editor_agent: "ollama/qwen2.5-coder:latest"
      rag_agent: "openai/qwen3.6-27b-90k:LATEST"
      ocr_agent: "glm-ocr-f16:LATEST"
```

### 5.2 Aider Model Overrides (`.aider.model.settings.yml`)
Model-specific reasoning budgets and KV-cache behaviors are forced via this file:

```yaml
- name: openai/qwen3.6-27b-90k:LATEST
  edit_format: editor-diff
  use_repo_map: true
  examples_as_sys_msg: true   # Locks instructions into the system block for cache retention
  caches_by_default: true     # Forces Aider to prefix-cache
  extra_params:
    think: false              # Strips reasoning tokens for speed
    thinking_tokens: 0
    temperature: 0.1          # Forces determinism
```

---

## 6. Operational Edge Cases, Failure Modes & Telemetry

| Failure Mode / Error Signature | Root Cause | Mitigation / Recovery Procedure |
| :--- | :--- | :--- |
| **`400 Bad Request: request exceeds the available context size`** | Input tokens exceed per-slot context on `llama-server` ($C_{req}$). | Increase `ctx-size` in `models.ini` or reduce `--parallel`. Verify query truncation limits. |
| **`400 Bad Request` with `model not found`** | Case-mismatch between `.env.yml` and `models.ini`. | Ensure the YAML `models:` entry exactly matches the `[section-name]` in `models.ini` (e.g., `LATEST` vs `latest`). |
| **Empty RAG context / `[knowledge base unavailable]`** | Embedding endpoint unreachable, or model evicted on `--models-max 1` servers. | Verify embedding server health (`curl <embed_api_base>/v1/models`). Increase `--models-max`. |
| **Slow Oracle CLI returns** | Model is streaming `<think>` tokens to stdout. | Ensure `think: false` and `thinking_tokens: 0` are set in `.aider.model.settings.yml` for the `rag_agent`. |
| **`permission denied: /run` during a session** | Model emitted `/run` inside a shell block instead of a bare command. | Aider's `architect` mode blocks shell execution. Use the programmatic `oracle` job or type `/run` manually in pair mode. |
