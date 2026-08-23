# AI Factory Core Philosophies & Engineering Invariants

> **Context Anchor & Authoring Directive:**  
> This document is the definitive master specification for the AI Factory's 13 foundational engineering invariants and load-bearing rules.  
> **Source Reference:** `factory_service_manual.md` under header `## Core Philosophies (the foundation — do not violate)` and `.aider_factory/CONVENTIONS.md`.  
> **Target Scope to Reconcile:**  
> 1. **The 13 Load-Bearing Invariants:** (1) Deterministic-first architecture, (2) Provable truth & precision over recall (no fuzzy/Levenshtein for grounding), (3) Embeddings as annotation-only, (4) Strict tag promotion guards (no deletions/auto-sentinels), (5) Deterministic validator tag authority, (6) Minimal-delta edits, (7) Full cross-validation after every change, (8) Splittable & combinable DAG order-independence, (9) No pipeline git commits except Aider auto-commits, (10) Single bundled Python interpreter runtime (`AIDER_PY`), (11) Native Aider framework integration, (12) Reactive ground-truth Knowledge Oracle, (13) Plain, objective communication.  
> 2. **Execution & Language-Agnostic Chassis:** Formalize how the single `produce → verify → escalate → finalize` skeleton applies uniformly across review documents, Python, R, Rust, Go, and Java.  
> 3. **Mandatory 6-Section Topology:** Adhere strictly to `implement_docs.md` (Overview $\rightarrow$ Flowcharts $\rightarrow$ Deep Mechanics $\rightarrow$ CLI Matrix $\rightarrow$ YAML Schema $\rightarrow$ Diagnostics).
