# Bulletproof path resolution regardless of R's working directory during testthat execution
possible_paths <- c(
  "src/aider_factory/tests/aider_factory_tests/end-to-end/fut_aac.R",
  "../src/aider_factory/tests/aider_factory_tests/end-to-end/fut_aac.R",
  "../../src/aider_factory/tests/aider_factory_tests/end-to-end/fut_aac.R"
)

found_path <- NULL
for (path in possible_paths) {
  if (file.exists(path)) {
    found_path <- path
    break
  }
}

if (is.null(found_path)) {
  stop("Could not find fut_aac.R in any of the expected paths.")
}
source(found_path)

test_that("locf_list forward fills empty elements", {
  test_list <- list(
    data.table::data.table(a = 1),
    data.table::data.table(),
    NULL,
    data.table::data.table(a = 2)
  )
  
  result <- locf_list(test_list)
  
  expect_equal(result[[2]]$a, 1)
  expect_equal(result[[3]]$a, 1)
  expect_equal(result[[4]]$a, 2)
})

test_that("period_subset calculates correct intervals", {
  dt <- data.table::data.table(timestamp = 120005)
  result <- period_subset(dt, freq = 60)
  expect_equal(as.numeric(result$periodStart), 120000)
})

test_that("period_subset handles zero frequency gracefully", {
  dt <- data.table::data.table(timestamp = 120005)
  # This triggers the division-by-zero bug. The test expects an error to be thrown.
  expect_error(period_subset(dt, freq = 0), "Frequency cannot be zero")
})
