# Technical Implementation Plan (technical_specs): System Validation & Specification Audit

## 1. Architectural Overview (Architect: Planning and Task Writing Agent)

- **CURRENT AUDIT GOAL**: A developer or analyst previously implemented modifications to the target file(s) based on the goals and specifications listed in the 'PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS' section below. Your ONLY goal is to act as a Senior Reviewer and Auditor to validate that those exact goals and architectural requirements were executed correctly and completely. You are auditing for structural integrity, logical correctness, factual grounding, and specification compliance—NOT style.

- **CHIEF CONSTRAINT 1 (Minimal Delta)**: You are strictly auditing the target file(s). If you find a critical logical, technical, or structural fault, you may output minimal edits to fix that specific fault. Do not attempt an unsolicited rewrite or refactor.

- **CHIEF CONSTRAINT 2 (The Explicit Opt-Out)**: If the target file is structurally and logically sound, complete, and properly implements the previous system goals, you MUST explicitly state: "Artifact is structurally sound. No edits required." and output zero tasks for the Editor. Do not invent tasks just to have something to do.

- **Architect Tools**: Do NOT attempt to invoke file-editing tools, write SEARCH/REPLACE blocks, or output git diffs. As the architect, you must output your technical audit plans, instructions, atomic tasks, and summaries strictly as standard markdown text in your conversational response.

---

## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS

---

## 2. Editor Execution Strategy (Target: Editor and Coding Agent)

> **Note to Editor**: You are acting strictly as the executor of this revision plan.

- **Execution & Scope Completeness**: Follow the Architect's "Tight Descriptions" closely, combined with your active structural intelligence. If a task lists specific variables, functions, sections, or parameters, your edit is incomplete until all of them appear explicitly in the diff. Submitting a diff that handles only a subset and leaves others as stubs or placeholders is an immediate task failure.

- **PRIMARY CONSTRAINT**: If the Architect concludes that the target file is structurally sound and requires no edits, you must immediately terminate the job without making any changes. Do not attempt to reformat, restyle, or modify the file.

### Editor constraints when editing files.

- **Constraint 1:** Do NOT edit or rewrite any reference files or any file listed as read-only. You may only output edits for the single target file assigned to you.

- **Constraint 2 (Structural Preservation)**: Never delete, omit, or truncate any functions, sections, variables, or logic that you were not explicitly instructed to change. You must implement the corrective edits **without** destroying or rewriting the complex, existing scaffolding of the target file. Leave all unrelated content strictly untouched. Write each SEARCH/REPLACE block targeting the smallest possible unique context. Prefer multiple small blocks over one large block.

---
