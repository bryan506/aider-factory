options(cli.unicode = FALSE)
args <- commandArgs(trailingOnly = TRUE)
if (length(args) == 0) {
  stop("Must provide a test filter pattern or file path")
}

input_arg <- args[1]

# Extract the base name (e.g., "tests/testthat/test-integration-fut_aac.R" -> "test-integration-fut_aac.R")
base_name <- basename(input_arg)

# Strip the .R extension
base_name <- sub("\\.R$", "", base_name, ignore.case = TRUE)

# Strip the "test-" prefix if it exists, since devtools::test() filter ignores it
if (grepl("^test-", base_name)) {
  base_name <- sub("^test-", "", base_name)
}

test_filter <- paste0("^", base_name, "$")

# Allow all tests to run even if there are many failures
Sys.setenv(TESTTHAT_MAX_FAILS = "Inf")
options(testthat.max_fails = Inf)

# Disable R warnings globally. This prevents testthat from intercepting and
# printing massive warning blocks (e.g., bit64 precision warnings) which bloat
# the LLM context window and distract the agent from the actual test Failures.
options(warn = -1)
options(bit64.promoteInteger64ToCharacter = TRUE)

# Run tests and let the output stream to stdout natively
res <- testthat::test_dir("tests/testthat", filter = test_filter)

# If res is empty, no tests were executed (e.g. fatal package load error)
if (length(res) == 0) {
  quit(status = 1)
}

# Safely sum failures and errors using unlist to handle potential list-columns
res_df <- as.data.frame(res)
fails <- sum(unlist(res_df$failed), na.rm = TRUE)
errs <- sum(unlist(res_df$error), na.rm = TRUE)

if ((fails + errs) > 0) {
  quit(status = 1)
}

quit(status = 0)
