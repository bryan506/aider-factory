# Technical Implementation Plan: Unit Testing for Infrastructure Helpers

## 1. Architectural Overview (Architect: Planning and Task Writing Agent)

- **System Goal**: Review the infrastructure and utility functions located in the assigned source file (`R/helpers.R`, `R/helpers_kv.R`, etc.) shared with you in context. These functions form the critical "Data Access Layer" and utility backbone of the application. Referencing your context, run and generate comprehensive `testthat` unit tests in the target script found in `tests/testthat/`. The unit tests must rigorously validate schema parsing, parameter validation, string manipulation, and database query formatting without making physical network calls.

- **Action**: Analyze the referenced `R/` helper file and explicitly identify every utility function, parameter validation logic, and query builder present. **You must write tests that cover ALL functions exported or defined in the source file.** Design tests that verify code and logic compliance with absolute precision. Because these are low-level utility functions, they are called thousands of times by higher-level orchestrators; therefore, you must adopt an aggressively skeptical posture. Your objective is maximum test density. You must generate an exhaustive test suite that asserts every data type check, every `NA`/`NULL` fallback, every `if/else` branch, every regex match, and every custom error-handling condition (`stop()`, `cli::cli_abort()`, etc.). **Generating a minimal or basic test suite is considered a failure**.
    - **Mocking Interface Contracts**: Unit tests must completely isolate algorithmic logic from physical database I/O. Use `mockery::stub` to intercept underlying package calls (e.g., `TimeBaseR` internals, `logger` calls) and force them to return expected dummy data structures.
    - **Stub Precision**: When stubbing allowed external dependencies, the string name of the mocked function in `mockery::stub` MUST match exactly how it is invoked in the source code namespace (e.g., if the source calls `execute_query()` directly, you must stub `"execute_query"`, not `"TimeBaseR::execute_query"`).

- **Phase 2: Comprehensive Test Decision Matrix (MANDATORY)**: Use Chain-of-Thought reasoning to output a section named `## Helper Function Boundary Analysis`. You must deeply investigate the target helper file and construct a comprehensive Decision Matrix mapping out every possible scenario that requires testing. Do not rely on generic examples; derive these strictly from the code's specific logic, parameter constraints, and return schemas:
    - **Identify All Primary Uses**: Map out the successful, expected behavior for valid inputs for every function.
    - **Identify All Type/Class Edge Cases**: Look for boundary conditions involving incorrect object types (e.g., passing a list instead of a string), vector length violations (passing vectors to scalar arguments), and extreme mathematical/string values.
    - **Identify All Failure Modes**: Map out every specific error string or condition that the helper is designed to throw or catch.
    - **The Decision Matrix**: Output a comprehensive markdown table summarizing this analysis. The table must have columns: `Function Name`, `Category` (Use Case/Edge Case/Failure Mode), `Scenario Description`, `Target Code Logic`, and `Required Unit Test Assertion`.
    - **Enforcement**: Your generated Atomic Tasks below MUST cover every single row in your Decision Matrix. You are expected to be exhaustive.

- **Architect Tools**: Do NOT attempt to invoke file-editing tools, write SEARCH/REPLACE blocks, or output git diffs. As the architect, you must output your technical testing plans, instructions, atomic tasks, and summaries strictly as standard markdown text in your conversational response.

- **Mocking Strategy**: All external dependencies must be mocked. **Do NOT mock internal logic, looping mechanisms, or data transformations (e.g., do not stub out internal processing functions). The core computational flow must execute against your mock data.** For namespaced calls (e.g., `TimeBaseR::execute_query`), use `with_mocked_bindings(fn = mock, .package = "PackageName", { ... })` to ensure interception. Never allow tests to make real database connections. Mock `db_read`, `db_write`, and any `TimeBaseR::get_timebase_connection` calls by assigning dummy values in the test environment before calling the function under test.

- **Constraint 1 (Target Verification)**: Do not suggest, imply, or write test plans for any reference file (or any source file listed in your context) that are not the specific `tests/testthat` target files. You must explicitly identify the core target files by mapping the `tests/testthat/test-*.R` files to its corresponding `R/*.R` source files. You must ONLY write tests for these specific source files.

- **Constraint 2**: You are responsible for keeping the editor and testing agent focused. Your primary job as the architect agent is to write a comprehensive plan and tests for the referenced file in 'system goal'. Ignore all other files mentioned in the Context Map or Git Diffs, do not try to validate other test files, only write plans, tasks and validations for the target file in `tests/testthat` assigned to this task.

- **Constraint 3**: Unless necessary to follow `testthat` conventions, DO NOT suggest to create new files. Always check for existing context in target `tests/testthat` file. If context exists then append suggestions and tests to the existing target `tests/testthat` file shared for this task. If the file is empty, proceed, that just means you are making the first edits.

- **Constraint 4**: You are strictly forbidden from using `testthat::skip()` because a function requires 'complex mocking' or 'extensive environment setup'. It is your job to write those complex mocks.

- **Additional Focus Points**: Where necessary, apply defensive coding best practices, while staying aware of built in error handling in functions, keeping code suggestions minimal, and not over engineering suggestions.
    - **Idempotency**: Ensure tests are designed to be run repeatedly without side effects. Mocks must be scoped within test blocks and must not leak state between tests. **When reusing mock `data.table` objects across multiple assertions or tests, use `data.table::copy()` to prevent in-place reference mutations (e.g., `:=`) from leaking state.**
    - **Codebase Consistency**: Ensure tests are written in a fashion coherent with expected structures and libraries. Use the same conventions and libraries as the target file where it applies. Use data.table methods over base R methods where appropriate, specially when creating new data tables and assigning columns and values (e.g. `data.table::set()`, or `dt[, :=]`). Avoid using backticks (``) in test code. When dealing with names. Assign an empty data.table first prior to any operations that require column names (e.g., `dt <- data.table()`before`data[, :=]`).

---

## 2. Tester Execution Strategy (Target: Editor and Testing Agent)

> **Note to Tester**: You are acting strictly as the executor of this testing plan. Your output must be surgical — mock exactly what is needed, assert exactly what is specified, and add nothing beyond the Architect's scope.

- **One-Shot Precision**: Follow the Architect's atomic tasks exactly to generate the `testthat` scripting.

- **Constraint 1:** Do NOT edit or rewrite any reference files or any file listed as read-only. You may only write to the `tests/testthat` target file that will be created with this task.

- **Constraint 2**: Unless necessary to follow `testthat` conventions, DO NOT create new files, simply append tests and architect suggestions to the existing target `tests/testthat` file shared for this task. If the file is empty, proceed, that just means you are making the first edits.

- **Constraint 3 (Code Preservation)**: Never delete, omit, or truncate any functions, variables, or logic that you were not explicitly instructed to change. Ensure all previous, unrelated content remains perfectly intact and functional in the final file.

- **Source Code Safety**: You may edit the source file and the test file to ensure the tests pass and the logic is mathematically sound. Make targeted, minimal edits to the source code. Do not attempt to rewrite massive blocks of code to fix a single-line bug.

- **Additional Focus Points**: Where necessary, apply defensive coding best practices, while staying aware of built in error handling in functions, keeping code suggestions minimal, and not over engineering edits.
    - Use data.table methods over base R methods where appropriate, specially when creating new data tables and assigning columns and values (e.g. `data.table::set()`, or `dt[, :=]`). Avoid using backticks (``) in code when dealing with names. Assign an empty data.table first prior to any operations that require column names (e.g., `dt <- data.table()`before`data[, :=]`).

---

## 3. Test Implementation Phases (The "How")

- **Phase 1: Decision Matrix Generation (MANDATORY)**: Before writing any tasks, the Architect planning agent MUST output the `## Helper Function Boundary Analysis` and generate the comprehensive markdown table as instructed in Section 1. Do not limit your analysis to basic examples; you must exhaustively identify type mismatches, parameter length violations, and specific error strings.

- **Phase 2: Execution Planning (Aider Handoff)**: The Architect agent will translate every single row of the Decision Matrix into an Atomic Task (detailed below) directly into the chat.

- **Phase 3: Implementation**: The Editor will read these tasks and execute the test scripts, focusing on precise assertions and robust error-catching (`expect_error`, `expect_warning`, `expect_identical`).

---

## 4. Atomic Task List Requirements

> Architect: For each task, provide the "Tight Description" the Editor and testing model needs to implement the test script.

### [Task ID: 001] - [Task Title]

- **Target File**: `tests/testthat/test-target_file.R`

- **Essential Elements**: (Brief comma-separated list of the functions or behaviors to be tested)

- **Tight Description**: Provide precise testing logic, expected inputs, and the specific `expect_equal` or `expect_true` assertions required.

- **Syntax Example**: (if applicable) Provide a code snippet of the exact `testthat` structure or syntax needed.

### [Task ID: 002] - [Task Title]

- **Target File**: `...`
- **Essential Elements**: `...`
- **Tight Description**: `...`
- **Syntax Example**: `...`

---

> Architect: Provide a concise, bulleted checklist summarizing the atomic tasks you just generated to ensure all goals and constraints were met.

## 5. Testing Summary (list format)

- [ ] `...`
- [ ] `...`
- [ ] `...`
- [ ] `...`
- [ ] `...`

---
