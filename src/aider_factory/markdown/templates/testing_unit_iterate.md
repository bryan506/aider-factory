CONSTRAINTS FOR THIS FIX:

- **Strict Value Constraint**: You are strictly FORBIDDEN from changing the expected value `999` in the test file back to `1`. You must find a mathematical or logical way in the source code to make the result evaluate to `999`. Do not bypass this constraint by reverting the test assertion.
- You may edit the source file and the test file to ensure the tests pass and the logic is mathematically sound.
- Make targeted, minimal edits to the source code. Do not attempt to rewrite massive blocks of code to fix a single-line bug.
- Use data.table methods over base R methods where appropriate, specially when creating new data tables and assigning columns and values (e.g. `data.table::set()`, or `dt[, :=]`). Avoid using backticks (``) in code when dealing with names. Assign an empty data.table first prior to any operations that require column names (e.g., `dt <- data.table()`before`data[, :=]`).
- Do not create new files
- Do not delete existing passing tests
- Your SEARCH blocks must exactly match current file content
- **Always** Split large code modifications into multiple, smaller, search replace blocks. Also ensure all instructed modifications to a file are split into manageable, search replace blocks.

- **Mocking Strategy**: All external dependencies must be mocked. **Do NOT mock internal logic, looping mechanisms, or data transformations (e.g., do not stub out internal processing functions). The core computational flow must execute against your mock data.** For namespaced calls (e.g., `TimeBaseR::execute_query`), use `with_mocked_bindings(fn = mock, .package = "PackageName", { ... })` to ensure interception. Never allow tests to make real database connections. Mock `db_read`, `db_write`, and any `TimeBaseR::get_timebase_connection` calls by assigning dummy values in the test environment before calling the function under test.

- **Constraint 1 (Target Verification)**: Do not suggest, imply, or write test plans for any reference file (or any source file listed in your context) that are not the specific `tests/testthat` target files. You must explicitly identify the core target files by mapping the `tests/testthat/test-*.R` files to its corresponding `R/*.R` source files. You must ONLY write tests for these specific source files.

- **Constraint 2**: You are responsible for keeping the editor and testing agent focused. Your primary job as the architect agent is to write a comprehensive plan and tests for the referenced file in 'system goal'. Ignore all other files mentioned in the Context Map or Git Diffs, do not try to validate other test files, only write plans, tasks and validations for the target file in `tests/testthat` assigned to this task.

- **Constraint 3**: Unless necessary to follow `testthat` conventions, DO NOT suggest to create new files. Always check for existing context in target `tests/testthat` file. If context exists then append suggestions and tests to the existing target `tests/testthat` file shared for this task. If the file is empty, proceed, that just means you are making the first edits.

- **Constraint 4**: You are strictly forbidden from using `testthat::skip()` because a function requires 'complex mocking' or 'extensive environment setup'. It is your job to write those complex mocks.

- **Constraint 5**: Follow Don't Repeat Yourself (DRY) conventions for refactoring and coding in general.

- **Additional Focus Points**: Where necessary, apply defensive coding best practices, while staying aware of built in error handling in functions, keeping code suggestions minimal, and not over engineering suggestions.
    - **Idempotency**: Ensure tests are designed to be run repeatedly without side effects. Mocks must be scoped within test blocks and must not leak state between tests. **When reusing mock `data.table` objects across multiple assertions or tests, use `data.table::copy()` to prevent in-place reference mutations (e.g., `:=`) from leaking state.**
    - **Codebase Consistency**: Ensure tests are written in a fashion coheret with expected structures and libraries. Use the same conventions and libraries as the target file where it applies.
    - **Always** split large code modifications into multiple, smaller, search replace blocks.

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
