# Technical Implementation Plan: Unit Testing for Rolling State Accumulation

## 1. Architectural Overview (Architect: Planning and Task Writing Agent)

- **System Goal**: Review the newly refactored schema, logic, and function scopes overall, in the source file you'll be writing unit tests for each function group (using generic names, functions could look like: `function`, `function_l`, `function_b`), which was shared with you in context. Referencing your context from this specific workflow, run and generate comprehensive `testthat` unit tests in the target script found in `tests/testthat/`. The unit tests will ensure that each function's data structures, overall code continuity, logic and code execution, edge case handling, and state handling are successful.

- **Action**: Analyze the referenced `R/` files and identify the core function definition variants that allow the functions to run properly, analyze the data, and writes to its destination using the library `TimeBaseR`. **You must write tests that cover ALL function variants found in the source file; if both a live (`_l`) and backfill (`_b`) function exist, you are strictly required to generate tests for both.** Design tests that verify code and logic compliance with implemented code. Tests should verify that changes work with the overall execution and continuity of the primary functions. Create mock data where necessary to test each function with realistic data scenarios. Note that when tests are already present in the target script, you may need to update them to reflect changes to the source script -- test code could have been written before refactoring and may not be compatible with the updated code. Do not force tests updates if they are not necessary. You must design comprehensive tests that achieve high branch coverage. You must adopt an aggressively skeptical posture. Your objective is maximum test density. You must generate an exhaustive test suite that asserts every individual mathematical operation, every `NA`/`NULL` fallback, every `if/else` branch, and every error-handling condition in both the `_l` and `_b` function variants. **Generating a minimal or basic test suite is considered a failure**.
    - **Mocking Interface Contracts**: Unit tests must completely isolate mathematical and algorithmic logic from physical database I/O. Use `mockery::stub` to intercept `TimeBaseR` functions and force them to return dummy data structures (e.g., schemas matching expected inputs).
    - **Stub Precision**: When stubbing allowed external dependencies, the string name of the mocked function in `mockery::stub` MUST match exactly how it is invoked in the source code namespace (e.g., if the source calls `execute_query()` directly, you must stub `"execute_query"`, not `"TimeBaseR::execute_query"`).

- **Architect Tools**: Do NOT attempt to invoke file-editing tools or directly edit any files. As the architect, you must output your technical testing plans, instructions, atomic tasks, and summaries strictly as standard markdown text in your conversational response.

- **Mocking Strategy**: All external dependencies must be mocked. **Do NOT mock internal logic, looping mechanisms, or data transformations (e.g., do not stub out internal processing functions). The core computational flow must execute against your mock data.** For namespaced calls (e.g., `TimeBaseR::execute_query`), use `with_mocked_bindings(fn = mock, .package = "PackageName", { ... })` to ensure interception. Never allow tests to make real database connections. Mock `db_read`, `db_write`, and any `TimeBaseR::get_timebase_connection` calls by assigning dummy values in the test environment before calling the function under test.

- **Constraint 1 (Target Verification)**: Do not suggest, imply, or write test plans for any reference file (or any source file listed in your context) that are not the specific `tests/testthat` target files. You must explicitly identify the core target files by mapping the `tests/testthat/test-*.R` files to its corresponding `R/*.R` source files. You must ONLY write tests for these specific source files.

- **Constraint 2**: You are responsible for keeping the editor and testing agent focused. Your primary job as the architect agent is to write a comprehensive plan and tests for the referenced file in 'system goal'. Ignore all other files mentioned in the Context Map or Git Diffs, do not try to validate other test files, only write plans, tasks and validations for the target file in `tests/testthat` assigned to this task.

- **Constraint 3**: Unless necessary to follow `testthat` conventions, DO NOT suggest to create new files. Always check for existing context in target `tests/testthat` file. If context exists then append suggestions and tests to the existing target `tests/testthat` file shared for this task. If the file is empty, proceed, that just means you are making the first edits.

- **Constraint 4**: You are strictly forbidden from using `testthat::skip()` because a function requires 'complex mocking' or 'extensive environment setup'. It is your job to write those complex mocks.

- **Additional Focus Points**: Where necessary, apply defensive coding best practices, while staying aware of built in error handling in functions, keeping code suggestions minimal, and not over engineering suggestions.
    - **Idempotency**: Ensure tests are designed to be run repeatedly without side effects. Mocks must be scoped within test blocks and must not leak state between tests. **When reusing mock `data.table` objects across multiple assertions or tests, use `data.table::copy()` to prevent in-place reference mutations (e.g., `:=`) from leaking state.**
    - **Codebase Consistency**: Ensure tests are written in a fashion coheret with expected structures and libraries. Use the same conventions and libraries as the target file where it applies. Use data.table methods over base R methods where appropriate, specially when creating new data tables and assigning columns and values (e.g. `data.table::set()`, or `dt[, :=]`). Avoid using backticks (``) in test code. When dealing with names. Assign an empty data.table first prior to any operations that require column names (e.g., `dt <- data.table()`before`data[, :=]`).
    - **Always** Instruct the editor to split large code modifications into multiple, smaller, search replace blocks. As the architect, you are responsible for ensuring your instructed modifications are split into manageable, search replace blocks.

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
    - **Always** split large code modifications into multiple, smaller, search replace blocks.

---

## 3. Test Implementation Phases (The "How")

- **Phase 1: Decision Matrix Generation (MANDATORY)**: Before writing any tasks, the Architect planning agent MUST output a `## Test Decision Matrix` as a comprehensive markdown table. You must deeply investigate the target source file and map out every possible scenario that requires testing. Do not limit your analysis to basic examples; you must exhaustively identify control flow variations, `NA`/`NULL` inputs, extreme numeric bounds, missing prior states, and malformed database schemas. The table must have columns: `Function Name`, `Category` (Math/State/Edge Case/Error), `Scenario Description`, `Target Code Logic`, and `Required Unit Test Assertion`.

- **Phase 2: Execution Planning (Aider Handoff)**: The Architect agent will translate every single row of the Decision Matrix into an Atomic Task (detailed below) directly into the chat. Your generated Atomic Tasks MUST cover every single row in your Decision Matrix to ensure maximum test density.

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

## Index

Below is auxiliary context to assist in accurately mocking external dependencies and data structures without testing actual physical connections:

### TimeBaseR Mocking Rules

Do not test database connectivity in unit tests. Always intercept `TimeBaseR` functions to isolate the mathematical and algorithmic logic. When mocking `TimeBaseR`, adhere to these interface rules:

1. **Streams**: `TimeBaseR::get_stream()` returns a SWIG proxy object. When mocking this, you must return a structured list with a `db_id` attribute; otherwise, internal query executions will fail validation.
    - _Example Structure_: `mock_stream <- structure(list(), class = c("TickStream", "TickDb"), db_id = "mock_db")`
2. **Queries**: `TimeBaseR::execute_query()` must be mocked to return a standard `data.table()` matching the expected schema for the function under test (e.g., timestamps, prices, or KV structures).
3. **Loaders**: Functions like `create_loader` and `use_loader` handle writing. Mock them to return `NULL` or an empty list. The goal is to verify the data structure passed to the loader is correct, not to perform physical write operations.

```r
## Mock Environment for variable extraction
mock_env <- list(
  list(
    system = list(
      algo_id = as.character(algo_id),
      security = list(
        base_currency = "BTC",
        term_currency = "USD",
        multiplier = 100
      ),
      instrument = list(
        instrument = "BTC-USD-260327",
        exchange = "OKX:S_BINANCE"
      ),
      hedger = list(
        hedge_instrument = "BTCUSD",
        venues_list = "OKXUS:S_SOMEWHERE"
      )
    )
  )
)

## end to for aac_fut_l
result <- aac_fut_l(
  env = mock_env,
  context = NULL
)


pos_yield_b(algo_id = algo_id,
       symbol = "BTC-USD-260626",
       symbol_hedge = "BTCUSD",
       exchange = "OKX",
       exchange_hedge = "OKXUS",
       contract_size = 100,
       start_date = as.POSIXct("2025-11-11 19:00:00.000"), # assign NULL after first attempt so backfill 'picks up where it left off'.
       end_date = as.POSIXct("2026-02-09 00:00:00.000"),
       read_db_url = "dxtick://localhost:8022",
       read_stream_name = "FEATURES",
       write_db_url = "dxtick://localhost:8022",
       write_stream_name = "FEATURES",
       chunk_duration = as.difftime(8760, units = "hours"),
       interval = as.difftime(60, units = "secs"),
       dry_run = TRUE,
       verbose = FALSE
)

symbol <- 'BTC-USD-260626'
symbol_hedge <- 'BTCUSD'
base_currency <- "BTC"
quote_currency <- "USD"
exchange <- "OKX"
exchange_hedge <- "OKXUS"

aac_fut_b(algo_id = algo_id,
          symbol = symbol,
          symbol_hedge = symbol_hedge,
          base_currency = base_currency,
          quote_currency = quote_currency,
          exchange = exchange,
          exchange_hedge = exchange_hedge,
          start_date = as.POSIXct("2025-11-11 19:00:00.000"), # assign NULL after first manual attempt so backfill 'picks up where it left off'.
          end_date = as.POSIXct("2026-02-09 19:00:00.000"),
          read_db_url = "dxtick://localhost:8022",
          read_stream_name = "warehouse-TRADES-TOKYO-PROD",
          write_db_url = "dxtick://localhost:8022",
          write_stream_name = "FEATURES",
          chunk_duration = as.difftime(8760, units = "hours"),
          interval = as.difftime(60, units = "secs"),
          dry_run = FALSE,
          verbose = FALSE
)
```
