# Interaction Templates & Prompt Engineering Architecture

> **Context Anchor & Authoring Directive:**  
> This document is the definitive master specification for prompt engineering, template tiering, YAML path resolution rules, and dynamic context injection in the AI Factory pipeline.  
> **Source References:** `factory_service_manual.md` under headers `### Interaction Templates (User-Customizable Prompts)`, `#### Path Resolution Rules`, `#### Template Directory Map`, `#### Writing Custom Templates`.  
> **Codebase References:** `src/aider_factory/markdown/templates/`, `src/aider_factory/markdown/internal/`, `src/aider_factory/markdown/oracle_pre_plan/`, `src/aider_factory/python/run_workflow.py`.  
> **Target Scope to Reconcile:**  
> 1. **The 3-Tier Template Hierarchy:** (a) User-customizable (`templates/`), (b) Infrastructure & Parsing-contract (`internal/` — `PROPOSAL:`, `VERDICT:`, tag semantics), (c) Strategy workflow (`oracle_pre_plan/`).  
> 2. **YAML Path Resolution Rules:** Relative scoping differences between phase `plans:` (relative to `.aider_factory/`) vs phase `oracle:` (relative to `working_directory`).  
> 3. **Dynamic Plan Splicing:** How `run_workflow.py` automatically injects `job_one_plan` into `job_two_plan` (`validate.md`) under `## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS`.  
> 4. **Prompt Engineering & Negative Constraints:** Persona design (imperative second-person Architect/Validator), anti-stub rules, and zero-placeholder guarantees.  
> 5. **Mandatory 6-Section Topology:** Adhere strictly to `implement_docs.md`.
