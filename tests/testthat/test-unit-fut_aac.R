library(testthat)
library(data.table)
library(bit64)

source("../../src/aider_factory/tests/aider_factory_tests/end-to-end/fut_aac.R")

test_that("period_subset works with freq > 0", {
  dt <- data.table(timestamp = c(10, 25, 30))
  res <- period_subset(copy(dt), 10)
  expect_equal(as.numeric(res$periodStart), c(10, 20, 30))
  expect_equal(as.numeric(res$periodEnd), c(20, 30, 40))
})

test_that("period_subset handles freq == 0", {
  dt <- data.table(timestamp = c(10, 25, 30))
  res <- period_subset(copy(dt), 0)
  expect_equal(as.numeric(res$periodStart), c(10, 25, 30))
  expect_equal(as.numeric(res$periodEnd), c(10, 25, 30))
})

test_that("period_subset handles freq as vector with 0", {
  dt <- data.table(timestamp = c(10, 25, 30))
  res <- period_subset(copy(dt), c(10, 0, 10))
  expect_equal(as.numeric(res$periodStart), c(10, 25, 30))
  expect_equal(as.numeric(res$periodEnd), c(20, 25, 40))
})

test_that("locf_list forward-fills empty data.tables", {
  dt1 <- data.table(a = 1)
  dt2 <- data.table(a = numeric(0))
  dt3 <- data.table(a = 2)
  res <- locf_list(list(dt1, dt2, dt3))
  expect_equal(res[[1]], dt1)
  expect_equal(res[[2]], dt1)
  expect_equal(res[[3]], dt3)
})

test_that("aac_fut_b runs", {
  expect_true(aac_fut_b())
})
