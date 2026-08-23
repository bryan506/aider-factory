# AI Factory Helper, Terminal Assistant & Skills Framework

> **Context Anchor & Authoring Directive:**  
> This document is the definitive master specification for the `aider-helper` CLI, interactive workspace onboarding, general AI terminal assistance, and the modular skills injection system.  
> **Source References:** `factory_service_manual.md` under headers `### AI Factory Helper (aider-helper)`, `### AI Factory Helper & Terminal Agent (aider-helper)`, `### The Oracle Session`, `#### Skills (CLI + Skill framework)`.  
> **Codebase References:** `src/aider_factory/python/bootstrap.py`, `src/aider_factory/cli.py` (`helper_cli`), `src/aider_factory/markdown/skills/`.  
> **Target Scope to Reconcile:**  
> 1. **Dual Operating Personas:** (a) Configuration Architect mode (YAML parsing & minimal-delta mutations) and (b) General AI Terminal Assistant mode (`--terminal` / `-t`).  
> 2. **Session Lifecycle & Append-Only KV Cache:** Document `.helper_session.json` vs `.helper_terminal_session.json`, prefix caching optimization on llama.cpp/vLLM, `--master`, `--expert`, `--repo-map`, and `--clear`.  
> 3. **Interactive Workspace Onboarding:** Detailed interview flow of `aider-helper bootstrap`.  
> 4. **Skills Injection Architecture:** Modular skill contracts under `markdown/skills/` delivered via `files.context_files_job`.  
> 5. **Mandatory 6-Section Topology:** Adhere strictly to `implement_docs.md`.
