# Technical Implementation Plan (technical_specs): KV Refactoring Validation

## 1. Architectural Overview (Architect: Planning and Task Writing Agent)

- **CURRENT AUDIT GOAL**: An analyst previously refactored the target `R/` file based on the goals listed in the 'PREVIOUS COMPLETED SYSTEM GOALS' section below. Your ONLY goal is to act as a Senior Code Reviewer and validate that those exact goals were executed correctly. You are auditing for structural integrity and logical correctness, NOT style.

- **CHIEF CONSTRAINT 1 (Minimal Delta)**: You are strictly auditing the file. If you find a critical logical or structural fault, you may output minimal edits to fix that specific fault. Do not attempt a complete code refactor.

- **CHIEF CONSTRAINT 2 (The Explicit Opt-Out)**: If the code is structurally and logically sound, and properly implements the previous system goals, you MUST explicitly state: "Code is structurally sound. No edits required." and output zero tasks for the Editor. Do not invent tasks just to have something to do.

- **Architect Tools**: Do NOT attempt to invoke file-editing tools, write SEARCH/REPLACE blocks, or output git diffs. As the architect, you must output your technical audit plans, instructions, atomic tasks, and summaries strictly as standard markdown text in your conversational response.

---

## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS

- System Goal: Adapt the relevant patterns from `fut_aac_l()` to the source script `R/lq_leverage.R`. The function `lq_leverage_l()` and its corresponding business logic function `leverage_lq()` are dependent on the POSITION feature and use `futNotionalValue` to compute liquidity, leverage, and other risk metrics found in `R/lq_leverage.R`. Apply domain knowledge of basis trading and risk computation to understand the business logic and adapt the code accordingly. As the architect, you are responsible for ensuring `R/lq_leverage.R` retains its own unique logic where necessary and adopts the efficiencies of `fut_aac_l()` only where it makes logical sense.

- Architectural Pattern: Identify the helper functions, efficiency code paths, and structural patterns in `fut_aac_l()` that are reusable and apply them to `lq_leverage_l()`.

- Action: Analyze `fut_aac_l()` and `lq_leverage_l()` to identify which parts are reusable and which are specific to each function. Apply the reusable parts only to `lq_leverage_l()` and refactor the specific parts of `lq_leverage_l()` accordingly.
  1. Ensure we properly use necessary variables at the top of `lq_leverage_l()`. Remove the unused ones and keep only the ones needed for the function's logic.
  2. Respect the workflow of `algo_start_time` and `algo_end_time`, make use of `current_minute_floor` where necessary. Adapt the time-related workflow to the specific needs of `lq_leverage_l()`.
  3. Use the naming conventions for columns so we only set the column names at the top of the script as shown in `fut_aac_l()`. This will make subsetting by columns and dynamic renaming easier in the future.
  4. Use a minimal delta approach and do not rename variables unnecessarily. If anything we want to establish reusable patterns or helper functions that could be applied to `lq_leverage_l()` and other functions, so reusing names where possible is encouraged.
  5. There are artifacts still in `lq_leverage_l()` from `fut_aac_l()` that should be refactored out and do not make sense in the context of `lq_leverage_l()`. Use your domain knowledge of basis trading between a futures leg and a spot leg to identify what is relevant and what must be removed.

- Unique Workflow Notes: The following are architectural choices that will need to be addressed. Likely they will have to be removed, but if you determine otherwise, justify the decision in your implementation plan.
  1. Replay logic may not be necessary. Remove replay logic from `lq_leverage_l()`. We may rely on the fact that since `LEVERAGE_LQ` is dependent on `POSITION`, that we will always write metrics for `LEVERAGE_LQ` based on the latest `POSITION` metrics needed to calculate the `LEVERAGE_LQ` features in `lq_leverage()`. The `lq_leverage_l()` function will gracefully exit (as is already implemented) if `POSITION` metrics are not available.
  2. Remove any unused variables or artifacts from `lq_leverage_l()`.
  3. `process_feature_event` needs to include the proper assignments for `leverage_lq` and columns and other relevant variables.
  4. Everything below the comment `# Pack KV values for all features` is going to need to be reworked. We might only need the KV packing logic once so ensure we are not being redundant.
  5. Everything below the comment `# Add metadata columns` in `lq_leverage_l()` should stay as is since those are global metadata column assignments.

- Constraint 1: Do not change the existing `lq_leverage_l()` business logic or implementation semantics beyond what is strictly required to complete the `lq_leverage_l()` workflow. WE WILL ONLY BE FOCUSING ON CHANGES TO `lq_leverage_l()` and `lq_leverage()`.

- Constraint 2: Only compute leverage, liquidity, and risk metrics when the required POSITION data and `futNotionalValue` inputs are available in-memory during the current workflow. The implementation must not query TimeBase for pre-existing leverage or risk events. Handle missing or partial inputs by gating computation — do not substitute defaults or fabricate values for unavailable inputs.

- Constraint 3: All KV unpacking and packing must happen exactly once per workflow stage, with shared reused objects instead of duplicate queries or duplicate transforms.\*\* Reuse unpack needed KV values before business logic, and pack all feature outputs once at the end using existing helpers such as `process_feature_event()`, `kv_dec()`, or `kv_values()`.

- Constraint 4: Never substitute `0` for missing price-like or derived economic state fields.
  - Missing price-like or derived economic state should remain `NA_real_` or be carried forward from valid prior state when appropriate
  - Only truly additive event-local quantity fields may use `0` as a safe default, and only when zero is semantically correct

---

## 2. Editor Execution Strategy (Target: Editor and Coding Agent)

> **Note to Editor**: You are acting strictly as the executor of this revision plan.

- **Execution & Variable Expansion**: Follow the Architect's "Tight Descriptions" closely, combined with your active structural intelligence. If a task's Scope Variables field lists multiple variables, your edit is incomplete until all of them appear explicitly in the diff. Submitting a diff that handles only one scoped variable and leaves others as NULL or stubs is a task failure.

- **PRIMARY CONSTRAINT**: If the Architect concludes that the file is structurally sound and requires no edits, you must immediately terminate the job without making any changes. Do not attempt to format, lint, or stylize the code.

### Editor constraints when editing files.

- **Constraint 1:** Do NOT edit or rewrite any reference files or any file listed as read-only. You may only output edits for the single target file assigned to you.

- **Constraint 2 (Code Preservation)**: Never delete, omit, or truncate any functions, variables, or logic that you were not explicitly instructed to change. You must implement the new code features **without** destroying or rewriting the complex, existing scaffolding of the target file. Leave all unrelated logic strictly untouched. Write each SEARCH/REPLACE block targeting the smallest possible unique context. Prefer multiple small blocks over one large block.

---
