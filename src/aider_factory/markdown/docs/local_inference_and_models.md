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
