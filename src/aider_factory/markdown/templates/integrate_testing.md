# Technical Implementation Plan: Integration Testing Against Live TimeBase

## 1. Architectural Overview (Architect: Planning and Task Writing Agent)

- **System Goal**: Review the refactored schema, logic, and function scopes in the source file shared in context. Generate comprehensive `testthat` integration tests in the target script found in `tests/testthat/`. These tests will execute against a **live TimeBase instance** using real historical trade data. Tests must verify that the functions correctly read from `warehouse-TRADES`, `OKX-OHLCV-1MIN`, work through all the integration logic and I/O related scenarios, and write results to the `FEATURES` stream with structurally valid data.table schemas and nested KV 'values' column. Ensure tests run for all function variants.

- **Action**: Analyze the referenced `R/` source file. Identify the core function variants, their database interaction patterns, and their expected outputs against known historical data. Design integration tests that call the live functions with real `algo_id`, `symbol`, `symbol_hedge`, and `exchange` parameters. Use known trade periods from the live database to assert that outputs are numerically plausible, structurally correct, and written successfully. Note that when tests are already present in the target script, you may need to update them to reflect changes to the source script -- test code could have been written before the refactoring and may not be compatible with the updated code. Do not force tests updates if they are not necessary.
    - **Connection Context**: Use `localhost:8022` for all TimeBase connections. The connection initialization in the test script must follow this logic:
        ```R
        library(TimeBaseR)
        db_write <- get_timebase_connection("dxtick://localhost:8022", readonly = FALSE)
        db_read <- get_timebase_connection("dxtick://localhost:8022", readonly = TRUE)
        ```
    - **Function Injection**: If the functions under test accept `db` or connection arguments, you MUST explicitly pass `db_read` and `db_write` into those arguments during testing to ensure the function uses the local test instance.
    - **Test Fixture Data**:
        - `algo_id`: `890`, `893`, `895`, `897`, `899`, and `901`
        - `symbol`: `BTC-USD-260925` for all
        - `symbol_hedge`: `BTCUSD` (algo 890), `BTC-USD-260626` (algo 893), `BTCUSDT` (algos 895, 897, 899, 901)
        - `exchange`: `OKX` for all
        - Trade period for algo 890: `2026-02-06` to `2026-02-06`
        - Trade period for algo 893: `2026-02-07` to `2026-02-08`
        - Trade period for algo 895: `2026-02-12` to `2026-02-15`
        - Trade period for algo 897: `2026-02-16` to `2026-02-22`
        - Trade period for algo 899: `2026-02-26` to `2026-03-02`
        - Trade period for algo 901: `2026-03-03` to `2026-03-03`

- **Integration Strategy**: Integration tests connect to real infrastructure — do NOT mock `TimeBaseR` database calls. The live `db_read` and `db_write` connections must be resolved by the functions themselves via `.resolve_db` for the backfill functions (`_b`) and hardcoded connections in the live functions (`_l`). **Do NOT use weak assertions (e.g., merely checking if a status is SUCCESS or ERROR). You must explicitly validate the schema of the returned payload or dry-run output—assert specific column names, data types, numeric plausibility (e.g., values are not all NA or 0), and non-empty row counts to ensure data integrity.** Use `tryCatch` inside tests to capture and surface TimeBase connection errors clearly.

- **Exhaustive Fixture Coverage**: You MUST NOT stop at testing just one `algo_id` or configuration. Your testing plan must iterate through or individually test ALL provided `algo_id` fixtures to ensure the logic handles the variability in instruments and hedge pairs across different market data scenarios. You must deeply investigate the target source file and construct a comprehensive Decision Matrix mapping out every possible scenario that requires testing.

- **State Continuity Testing**: You MUST include test tasks that verify rolling state. For backfill functions (`_b`), simulate two sequential runs (e.g., Run 1 for Day 1, Run 2 for Day 2) and assert that the prior state is successfully picked up and accumulated.

- **State Management & Cleanup (MANDATORY)**: The test suite must run against a clean destination state to ensure accurate integration testing without early-exit false positives. You MUST physically write data during these tests (`dry_run = FALSE`) to test continuity.
    - To ensure the `FEATURES` stream is clean, you MUST include the stream purging logic (`stream$deleteData(...)` provided in the Index) at the very top of your test script.
    - You must also wrap the purge logic in a `withr::defer()` block within your tests to ensure the database is cleaned up after the test completes or crashes.

- **Anti-Laziness & Debugging Protocol**: You are STRICTLY FORBIDDEN from adding `skip_if_not()` or skipping tests just because an assertion fails. If an assertion like `expect_true("FEATURES" %in% streams)` fails, do NOT assume the database is offline. Assume YOUR code is wrong and use explicit techniques like `print(str(streams))` to debug the object structures instead of skipping the test.

- **Architect Tools**: Do NOT attempt to invoke file-editing tools, write SEARCH/REPLACE blocks, or output git diffs. As the architect, you must output your technical testing plans, instructions, atomic tasks, and summaries strictly as standard markdown text in your conversational response.

- **Constraint 1 (Live Data Safety)**: Before writing, verify the target write stream exists and is designated for testing. If a `dry_run = TRUE` parameter is available in the function under test, use it where applicable for write operations. Only assert on the returned status and structure — do not assert on the exact number of rows written.

- **Constraint 2 (System Focus)**: You are responsible for the "System-of-Systems" integrity. Your primary job is to verify the successful handoff between the source logic and the target external systems. While you must understand the internal logic, your tasks must prioritize the contract between services. Ignore unrelated files in the context map; focus strictly on the integration boundary defined in the 'System Goal'.

- **Constraint 3 (Context Continuity)**: Prioritize incremental improvement. Always analyze the existing tests/testthat file first. If tests exist, your tasks must extend the current coverage to include the integration aspects without breaking existing unit-level assertions. If the file is empty, you are responsible for establishing the initial connection and teardown boilerplate.

- **Constraint 4 (Strict Integration Focus)**: Do NOT write unit tests (tests using manually crafted, mock `data.table` or other type objects consistent with current usage) in this integration test file. Every test here must evaluate the actual handoff between the source R code and the live TimeBase database. Pure logic tests belong exclusively in the unit testing suite.

- **Additional Focus Points**:
    - **Connectivity Resilience**: Design tests that verify how the function behaves when external systems are slow, unreachable, or return empty/malformed payloads.
    - **Data Integrity**: Assert that the data written to the destination exactly matches the schema requirements of the downstream consumers.
    - **Idempotency**: Ensure tests are designed to be run repeatedly without polluting the target system or leaving "zombie" state behind.
    - **Testing Connections**: Don't test timebase connectivity directly. Use a query to retrieve data to check if the connection is working instead.

---

## 2. Tester Execution Strategy (Target: Editor and Testing Agent)

> **Note to Tester**: You are the Guardian of the Integration Environment. Your execution must be surgical to avoid side effects in live or staging environments.

- **One-Shot Precision**: Execute the Architect’s tasks with zero deviation. Integration tests often involve complex setup/teardown; moving lines or changing variable names can break the connection to the external system.

- **Constraint 1 (Environment Isolation):** You may only write to the tests/testthat target file. Under no circumstances should you hardcode credentials or modify global environment variables. Use the provided connection wrappers (.resolve_db, etc.) as defined in the source.

- **Constraint 2 (Context Preservation)**: Append your tests to the existing target file. Do not overwrite setup blocks (e.g., test_db handles) that are already functional, as these are critical for the integration environment.

- **Constraint 3 (System Safety)**: if a test requires a "Write" operation, verify it is directed at the correct stream and uses the correct `dxtick` url. Do not modify the source code in the R/ directory unless the integration test reveals a fatal type-coercion error that prevents the system-to-system handoff.

- **Source Code Safety**: Keep your edited and created files confined strictly to the `tests/testthat` directory. Do not alter the source code in the `R/` directory unless your tests reveal a fatal syntax crash with the source code file (the source file with same suffix as the target file for this task found in `tests/testthat`).

- **Additional Focus Points**: Do not use any skipping logic or code, all systems are active and must be tested. Any connection errors or API not reachable errors are because of the test code not because of connections.

---

## 3. Test Implementation Phases (The "How")

- **Phase 1: Connectivity & Schema Verification (MANDATORY)**: The Architect must first identify the "External Contract." Before writing tasks, list the required inputs from the source system and the required schema of the target system. Your plan must start by verifying that a basic connection can be established and that a "ping" or "first-row" query returns the expected column headers and data types.

- **Phase 2: Comprehensive Test Decision Matrix (MANDATORY)**: Use Chain-of-Thought reasoning to output a section named `## Integration Boundary & Use Case Analysis`. You must deeply investigate the target source file and construct a comprehensive Decision Matrix mapping out every possible scenario that requires testing. Do not rely on generic examples; derive these strictly from the code's specific logic, parameters, and database interactions:
    - **Identify All Use Cases**: Map out all primary execution paths, data ingestion variants, and successful expected states.
    - **Identify All Edge Cases**: Look for boundary conditions, extreme parameter values, mathematical vulnerabilities (like division by zero on empty payloads), and time/state gaps.
    - **Identify All System Boundaries**: Analyze the handoff between R and the database. What happens on timeouts, malformed schema returns, or zero-row returns?
    - **The Decision Matrix**: Output a comprehensive markdown table summarizing this analysis. The table must have columns: `Category` (Use Case/Edge Case/Boundary), `Scenario Description`, `Target Code Logic`, and `Required Integration Test`.
    - **Enforcement**: Your generated Atomic Tasks below MUST cover every single row in your Decision Matrix. You are expected to be exhaustive.

- **Phase 3: Operational Handoff (Aider Execution)**: The Architect will finalize the Atomic Tasks. The Editor will implement these, focusing on ensuring the test scripts are "self-healing" (i.e., they close their own database connections regardless of whether the test passes or fails).

---

## 4. Atomic Task List (`tasks` format)

> Architect: For each task, provide the "Tight Description" the Editor and testing model needs to implement the test script.

### [Task ID: 001] - [Task Title]

- **Target File**: `tests/testthat/test-target_file.R`

- **Essential Elements**: (Brief comma-separated list of the functions or behaviors to be tested)

- **Tight Description**: Provide precise testing logic, expected inputs, and the specific `expect_equal` or `expect_true` assertions required.

- **Syntax Example**: (if applicable) Provide a code snippet of the exact `testthat` structure or syntax needed.

## REQUIRED OUTPUT FORMAT

> Architect: You MUST structure your entire response exactly like the template below. Do not add conversational filler.

```markdown
## Integration Boundary Analysis

### External Contract Identified:

1. ...

### Predicted System Boundaries & Failure Modes:

| Boundary / Failure Mode | Target Code Logic | Required Live/Dry-Run Scenario |
| ----------------------- | ----------------- | ------------------------------ |
| ...                     | ...               | ...                            |

---

## Test Plan

### [Task ID: 001] - [Task Title]

- **Target File**: `...`
- **Essential Elements**: `...`
- **Tight Description**: `...`
- **Syntax Example**: `...`

---

## Atomic Tasks

### [Task ID: 001] - [Task Title]

```r
# Code implementation here
```

...

---

## Testing Summary

- [ ] Task 001...
```

## Index

Below is some auxilary code to make integration testing easier:

### Purging Stream Data for Clean State Testing

Use this snippet to purge data from a stream without destroying the stream schema. This is critical for setup and teardown in integration tests.

```{r, eval = FALSE}
db <- TimeBaseR::get_timebase_connection("dxtick://localhost:8022", readonly = FALSE)
stream <- db$getStream("FEATURES")
stream$deleteData(
  fromMs = 1L * 1000L,
  toMs   = as.numeric(Sys.time()) * 1000L,
  entities = NULL
)

## further implementation example for purging and state management

library(testthat)
library(TimeBaseR)
library(withr)
library(data.table)

db_url <- "dxtick://localhost:8022"
read_stream_name <- "FEATURES"
write_stream_name <- "FEATURES"
ohlcv_stream_name <- "OKX-OHLCV-1MIN"

# 1. Global Data Load (Memory Only)
fixtures_path <- "../data/reference_backfill_data.rds"
algos_data <- if (file.exists(fixtures_path)) readRDS(fixtures_path) else NULL

# Register global teardown to clean up the database after all tests finish
withr::defer(
  {
    tryCatch(
      {
        db_w <- TimeBaseR::get_timebase_connection(db_url, readonly = FALSE)
        st <- TimeBaseR::get_stream(write_stream_name, db = db_w)
        st$deleteData(fromMs = 1L, toMs = as.numeric(Sys.time()) * 1000L, entities = NULL)
      },
      error = function(e) NULL
    )
  },
  teardown_env()
)

# 2. Global Metadata
algo_meta <- list(
  "890" = list(sym = "BTC-USD-260925", hedge = "BTCUSD", exch = "OKX", exch_h = "OKXUS"),
  "893" = list(sym = "BTC-USD-260925", hedge = "BTC-USD-260626", exch = "OKX", exch_h = "OKXUS"),
  "895" = list(sym = "BTC-USD-260925", hedge = "BTCUSDT", exch = "OKX", exch_h = "OKXUS"),
  "897" = list(sym = "BTC-USD-260925", hedge = "BTCUSDT", exch = "OKX", exch_h = "OKXUS"),
  "899" = list(sym = "BTC-USD-260925", hedge = "BTCUSDT", exch = "OKX", exch_h = "OKXUS"),
  "901" = list(sym = "BTC-USD-260925", hedge = "BTCUSDT", exch = "OKX", exch_h = "OKXUS")
)

# 3. Helper: Purge and Inject (Perfect Isolation)
reset_and_inject_fixtures <- function() {
  skip_if(is.null(algos_data), "Fixture data not loaded")

  db_write <- TimeBaseR::get_timebase_connection(db_url, readonly = FALSE)
  stream <- TimeBaseR::get_stream(write_stream_name, db = db_write)

  # Purge
  tryCatch(
    {
      stream$deleteData(fromMs = 1L, toMs = as.numeric(Sys.time()) * 1000L, entities = NULL)
    },
    error = function(e) message("Purge failed: ", e$message)
  )

  # Inject
  load_opts <- TimeBaseR::create_loading_options(write_mode = "insert")
  for (algo_id in names(algos_data)) {
    dt_inject <- data.table::copy(algos_data[[algo_id]])
    if (!inherits(dt_inject, "data.table")) setDT(dt_inject)

    # Sanitize exchange to match query
    meta <- algo_meta[[algo_id]]
    if (!is.null(meta) && "exchange" %in% colnames(dt_inject)) {
      dt_inject[symbol == meta$sym, exchange := meta$exch]
      dt_inject[symbol == meta$hedge, exchange := meta$exch_h]
    }

    # Convert ONLY payload timestamps from nanoseconds to milliseconds (integer64).
    # Do NOT touch 'timestamp' or 'sourceTimestamp' as they are already in the correct
    # POSIXct/nanotime format required by use_loader.
    for (col in c("periodStart", "periodEnd")) {
      if (col %in% colnames(dt_inject)) {
        dt_inject[[col]] <- bit64::as.integer64(as.numeric(dt_inject[[col]]) / 1e6)
      }
    }

    loader <- TimeBaseR::create_loader(stream, options = load_opts)
    TimeBaseR::use_loader(
      loader = loader, dt_inject,
      array_type_names = list(values = list("wf.timebase.feature.messages.EventKV")),
      timestamp_encodings = list(sourceTimestamp = "ms"),
      dry_run = FALSE, verbose = FALSE
    )
  }
}


```

### Verifying TimeBase Connection (The ONLY valid way to check connectivity)

Always place this at the top of your test blocks to gracefully skip if the database is offline.

```{r, eval = FALSE}
  testthat::skip_if_not(
    !inherits(tryCatch({
      db_read <- TimeBaseR::get_timebase_connection("dxtick://localhost:8022", readonly = TRUE)
      TimeBaseR::list_streams(db = db_read)
    }, error = function(e) e), "error"),
    "TimeBase not available at localhost:8022"
  )
```

```{r, eval = FALSE}
## Do not use get_TimeBaseR::timebase_connection(). It returns TRUE or FALSE, which is not the actual connection status. To test if timebase is connected simply execute TimeBaseR::list_streams(db = db_connection), it will return an error if the connection is not established.

## Environment for variable extraction
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
