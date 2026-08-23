# Full-Stack Observability, Master Logging & Cost Accounting

> **Context Anchor & Authoring Directive:**  
> This document is the definitive master specification for full-stack telemetry, low-level OS file descriptor multiplexing, structured run ledgers, and token/financial cost accounting.  
> **Source References:** `factory_service_manual.md` under headers `### Cost Reporting`, `### Artifact & Log Directory Map`, `### Comprehensive Observability, Master Logging & Telemetry Engine`.  
> **Codebase References:** `src/aider_factory/python/run_workflow.py` (`OSTee`), `src/aider_factory/python/aggregate_costs.py`, `src/aider_factory/python/cost_tracker.py`.  
> **Target Scope to Reconcile:**  
> 1. **Kernel-Level Stream Multiplexing (`OSTee`):** OS pipe duplication (`os.dup2(pipe_w, 1)`, `os.dup2(pipe_w, 2)`), C-extension/subprocess capture, and zero-loss streaming to `.aider_factory/logs/*_run_*.log`.  
> 2. **The 3 Synchronized Observability Tiers:** (1) Live interactive ANSI terminal stream, (2) Master terminal recording log (`less -R`), (3) Structured disk artifacts (chat archives, oracle transcripts, debate ledgers, validation reports).  
> 3. **Vector Database & Chunking Telemetry:** AST symbol resolution traces, Docling subprocess logs, and LanceDB index building metrics.  
> 4. **Financial Cost Accounting:** Token-by-token parsing regex (`Tokens: Nk sent... Cost: $X.XX`), USD aggregation across models, and pair programming `script -qfe` capture.  
> 5. **Mandatory 6-Section Topology:** Adhere strictly to `implement_docs.md`.
