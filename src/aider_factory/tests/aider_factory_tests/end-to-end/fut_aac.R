#' Futures Adjusted Average Cost B
#'
#' Backfills historical AAC_BASIS (Adjusted Average Cost) values for
#' futures positions by processing trade data from the warehouse-TRADES
#' stream in time-windowed chunks. Calculates AAC_BASIS for both primary
#' futures positions and hedge positions, then computes the spread between
#' them. Uses time-gated processing to ensure completion before deadline.
#' Supports dry-run mode for testing.
#'
#' NOTE: the named write stream must already exist in the TimeBase instance
#'   specified by `write_db_url`.
#'
#' @param algo_id A scalar character string of the algorithm ID.
#' @param symbol A scalar character string of the primary futures symbol.
#' @param symbol_hedge A scalar character string of the hedge symbol.
#'   Can be NULL if no hedging is used.
#' @param base_currency A scalar character string of the base currency.
#' @param quote_currency A scalar character string of the quote currency.
#' @param exchange A scalar character string of the primary exchange.
#' @param exchange_hedge A scalar character string of the hedge exchange.
#'   Can be NULL if no hedging is used.
#' @param start_date The start date of the backfill as a POSIXct object.
#'   If NULL, determined from existing data. (Default: NULL)
#' @param end_date The end date of the backfill as a POSIXct object.
#'   If NULL, backfill will continue until the last event in the read stream.
#'   (Default: NULL)
#' @param read_db_url The address of the TimeBase instance to read from.
#'   (Default: NULL)
#' @param read_stream_name The name of the stream to read trade data from.
#'   (Default: "warehouse-TRADES")
#' @param write_db_url The address of the TimeBase instance to write to.
#'   (Default: NULL)
#' @param write_stream_name The name of the stream to write to.
#'   (Default: "FEATURES")
#' @param interval The interval of the AAC_BASIS to calculate as an hms::hms or
#'   difftime object. (Default: 60 seconds)
#' @param chunk_duration The duration of each chunk to process as an hms::hms or
#'   difftime object. (Default: 104 weeks)
#' @param dry_run Whether to simulate processing without writing
#'   (default: FALSE)
#' @param verbose Whether to log verbose output (default: FALSE)
#'
#' @return An invisible logical value indicating whether the backfill operation
#'   was successful.
#'
#' @section Event generation:
#' Writes AAC_BASIS, SPREAD, POSITION, and YIELD events to the `FEATURES`
#' stream. `values` stores [feature_eventkv] entries with `decimalValue` keys:
#' - AAC_BASIS: `value`, `fees`, `positionCost`, `currentPositionSize`,
#'   `netPositionSize`
#' - SPREAD: `value`, `spreadQuotient`
#' - POSITION: `futCumulativePosition`, `futCumulativePosition_respective`,
#'   `spotCumulativePosition`, `value`, `respectiveSpreadCoins`,
#'   `spreadValueDollars`
#' - YIELD: `marketSpread`, `Basis`, `grossYieldCoins`, `marketYieldPct`, `value`
#'
#' @importFrom data.table data.table set setDT setalloccol := setnames
#' @importFrom data.table melt first last as.data.table
#' @importFrom glue glue glue_collapse
#' @importFrom logger log_error log_info log_warn
#' @importFrom TimeBaseR create_loader use_loader execute_query
#' @importFrom TimeBaseR get_stream get_timebase_connection
#' @importFrom TimeBaseR list_stream_symbols create_loading_options
#' @importFrom nanotime nanotime as.nanotime
#' @seealso [feature_event], [feature_eventkv], [aac_fut_l]
period_subset <- function(dt, freq) {
  # Ensure dt is a data.table
  if (!data.table::is.data.table(dt)) {
    dt <- data.table::as.data.table(dt)
  }

  # Convert timestamp to POSIXct for date operations
  # Assuming timestamp is in nanoseconds (integer64) or seconds (numeric)
  if (inherits(dt$timestamp, "integer64")) {
    timestamps_posix <- as.POSIXct(suppressWarnings(as.numeric(dt$timestamp)) / 1e9, origin = "1970-01-01", tz = "UTC")
  } else {
    timestamps_posix <- as.POSIXct(dt$timestamp, origin = "1970-01-01", tz = "UTC")
  }

  # Calculate periodStart by flooring to the nearest 'freq' seconds (as POSIXct)
  period_start_posix <- as.POSIXct(floor(as.numeric(timestamps_posix) / freq) * freq, origin = "1970-01-01", tz = "UTC")
  # Calculate periodEnd by adding 'freq' seconds to periodStart (as POSIXct)
  period_end_posix <- period_start_posix + freq

  # Convert to integer64 milliseconds for TimeBase compatibility
  dt[, periodStart := bit64::as.integer64(as.numeric(period_start_posix) * 1000)]
  dt[, periodEnd := bit64::as.integer64(as.numeric(period_end_posix) * 1000)]

  return(dt)
}

locf_list <- function(x) {
  last_valid <- NULL
  for (i in seq_along(x)) {
    current_element <- x[[i]]
    is_empty_dt <- FALSE
    if (data.table::is.data.table(current_element)) {
      if (nrow(current_element) == 0) {
        is_empty_dt <- TRUE
      }
    }

    if (is.null(current_element) || is_empty_dt) {
      if (!is.null(last_valid)) {
        x[[i]] <- last_valid
      }
    } else {
      last_valid <- current_element
    }
  }
  return(x)
}

#' @export
aac_fut_b <- function(
  algo_id,
  symbol,
  symbol_hedge,
  base_currency,
  quote_currency,
  exchange,
  exchange_hedge,
  start_date = NULL,
  end_date = NULL,
  read_db_url = NULL,
  read_stream_name = "warehouse-TRADES",
  write_db_url = NULL,
  write_stream_name = "FEATURES",
  interval = as.difftime(60, units = "secs"),
  chunk_duration = as.difftime(104, units = "weeks"),
  dry_run = FALSE,
  verbose = FALSE
) {
  .validate_scalar_character(algo_id, "algo_id")
  .validate_scalar_character(symbol, "symbol")
  if (!is.null(symbol_hedge)) {
    .validate_scalar_character(
      symbol_hedge,
      "symbol_hedge"
    )
  }
  .validate_scalar_character(exchange, "exchange")
  if (!is.null(exchange_hedge)) {
    .validate_scalar_character(
      exchange_hedge,
      "exchange_hedge"
    )
  }
  if (!is.null(start_date)) .validate_scalar_posixct(start_date, "start_date")
  if (!is.null(end_date)) .validate_scalar_posixct(end_date, "end_date")
  .validate_scalar_character(base_currency, "base_currency")
  .validate_scalar_character(quote_currency, "quote_currency")
  if (!is.null(end_date)) .validate_scalar_posixct(end_date, "end_date")
  .validate_scalar_character(read_stream_name, "read_stream_name")
  .validate_scalar_character(write_stream_name, "write_stream_name")
  .validate_scalar_difftime(interval, "interval")
  .validate_scalar_difftime(chunk_duration, "chunk_duration")
  .validate_scalar_logical(dry_run, "dry_run")
  .validate_scalar_logical(verbose, "verbose")
  read_db <- .resolve_db(read_db_url)
  write_db <- .resolve_db(write_db_url, readonly = FALSE)
  ohlcv_stream_name <- paste0(exchange, "-OHLCV-1MIN")
  logger::log_info("Backfilling AAC_BASIS...")
  logger::log_info("Determining date range for processing...")
  # Determine start_date from prior events if not provided
  # Query last events for state extraction regardless of start_date source
  last_sym <- query_first_or_last_event(
    stream_name = write_stream_name,
    symbols = symbol,
    direction = "last",
    where = c(
      glue::glue("featureName == 'AAC_BASIS'"),
      glue::glue("algoId == '{algo_id}'")
    ),
    sidecar_schema = list(
      decimal_fields = "decimalValue",
      timestamp_fields = c("sourceTimestamp", "periodStart", "periodEnd")
    ),
    db = write_db,
    verbose = verbose
  )

  last_hedge <- query_first_or_last_event(
    stream_name = write_stream_name,
    symbols = symbol_hedge,
    direction = "last",
    where = c(
      glue::glue("featureName == 'AAC_BASIS'"),
      glue::glue("algoId == '{algo_id}'")
    ),
    sidecar_schema = list(
      decimal_fields = "decimalValue",
      timestamp_fields = c("sourceTimestamp", "periodStart", "periodEnd")
    ),
    db = write_db,
    verbose = verbose
  )

  if (is.null(start_date)) {
    start_date_sym <- NULL
    start_date_hedge <- NULL
    if (length(last_sym) > 0) {
      if (inherits(last_sym$periodEnd, "integer64")) {
        start_date_sym <- as.POSIXct(suppressWarnings(as.numeric(last_sym$periodEnd)) / 1e9,
          origin = "1970-01-01",
          tz = "UTC"
        )
      } else {
        start_date_sym <- as.POSIXct(as.numeric(last_sym$periodEnd) / 1e9,
          origin = "1970-01-01",
          tz = "UTC"
        )
      }
    }
    if (length(last_hedge) > 0) {
      if (inherits(last_hedge$periodEnd, "integer64")) {
        start_date_hedge <- as.POSIXct(suppressWarnings(as.numeric(last_hedge$periodEnd)) / 1e9,
          origin = "1970-01-01",
          tz = "UTC"
        )
      } else {
        start_date_hedge <- as.POSIXct(as.numeric(last_hedge$periodEnd) / 1e9,
          origin = "1970-01-01",
          tz = "UTC"
        )
      }
    }
    if (!is.null(start_date_sym) && !is.null(start_date_hedge)) {
      start_date <- max(start_date_sym, start_date_hedge)
    } else if (!is.null(start_date_sym)) {
      start_date <- start_date_sym
    } else if (!is.null(start_date_hedge)) {
      start_date <- start_date_hedge
    }
    if (is.null(start_date) || !is.finite(start_date)) {
      logger::log_info(paste(
        "Source", read_stream_name, "stream is empty.",
        "There is nothing to process."
      ))
      return(invisible(TRUE))
    }
  }

  if (!is.null(start_date) && !is.null(end_date) && start_date >= end_date) {
    logger::log_info(paste(
      "Destination", write_stream_name,
      "stream is already up to date. Start:",
      format(start_date, "%Y-%m-%dT%H:%M:%OS3Z", tz = "UTC"),
      "End:", format(end_date, "%Y-%m-%dT%H:%M:%OS3Z", tz = "UTC")
    ))
    return(invisible(TRUE))
  }

  logger::log_info(paste(
    "Calculated processing range:",
    format(start_date, "%Y-%m-%dT%H:%M:%OS3Z", tz = "UTC"),
    "to", format(end_date, "%Y-%m-%dT%H:%M:%OS3Z", tz = "UTC")
  ))

  read_op <- function(chunk_start, chunk_end) {
    logger::log_info(paste(
      "Reading chunk of", read_stream_name, "stream from",
      format(chunk_start, "%Y-%m-%dT%H:%M:%OS3Z", tz = "UTC"),
      "to", format(chunk_end, "%Y-%m-%dT%H:%M:%OS3Z", tz = "UTC")
    ))
    values <- c(
      "tradePrice",
      "tradeQuantity",
      "commission"
    )
    message_type <- "deltix.timebase.api.messages.trade.OrderTradeReportEvent"
    current_minute_floor <- floor(as.numeric(Sys.time()) / 60) * 60 * 1000
    logger::log_info("printing read_stream_name: %s", read_stream_name)
    logger::log_info("printing message_type: %s", message_type)
    logger::log_info("printing symbol: %s", symbol)
    logger::log_info("printing exchange: %s", exchange)
    logger::log_info("printing current_minute_floor: %s", current_minute_floor)
    symbol_pairs <- paste0(
      "'", glue::glue_collapse(c(symbol, symbol_hedge), sep = "', '"), "'"
    )
    exchange_pairs <- paste0(
      "'", glue::glue_collapse(c(exchange, exchange_hedge), sep = "', '"), "'"
    )
    logger::log_info("printing symbol_pairs: %s", symbol_pairs)
    query <- glue::glue("
      SELECT OrderTradeReportEvent:tradePrice,
        OrderTradeReportEvent:tradeQuantity,
        OrderTradeReportEvent:commission,
        OrderTradeReportEvent:commissionCurrency,
        OrderTradeReportEvent:exchangeId,
        OrderTradeReportEvent:side
      FROM \"{read_stream_name}\"
      WHERE \"{message_type}\":traderId == '{algo_id}'
        AND symbol IN ({symbol_pairs})
        AND \"{message_type}\":exchangeId IN ({exchange_pairs})
        AND timestamp >= {as.integer64(as.numeric(chunk_start) * 1000)}
        AND timestamp < {as.integer64(as.numeric(chunk_end) * 1000)}
      ")
    sidecar <- list(decimal_fields = values)
    stream <- TimeBaseR::get_stream(read_stream_name, db = read_db)
    logger::log_info("About to execute query for result data...")
    # options("TimeBaseR.debug" = TRUE)
    result <- execute_query(query,
      stream = stream,
      sidecar_schema = sidecar,
      db = read_db,
      verbose = FALSE
    )
    if (NROW(result) > 0) {
      result[, "tradeQuantity" := ifelse(side == "SELL",
        tradeQuantity * -1,
        tradeQuantity
      )]
    }
    logger::log_info(
      "Query executed. result has %d rows and %d columns",
      nrow(result), " ", ncol(result)
    )
    list(data = result, start = chunk_start)
  }

  write_op <- function(data_from_read,
                       time_int = interval,
                       state = NULL) {
    # Capture symbol and symbol_hedge from parent environment
    sym_primary <- symbol
    sym_hedge <- symbol_hedge

    if (dry_run) {
      logger::log_info(paste(
        "NOTE: this is a 'DRY RUN',",
        "simulating writing to", write_stream_name, "stream."
      ))
    }
    # Extract state for symbols
    state_symbol <- NULL
    state_hedge <- NULL
    if (!is.null(state)) {
      state_symbol <- state$symbol
      state_hedge <- state$hedge
    }

    if (NROW(data_from_read$data) == 0) {
      logger::log_info("No new trades found in chunk. Skipping write.")
      return(list(symbol = state_symbol, hedge = state_hedge))
    }

    if ("commissionCurrency" %in% colnames(data_from_read$data)) {
      event_wt <- convert_trade_commissions(
        trade_data = data_from_read$data,
        ohlcv_stream_name = ohlcv_stream_name,
        db = read_db,
        exchange = exchange,
        base_currency = base_currency,
        quote_currency = quote_currency,
        start_time = as.numeric(data.table::first(data_from_read$data$timestamp)) / 1e6,
        end_time = as.numeric(data.table::last(data_from_read$data$timestamp)) / 1e6
      )
    } else {
      logger::log_info(paste0(
        "commissionCurrency column not found,",
        " could be in dev environment. Assigning",
        " commission to fees with no conversions"
      ))
      event_wt <- data_from_read$data
    }


    data.table::set(event_wt,
      j = "positionCost",
      value = abs(event_wt$tradePrice *
        event_wt$tradeQuantity)
    )

    dt <- split(event_wt, f = event_wt$symbol)

    dt <- lapply(setNames(object = dt, names(dt)), function(aacs) {
      sym_name <- aacs$symbol[1]
      init_st <- if (sym_name == sym_primary) state_symbol else state_hedge
      dt_func <- data.table::data.table()
      data.table::set(dt_func, j = "timestamp", value = aacs$timestamp)

      data.table::set(dt_func,
        j = "positionCost",
        value = apply_cumsum_with_state(aacs$positionCost, "positionCost", init_st)
      )
      data.table::set(dt_func,
        j = "currentPositionSize",
        value = apply_cumsum_with_state(abs(aacs$tradeQuantity), "currentPositionSize", init_st)
      )
      data.table::set(dt_func,
        j = "netPositionSize",
        value = apply_cumsum_with_state(aacs$tradeQuantity, "netPositionSize", init_st)
      )
      data.table::set(dt_func,
        j = "fees",
        value = apply_cumsum_with_state(aacs$fees, "fees", init_st)
      )

      data.table::set(
        dt_func,
        j = "value",
        value = aac(dt_func$fees, dt_func$positionCost, dt_func$currentPositionSize)
      )
      data.table::set(dt_func, j = "symbol", value = aacs$symbol)
      data.table::set(dt_func, j = "exchange", value = aacs$exchange)
      data.table::set(dt_func, j = "featureName", value = "AAC_BASIS")

      return(dt_func)
    })


    if (!is.null(sym_primary)) {
      ts_val <- dt[[sym_primary]]$timestamp
      if (inherits(ts_val, "integer64")) {
        ts_seconds <- suppressWarnings(as.numeric(ts_val)) / 1e9
      } else {
        ts_seconds <- as.numeric(ts_val) / 1e9
      }
      symbol_posix <- as.POSIXct(ts_seconds, origin = "1970-01-01", tz = "UTC")
      if (!is.null(sym_hedge)) {
        ts_val_hedge <- dt[[sym_hedge]]$timestamp
        if (inherits(ts_val_hedge, "integer64")) {
          ts_seconds_hedge <- suppressWarnings(as.numeric(ts_val_hedge)) / 1e9
        } else {
          ts_seconds_hedge <- as.numeric(ts_val_hedge) / 1e9
        }
        hedge_posix <- as.POSIXct(ts_seconds_hedge, origin = "1970-01-01", tz = "UTC")
      } else {
        hedge_posix <- NULL
      }
    }

    if (!is.null(hedge_posix) && length(hedge_posix) > 0) {
      val_sym_vec <- dt[[sym_primary]]$value
      val_hedge_vec <- dt[[sym_hedge]]$value
      dt[["SPREAD"]] <-
        merge(
          xts::as.xts(val_sym_vec, order.by = symbol_posix),
          xts::as.xts(val_hedge_vec, order.by = hedge_posix)
        )

      colnames(dt[["SPREAD"]]) <- c(sym_primary, sym_hedge)

      dt[["SPREAD"]] <- zoo::na.locf(dt[["SPREAD"]])
      dt[["SPREAD"]] <- zoo::na.locf(dt[["SPREAD"]],
        fromLast = TRUE
      )

      dt[["SPREAD"]]$value <- dt[["SPREAD"]][, 1] -
        dt[["SPREAD"]][, 2]
      dt[["SPREAD"]]$spreadQuotient <- dt[["SPREAD"]]$value /
        dt[["SPREAD"]][, 2]
      dt[["SPREAD"]] <- data.table::as.data.table(
        dt[["SPREAD"]][, c(
          "value",
          "spreadQuotient"
        )]
      )
      data.table::setnames(dt[["SPREAD"]], old = "index", new = "timestamp")
      data.table::set(dt[["SPREAD"]], j = "symbol", value = sym_primary)
      data.table::set(dt[["SPREAD"]], j = "exchange", value = exchange)
      data.table::set(dt[["SPREAD"]], j = "featureName", value = "SPREAD")
      data.table::set(dt[["SPREAD"]],
        j = "timestamp",
        value = nanotime::as.nanotime(dt[["SPREAD"]]$timestamp)
      )
    }

    dt <- lapply(setNames(object = dt, names(dt)), function(market) {
      if (market$featureName[1] == "SPREAD") {
        process_feature_event(
          dt = market,
          logic_func = function(x) x$value,
          flat_cols = list(),
          kv_cols = c("value", "spreadQuotient")
        )
      } else {
        process_feature_event(
          dt = market,
          logic_func = function(x) x$value,
          flat_cols = list(),
          kv_cols = c(
            "value", "fees", "positionCost",
            "currentPositionSize", "netPositionSize"
          )
        )
      }
    })

    # Apply lapply processing to ALL cases (both futures, or with SPREAD)
    dt <- lapply(setNames(object = dt, names(dt)), function(market) {
      data.table::set(market,
        j = "sourceTimestamp",
        value = market$timestamp
      )
      data.table::set(market, j = "timestamp", value = NULL)

      same_cols <- period_subset(market, freq = as.numeric(interval))

      return(same_cols)
    })
    dt <- data.table::rbindlist(dt, fill = TRUE)
    data.table::set(dt, j = "timestamp", value = dt$sourceTimestamp)

    ## Expand to complete minute-series per feature and locf fill
    if (nrow(dt) > 0 && "periodEnd" %in% colnames(dt) && "featureName" %in% colnames(dt)) {
      # Convert periodEnd (integer64 ms) to POSIXct for min/max and sequence generation
      min_period_posix <- as.POSIXct(min(dt$periodEnd, na.rm = TRUE) / 1000, origin = "1970-01-01", tz = "UTC")
      max_period_posix <- as.POSIXct(max(dt$periodEnd, na.rm = TRUE) / 1000, origin = "1970-01-01", tz = "UTC")
      minute_seq_posix <- seq.POSIXt(min_period_posix, max_period_posix, by = "min")

      # Create full_series with periodEnd as integer64 milliseconds
      full_series <- data.table::data.table(
        periodEnd = bit64::as.integer64(as.numeric(minute_seq_posix) * 1000)
      )

      # Identify numeric columns to locf (exclude list columns like 'values')
      numeric_cols <- names(dt)[sapply(dt, function(x) {
        is.numeric(x) || inherits(x, "integer64")
      })]

      dt <- split(dt, by = c("featureName", "symbol"), flatten = FALSE)

      # Expand each featureName to full minute-series and locf fill by group
      dt <- lapply(dt, function(feature_group) {
        lapply(feature_group, function(symbol_dt) {
          dl <- data.table::merge.data.table(full_series, symbol_dt,
            by.x = "periodEnd", by.y = "periodEnd", all = TRUE
          )

          # LOCF numeric columns (excluding list columns like 'values')
          num_cols <- names(dl)[sapply(dl, function(x) is.numeric(x) || inherits(x, "integer64"))]
          if (length(num_cols) > 0) {
            dl[, (num_cols) := lapply(.SD, function(x) data.table::nafill(x, type = "locf")), .SDcols = num_cols]
          }

          # Forward-fill character columns with first non-NA value
          char_cols <- names(dl)[sapply(dl, is.character)]
          for (col in char_cols) {
            first_non_na <- dl[[col]][!is.na(dl[[col]])][1L]
            if (!is.na(first_non_na)) {
              dl[[col]] <- data.table::fifelse(is.na(dl[[col]]), first_non_na, dl[[col]])
            }
          }

          # Forward-fill "values" list-column with last valid non-empty data.table
          if ("values" %in% colnames(dl)) {
            dl[["values"]] <- locf_list(dl[["values"]])
          }

          data.table::setkey(dl, "periodEnd")
          dl
        })
      })
    }

    dt <- dt[sapply(dt, function(x) !is.null(x) && length(x) > 0)]
    dt <- data.table::rbindlist(unlist(dt, recursive = FALSE), fill = TRUE)

    # Consolidate metadata column assignment to final block
    data.table::set(dt,
      j = "timestamp",
      value = nanotime::as.nanotime(dt$periodEnd * 1e6) # periodEnd is ms, convert to ns
    )
    data.table::set(dt,
      j = "sourceTimestamp",
      value = bit64::as.integer64(dt$sourceTimestamp / 1e6) # sourceTimestamp is ns, convert to ms
    )
    data.table::set(dt, j = "algoId", value = as.character(algo_id))
    data.table::set(dt, j = "instrumentType", value = "CUSTOM")
    data.table::set(dt,
      j = "typeName",
      value = "wf.timebase.feature.messages.Event"
    )

    target_stream <- TimeBaseR::get_stream(write_stream_name, db = write_db)
    load_opts <- TimeBaseR::create_loading_options(write_mode = "insert")
    loader <- TimeBaseR::create_loader(target_stream, options = load_opts)

    TimeBaseR::use_loader(
      loader = loader,
      dt,
      array_type_names = list(
        values = list("wf.timebase.feature.messages.EventKV")
      ),
      timestamp_encodings = list(
        sourceTimestamp = "ms",
        periodStart = "ms",
        periodEnd = "ms"
      ),
      dry_run = dry_run,
      verbose = verbose
    )
    # Extract new state for next chunk # NOTE: It may not need previous state if it's dependent on AAC. It should always use the latest state from AAC.
    # Default to carrying over previous state if no trades occurred in this chunk
    new_state_symbol <- state_symbol
    new_state_hedge <- state_hedge
    # Check if symbol data exists in dt
    dt_sym <- dt[dt$symbol == sym_primary & dt$featureName == "AAC_BASIS"]

    if (nrow(dt_sym) > 0) {
      last_row_sym <- data.table::last(dt_sym)
      kv_data_sym <- last_row_sym$values[[1]]
      new_state_symbol <- stats::setNames(
        as.list(kv_data_sym$decimalValue),
        kv_data_sym$key
      )
    }

    if (!is.null(sym_hedge)) {
      dt_hedge <- dt[dt$symbol == sym_hedge & dt$featureName == "AAC_BASIS"]
      if (nrow(dt_hedge) > 0) {
        last_row_hedge <- data.table::last(dt_hedge)
        kv_data_hedge <- last_row_hedge$values[[1]]
        new_state_hedge <- stats::setNames(
          as.list(kv_data_hedge$decimalValue),
          kv_data_hedge$key
        )
      }
    }
    return(list(symbol = new_state_symbol, hedge = new_state_hedge))
  }
  # Extract initial state from prior events
  initial_state <- NULL
  if (!is.null(last_sym) || !is.null(last_hedge)) {
    state_symbol <- NULL
    state_hedge <- NULL
    if (!is.null(last_sym) && length(last_sym) > 0) {
      kv_data_sym <- last_sym$values[[1]]
      state_symbol <- stats::setNames(
        as.list(kv_data_sym$decimalValue),
        kv_data_sym$key
      )
    }
    if (!is.null(last_hedge) && length(last_hedge) > 0) {
      kv_data_hedge <- last_hedge$values[[1]]
      state_hedge <- stats::setNames(
        as.list(kv_data_hedge$decimalValue),
        kv_data_hedge$key
      )
    }
    initial_state <- list(symbol = state_symbol, hedge = state_hedge)
  }

  tryCatch(
    {
      .iterp(
        deadline = as.POSIXct("2100-01-01", tz = "UTC"),
        start_date = start_date,
        end_date = end_date,
        chunk_duration = chunk_duration,
        read_op = read_op,
        write_op = write_op,
        initial_state = initial_state
      )
      logger::log_info("Processing complete.")
      invisible(TRUE)
    },
    error = function(e) {
      logger::log_error(sprintf(
        "An error occurred during data processing: %s", e$message
      ))
      invisible(FALSE)
    }
  )
}
