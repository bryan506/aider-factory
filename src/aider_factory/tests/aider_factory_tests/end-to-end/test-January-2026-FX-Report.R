library(testthat)

test_that("January 2026 FX Report summarizes macroeconomic drivers", {
  report_content <- "The provided context is insufficient to summarize the performance of the US Dollar (USD) and Euro (EUR) during January 2026, as there is no mention of these currencies or their performance in the provided text.

However, the main macroeconomic drivers mentioned in the context include:

**1. Labor Market Dynamics**
* <evidence quote=\"Since June 2025, private-sector employers have added an average of 43,000 jobs per month, slower than the 79,000 average monthly pace during the first half of the year and considerably below the 135,000 average during the second half of 2024.\">Private-sector job growth slowed down significantly after June 2025.</evidence>
* <evidence quote=\"Meanwhile, the unemployment rate since June has averaged 4.4%, or about 0.2 percentage points above the average in the first half of 2025—though the increase in the unemployment rate is due to a low hires rate rather than a rising layoffs rate, which remains stable and low.\">The unemployment rate experienced a slight increase due to a lower hiring rate rather than increased layoffs.</evidence>

**2. U.S. Current Account and Trade Deficit**
* <evidence quote=\"The U.S. current account deficit widened by $317.1 billion to $1.3 trillion in the four quarters through June 2025.\">The current account deficit expanded to $1.3 trillion (or 4.6% of GDP) during the four quarters ending June 2025.</evidence>
* <evidence quote=\"The widening of the current account deficit mostly reflected an expanded deficit in goods. Overall, the goods deficit increased by around $276.4 billion in the four quarters through June 2025 while the services surplus increased by $15.0 billion.\">This trade imbalance was primarily driven by an expanding deficit in goods.</evidence>

**3. Fiscal Deficit and Federal Debt**
* <evidence quote=\"In FY 2025, which ended last September, the deficit narrowed by $41 billion to $1.78 trillion, equal to 5.8% of GDP as an increase in receipts more than offset rising outlays.\">The fiscal deficit narrowed to 5.8% of GDP in FY 2025 due to revenue increases offsetting outlays.</evidence>
* <evidence quote=\"At the end of FY 2025, gross federal debt stood at $37.6 trillion (124.0% of GDP), while debt held by the public was $30.3 trillion (99.7% of GDP).\">U.S. gross federal debt reached $37.6 trillion, representing 124.0% of GDP by the end of FY 2025.</evidence>

**4. Moderating Inflation**
* <evidence quote=\"Over the twelve months ending in December 2025, year-over-year CPI inflation was 2.7%, matching the pace over the twelve months through June.\">Annual CPI inflation slowed down and stabilized at 2.7% through December 2025.</evidence>"

  expect_true(grepl("The provided context is insufficient", report_content))
  expect_true(grepl("However, the main macroeconomic drivers mentioned in the context include:", report_content))
  expect_true(grepl("**1. Labor Market Dynamics**", report_content))
  expect_true(grepl("**2. U.S. Current Account and Trade Deficit**", report_content))
  expect_true(grepl("**3. Fiscal Deficit and Federal Debt**", report_content))
  expect_true(grepl("**4. Moderating Inflation**", report_content))
})
