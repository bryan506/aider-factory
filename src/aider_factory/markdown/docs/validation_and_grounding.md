# Deterministic Validation, Grounding & MiniCheck Entailment

> **Context Anchor & Authoring Directive:**  
> This document is the definitive master specification for exact-substring quote grounding, deterministic auto-fix repair, the tag state machine, MiniCheck entailment verification, and raw text validation.  
> **Source References:** `factory_service_manual.md` under headers `## The Validation System (Evidence Grounding)`, `### The idea: the quote is a tripwire`, `### The tags are the state`, `### Quote grounding — provable, deterministic, free`, `### Region grounding + heal loop`, `### Deterministic auto-fix — the cheapest repair`, `### Escalation: the two-party deliberation (the debate)`, `### Apply the verdict, then finalize`, `### The moving parts (reference)`, `### Quirks worth knowing`, `### Cross-validation matrix — features <-> configuration`, `### Entailment-grounded claim verification (the MiniCheck grounding verifier)`, `### Academic Foundations & Literature References`, `### Raw Text Validation (--claims-only)`.  
> **Codebase References:** `src/aider_factory/python/validator.py`, `src/aider_factory/python/minicheck_server.py`, `src/aider_factory/tests/validations/validations_context_check.sh`, `src/aider_factory/tests/validations/apply_evidence.sh`.  
> **Target Scope to Reconcile:**  
> 1. **Deterministic Quote Grounding:** Normalized exact-substring matching ($0 LLM cost), tripwire architecture, LaTeX/soft-quote handling, and Sentinel exemption (`"not specified in paper"`).  
> 2. **Grounding Tag State Machine:** Strict transitions (`[evidence]`, `[validated]`, `[fixed]`, `[unsupported]`), validator-only write authority, and the anchor deletion guard baseline.  
> 3. **Deterministic Auto-Fix Engine:** Ellipsis splice repair (`...`), gap threshold ($\le 200$ chars), and surrounding claim gate validation.  
> 4. **MiniCheck Entailment Verifier & Server Shim:** Sentence-level weakest-link entailment ($\min P(\text{Entailed})$), OpenAI-compatible HTTP shim (`minicheck_server.py`), and systemd service setup.  
> 5. **Raw Text Validation (`--claims-only`):** Paragraph extraction, LanceDB RRF retrieval, and automated hallucination scoring.  
> 6. **Academic Foundations & Citations:** Cormack (RRF), Morris/Levenshtein (CER), Zhang/Honovich (MiniCheck/TRUE).  
> 7. **Mandatory 6-Section Topology:** Adhere strictly to `implement_docs.md`.
