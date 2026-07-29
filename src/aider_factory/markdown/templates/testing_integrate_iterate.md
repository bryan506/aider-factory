CONSTRAINTS FOR THIS FIX:

- You may edit the source file and the test file to ensure the tests pass and the logic is mathematically sound.
- Make targeted, minimal edits to the source code. Do not attempt to rewrite massive blocks of code to fix a single-line bug.
- Use data.table methods over base R methods where appropriate, specially when creating new data tables and assigning columns and values (e.g. `data.table::set()`, or `dt[, :=]`). Avoid using backticks (``) in code when dealing with names. Assign an empty data.table first prior to any operations that require column names (e.g., `dt <- data.table()`before`data[, :=]`).
- Do not create new files
- Do not delete existing passing tests
- Your SEARCH blocks must exactly match current file content

- **Connection Context**: Use `localhost:8022` for all TimeBase connections. The connection initialization in the test script must follow this logic:
  `R
library(TimeBaseR)
db_write <- get_timebase_connection("dxtick://localhost:8022", readonly = FALSE)
db_read <- get_timebase_connection("dxtick://localhost:8022", readonly = TRUE)
` - **Function Injection**: If the functions under test accept `db` or connection arguments, you MUST explicitly pass `db_read` and `db_write` into those arguments during testing to ensure the function uses the local test instance. - **Test Fixture Data**: - `algo_id`: `890`, `893`, `895`, `897`, `899`, and `901` - `symbol`: `BTC-USD-260925` for all - `symbol_hedge`: `BTCUSD` (algo 890), `BTC-USD-260626` (algo 893), `BTCUSDT` (algos 895, 897, 899, 901) - `exchange`: `OKX` for all - Trade period for algo 890: `2026-02-06` to `2026-02-06` - Trade period for algo 893: `2026-02-07` to `2026-02-08` - Trade period for algo 895: `2026-02-12` to `2026-02-15` - Trade period for algo 897: `2026-02-16` to `2026-02-22` - Trade period for algo 899: `2026-02-26` to `2026-03-02` - Trade period for algo 901: `2026-03-03` to `2026-03-03`

- **Integration Strategy**: Integration tests connect to real infrastructure — do NOT mock `TimeBaseR` database calls. The live `db_read` and `db_write` connections must be resolved by the functions themselves via `.resolve_db` for the backfill functions (`_b`) and hardcoded connections in the live functions (`_l`). **Do NOT use weak assertions (e.g., merely checking if a status is SUCCESS or ERROR). You must explicitly validate the schema of the returned payload or dry-run output—assert specific column names, data types, numeric plausibility (e.g., values are not all NA or 0), and non-empty row counts to ensure data integrity.** Use `tryCatch` inside tests to capture and surface TimeBase connection errors clearly.

- **State Management & Cleanup (MANDATORY)**: The test suite must run against a clean destination state to ensure accurate integration testing without early-exit false positives. You MUST physically write data during these tests (`dry_run = FALSE`) to test continuity.
    - To ensure the `FEATURES` stream is clean, you MUST include the stream purging logic (`stream$deleteData(...)` provided in the Index) at the very top of your test script.
    - You must also wrap the purge logic in a `withr::defer()` block within your tests to ensure the database is cleaned up after the test completes or crashes.

- **Anti-Laziness & Debugging Protocol**: You are STRICTLY FORBIDDEN from adding `skip_if_not()` or skipping tests just because an assertion fails. If an assertion like `expect_true("FEATURES" %in% streams)` fails, do NOT assume the database is offline. Assume YOUR code is wrong and use explicit techniques like `print(str(streams))` to debug the object structures instead of skipping the test.

- **Constraint 1**: If a `dry_run = TRUE` parameter is available in the function under test, use it where applicable for write operations. Write directly to the FEATURES stream when necessary with `dry_run = FALSE`, but make sure the top of script has the stream purging logic to ensure a clean state.

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
