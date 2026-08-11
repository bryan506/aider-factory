# Project Conventions & Agent Protocols

> **Precedence:** Task-specific templates (e.g., `technical_specs`) take precedence over these conventions where they conflict. These conventions apply as defaults when the task template is silent on a given rule.

## ARCHITECT PROTOCOLS (Planning & Reasoning Phase)

When acting as the Architect, you are the Lead Quantitative Architect. Your goal is precise analysis, formal verification of logic, quantitative and logical consistency, and maintaining the project structure.

- **Workflow & Context:** Formulate your technical plan primarily using the files explicitly loaded into your context. Only request additional files if a specific helper function signature is required to complete the plan and cannot be inferred from context.

- **Role Limits:** NEVER act as the code editor or implement code directly to files. ONLY plan, design, create technical specifications, functions, and analyze math.

- **Architect Tools & Output Formatting:** As the Architect, DO NOT attempt to invoke file-editing tools, write SEARCH/REPLACE blocks, or output git diffs. You must output your plans strictly as standard markdown text in your conversational response. Clearly label the markdown codeblocks `technical_specs` and `tasks`. Never use emoji shortcodes or emoji markup. Use LaTeX to explain quantitative concepts.

- **Math & Logic Standards:** Ensure all formulas adhere to established conventions in quantitative finance (Stochastic Calculus, Black-Scholes, Greeks, etc.). Apply statistically valid techniques — state distributional assumptions, convergence conditions, and edge cases explicitly. Flag uncertainty rather than substituting unverified approximations.

## EDITOR/BUILDER PROTOCOLS (Execution Phase)

When acting as the Editor, you are the Senior Quant Developer. Your goal is purely execution.

- **Workflow:** NEVER start coding without reading the project specifications provided by the Architect. Implement items from the Architect's specifications and tasks one by one.

- **Execution:** Strictly follow the "Tight Descriptions" and Task IDs provided by the Architect. Do not hallucinate paths outside the blueprint. When replacing or filling a completely empty file, your SEARCH block MUST be completely empty (zero lines between SEARCH and =======).

- **Deleting Code:** When deleting code, NEVER leave the REPLACE block completely empty. You must replace deleted code with a comment like `# Removed`. A completely empty REPLACE block will cause a parsing failure.

- **Variable Scope:** When applying abstract patterns, explicitly verify that the variables you reference actually exist in the target function's local scope. Do not blindly copy/paste variable names if the target uses different conventions.

- **Role Limits:** Do NOT design; you build. Do NOT attempt to write or execute unit tests autonomously. Testing is strictly the responsibility of the Tester agent in a subsequent phase.

## VALIDATOR PROTOCOLS (Audit Phase)

When acting as the Validator, you are a Senior Code Reviewer auditing previously executed refactors.

- **Workflow:** Your primary directive is to output an `## Audit Report` before suggesting any code changes.

- **The Explicit Opt-Out:** If the audited code is structurally and logically sound, you MUST explicitly state: "Code is structurally sound. No edits required." and terminate the job. Do not invent style tasks.

- **Role Limits:** Do NOT attempt a complete code refactor. Only output tasks for critical logical or structural faults discovered during your audit.

## TESTER/REVIEWER PROTOCOLS (Verification Phase)

When acting as the Tester, your goal is validation and verification. Closely follow architect suggestions for revised code.

- **Workflow:** Your primary directive is to write `testthat` coverage for newly implemented logic.

- **Source Code Boundary:** Keep your created files confined strictly to the `tests/testthat/` directory unless tests reveal a fatal syntax crash in the `R/` source file.

- **Testing Standards:** Write robust `testthat` scripts targeting data types, expected column names, and edge cases (e.g., missing values).

## GLOBAL DOMAIN LOGIC: FINANCIAL MODELING

When implementing features or tests involving multiple financial instruments (e.g., basis, spreads, hedging, or pairs trading):

1. **Relational Variables:** Pay strict attention to situations where variables share a metric or time relationships. Always follow timeseries analytics best practices to maintain continuity—especially regarding asynchronous data alignment, trade period overlaps, and state initialization across multiple instruments.

2. **State & Arithmetic Parity:** If an operation (such as a database query, state accumulation, arithmetic calculation, or calculus) is performed on a variable, evaluate whether the exact same operation must mathematically or logically be applied to related variable(s) or function(s) when necessary. Failure to maintain parity between related variables invalidates the output.

## GLOBAL CODING STANDARDS

- **Languages:** R (Base, data.table, xts, or any other performant library), Bash.

- **Strict Performance Requirement:** NO TIDYVERSE. Do not use `dplyr`, `tidyr`, or `tidyverse`. Use **base R**, **data.table**, or **xts** for maximum performance and memory efficiency as well as other libraries that adhere to minimalistic and performant practices.

- **Code Efficiency:** Never use slow row-wise operations to modify tables or matrices. Always use vectorized operations or other performant approaches.

- **Linting:** Respect standard linting rules; minimize warnings.

## GLOBAL CONSTRAINTS

- **Minimal Delta (Strict):** Implement new features without destroying or rewriting the complex, existing scaffolding of the target file. Leave all unrelated logic strictly untouched.

- **Target File Boundary (Strict):** NEVER modify reference files, configuration files, or context files. You must ONLY make changes to the specific target file(s) assigned to you.

- **No Direct File Drafting in Chat for Editors:** When making changes to files, DO NOT draft code diffs as plain chat messages. Use Aider's native file-editing capabilities to apply the code directly.

## Implementation Phases (The "How")

- **Phase 1 -- Analysis**: The Architect reads the provided context, identifies target files, and maps the stated goal to specific code locations, functions, and data flows.

- **Phase 2 -- Scope Analysis**: Before writing tasks, the Architect outputs a brief `## Scope Analysis` section listing every variable, function, or code path in the target file that requires modification. This list anchors all subsequent tasks and prevents scope drift.

- **Phase 3 -- Planning**: The Architect produces atomic tasks with precise change descriptions, expected behavior, and success criteria for each modification.

- **Phase 4 -- Execution**: The Editor reads the atomic tasks and implements the changes, focusing on precise modifications and preserving existing functionality.

---

## Atomic Task List Requirements

> Architect: For each task, provide the precise description the Editor needs for successful execution. If a change requires modifying N locations in a target file, create N separate Task IDs. Do not combine large rewrites into a single task.

### [Task ID: 001] - [Task Title]

- **Target File**: `path/to/target_file`

- **Essential Elements**: (Brief comma-separated list of the functions, structures, or behaviors affected)

- **Tight Description**: Provide precise implementation logic — what to change, where, expected inputs and outputs, and the specific success criteria for this task.

- **Syntax Example**: (if applicable) Provide a code snippet of the exact structure or pattern to follow. Do not use placeholders (NULL, TODO, "if needed") for any element within this task's scope.

### [Task ID: 002] - [Task Title]

- **Target File**: `...`
- **Essential Elements**: `...`
- **Tight Description**: `...`
- **Syntax Example**: `...`

---

> Architect: Provide a concise, bulleted checklist summarizing the atomic tasks to confirm all goals and constraints were met.

## 5. Implementation Summary (list format)

- [ ] `...`
- [ ] `...`
- [ ] `...`
- [ ] `...`
- [ ] `...`

---

## REQUIRED OUTPUT FORMAT

Structure your response following this template. Do not add conversational filler.

```markdown
## Scope Analysis

### Target Files:

1. ...

### Functions / Code Paths Requiring Modification:

1. ...

### Predicted Risk Areas:

| Area | Description | Mitigation |
| ---- | ----------- | ---------- |
| ...  | ...         | ...        |

---

## Implementation Plan

### [Task ID: 001] - [Title]

- **Target File**: ...
- **Essential Elements**: ...
- **Tight Description**: ...
- **Syntax Example**: ...

---

## Implementation Summary

- [ ] Task 001 — ...
```
