# Technical Implementation Plan (technical_specs): Spread Feature KV refactoring

## 1. Architectural Overview (Architect: Planning and Task Writing Agent)

- **System Goal**: Adapt the relevant patterns from `fut_aac_l()` to the source script `R/lq_leverage.R`. The function `lq_leverage_l()` and its corresponding business logic function `leverage_lq()` are dependent on the POSITION feature and use `futNotionalValue` to compute liquidity, leverage, and other risk metrics found in `R/lq_leverage.R`. Apply domain knowledge of basis trading and risk computation to understand the business logic and adapt the code accordingly. As the architect, you are responsible for ensuring `R/lq_leverage.R` retains its own unique logic where necessary and adopts the efficiencies of `fut_aac_l()` only where it makes logical sense.

- **Architectural Pattern**: Identify the helper functions, efficiency code paths, and structural patterns in `fut_aac_l()` that are reusable and apply them to `lq_leverage_l()`.

- **Action**: Analyze `fut_aac_l()` and `lq_leverage_l()` to identify which parts are reusable and which are specific to each function. Apply the reusable parts only to `lq_leverage_l()` and refactor the specific parts of `lq_leverage_l()` accordingly.
  1. Ensure we properly use necessary variables at the top of `lq_leverage_l()`. Remove the unused ones and keep only the ones needed for the function's logic.
  2. Respect the workflow of `algo_start_time` and `algo_end_time`, make use of `current_minute_floor` where necessary. Adapt the time-related workflow to the specific needs of `lq_leverage_l()`.
  3. Use the naming conventions for columns so we only set the column names at the top of the script as shown in `fut_aac_l()`. This will make subsetting by columns and dynamic renaming easier in the future.
  4. Use a minimal delta approach and do not rename variables unnecessarily. If anything we want to establish reusable patterns or helper functions that could be applied to `lq_leverage_l()` and other functions, so reusing names where possible is encouraged.
  5. There are artifacts still in `lq_leverage_l()` from `fut_aac_l()` that should be refactored out and do not make sense in the context of `lq_leverage_l()`. Use your domain knowledge of basis trading between a futures leg and a spot leg to identify what is relevant and what must be removed.

- **Unique Workflow Notes**: The following are architectural choices that will need to be addressed. Likely they will have to be removed, but if you determine otherwise, justify the decision in your implementation plan.
  1. Replay logic may not be necessary. Remove replay logic from `lq_leverage_l()`. We may rely on the fact that since `LEVERAGE_LQ` is dependent on `POSITION`, that we will always write metrics for `LEVERAGE_LQ` based on the latest `POSITION` metrics needed to calculate the `LEVERAGE_LQ` features in `lq_leverage()`. The `lq_leverage_l()` function will gracefully exit (as is already implemented) if `POSITION` metrics are not available.
  2. Remove any unused variables or artifacts from `lq_leverage_l()`.
  3. `process_feature_event` needs to include the proper assignments for `leverage_lq` and columns and other relevant variables.
  4. Everything below the comment `# Pack KV values for all features` is going to need to be reworked. We might only need the KV packing logic once so ensure we are not being redundant.
  5. Everything below the comment `# Add metadata columns` in `lq_leverage_l()` should stay as is since those are global metadata column assignments.

- **Architect Tools**: Do NOT attempt to invoke file-editing tools, write SEARCH/REPLACE blocks, or output git diffs. As the architect, you must output your technical implementation plans, instructions, atomic tasks, and summaries strictly as standard markdown text in your conversational response.

- **Constraint 1**: Do not change the existing `lq_leverage_l()` business logic or implementation semantics beyond what is strictly required to complete the `lq_leverage_l()` workflow. WE WILL ONLY BE FOCUSING ON CHANGES TO `lq_leverage_l()` and `lq_leverage()`.

- **Constraint 2**: Only compute leverage, liquidity, and risk metrics when the required POSITION data and `futNotionalValue` inputs are available in-memory during the current workflow. The implementation must not query TimeBase for pre-existing leverage or risk events. Handle missing or partial inputs by gating computation — do not substitute defaults or fabricate values for unavailable inputs.

- **Constraint 3**: All KV unpacking and packing must happen exactly once per workflow stage, with shared reused objects instead of duplicate queries or duplicate transforms.\*\* Reuse unpack needed KV values before business logic, and pack all feature outputs once at the end using existing helpers such as `process_feature_event()`, `kv_dec()`, or `kv_values()`.

- **Constraint 4 (Reference Strictness)**: Treat referenced files strictly as syntactic references for how existing functions and code structures accomplish similar goals. Do not port the referenced files' mathematical logic or variable names into the target file — the target may require its own unique logic.

- **Constraint 5 (Minimal Delta)**: Modify only the specific code necessary to replace the legacy structures with the new approach. Outline the new code features **without** destroying or rewriting the complex, existing scaffolding of the target file. Leave all unrelated logic strictly untouched.

- **Constraint 6 (Scope and Focus)**: Do not suggest, plan, or imply edits to any reference file or any file listed in your context that is not the target file. You may only architect, plan, and outline changes for the specific target file assigned to this task. You are responsible for keeping the coding agent focused — do not assign tasks that are not necessary to completing the **system goal**. Your primary job is to write an architectural plan to change only ONE file, the target file.

- **Additional Focus Points**: Where the target file uses logging or structured error handling, preserve those patterns and extend them to cover new code paths. Apply defensive coding practices proportional to the risk surface. Stay aware of existing error handling in functions. Keep code suggestions minimal and do not over-engineer.

---

## 2. Editor Execution Strategy (Target: Editor and Coding Agent)

> **Note to Editor**: You are acting strictly as the executor of this plan.

- **Execution & Variable Expansion**: Follow the Architect's "Tight Descriptions" closely. If a task's Scope Variables field lists multiple variables, your edit is incomplete until all of them appear explicitly in the diff. Submitting a diff that handles only one scoped variable and leaves others as NULL or stubs is a task failure.

- **Constraint 1:** Do NOT edit or rewrite any reference files or any file listed as read-only. You may only output edits for the single target file assigned to you.

- **Constraint 2 (Code Preservation)**: Never delete, omit, or truncate any functions, variables, or logic that you were not explicitly instructed to change. You must implement the new code features **without** destroying or rewriting the complex, existing scaffolding of the target file. Leave all unrelated logic strictly untouched. Write each SEARCH/REPLACE block targeting the smallest possible unique context. Prefer multiple small blocks over one large block.

- **Reference Strictness**: If you use the reference files while executing the Architect's plan, use them ONLY for syntactic structure examples. Never copy its mathematical logic since you may have to build your own unique logic.

- **Validation**: Ensure that all applied refactoring maintains valid R syntax and structurally aligns with the required KV patterns before moving on to the next task.

- **Additional Focus Points**: Where the target file uses logging or structured error handling, preserve those patterns and extend them to cover new code paths. Apply defensive coding practices proportional to the risk surface. Stay aware of existing error handling. Keep edits minimal and do not over-engineer.

---

## 3. Implementation Phases (The "How")

- **Phase 1: Algorithmic Preservation (MANDATORY)**: Before planning any structural refactoring, the Architect must explicitly identify the core mathematical and algorithmic logic currently present in the target file (FX conversions, specific aggregations, or unique conditional logic, etc.). Your plan must prioritize preserving the _intent_ of this logic. While you may correct obvious arithmetic faults or adjust equations to accommodate the new state management structure, do not invent entirely new mathematical approaches or overwrite underlying quantitative best practices.

- **Phase 2: Variable Scope Analysis (MANDATORY)**: Before writing any tasks, the architect planning agent must output a brief section named `## Scope Analysis`. In this section, list every single variable in the target file that requires the new logic (e.g., if the file processes a variable pattern like `variable_A`, `variable_B`, and `variable_OTHER`, etc.) list them both in the `## Scope Analysis`.). You will use this list to ensure your tasks apply to all necessary entities.

- **Phase 3: Core Logic**: Failure to apply the referenced refactoring patterns to the target file invalidates the plan. The logic and the patterns are the important code — use generic naming rather than fabricating a code path that does not follow the established workflow patterns. If updating mathematical calculations (aggregations, averages, or other statistics), explicitly define the initialization states.

- **Phase 4: Integration (Aider Handoff)**: The Architect agent will parse this document and output the Atomic Tasks directly into the chat. The Editor will read these tasks and execute the code edits.

---
