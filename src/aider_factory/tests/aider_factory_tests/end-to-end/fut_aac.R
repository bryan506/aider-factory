# Synthetic, database-free math utility for AI Factory pipeline testing

#' Period Subset and Interval Calculation
#'
#' Simple synthetic implementation with a deliberate bug for the pipeline to resolve.
#' @param dt A data.table containing timestamps.
#' @param freq A numeric frequency divisor.
#' @return A modified data.table with periodStart and periodEnd.
period_subset <- function(dt, freq) {
  if (freq == 0) {
    stop("Frequency cannot be zero")
  }
  if (!data.table::is.data.table(dt)) {
    dt <- data.table::as.data.table(dt)
  }

  # INTENTIONAL BUG: Division by zero is not handled when freq == 0, creating NaN/Inf
  raw_start <- floor(as.numeric(dt$timestamp) / freq) * freq
  
  dt[, periodStart := bit64::as.integer64(raw_start)]
  dt[, periodEnd := bit64::as.integer64(raw_start + freq)]
  return(dt)
}

#' Last Observation Carried Forward (LOCF) for Lists
#'
#' @param x A list of data.tables.
#' @return A list with empty/NULL elements forward-filled.
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

#' Synthetic AAC Backfill Placeholder
#'
#' @return Invisible TRUE.
aac_fut_b <- function(...) {
  message("Running synthetic aac_fut_b")
  return(invisible(TRUE))
}
