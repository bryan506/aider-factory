# Language-Agnostic Test Harness & Execution Engine

> **Context Anchor & Authoring Directive:**  
> This document is the definitive master specification for language-agnostic test suite integration, containerized execution wrappers, test-fix retry loops, and deterministic final-check verification.  
> **Source References:** `factory_service_manual.md` under headers `### Containerized Test Execution (Docker)`, `### Customizing the Test Runner (language-agnostic)`, `#### How Combined Unit + E2E Testing Operates`, `### Iteration Loops & Fallback Logic`, `#### The same skeleton in CODE mode`.  
> **Codebase References:** `src/aider_factory/python/orchestrate.py` (`Task`, test execution loops, `Task.final_check`, `Task.soft_fail`), `src/aider_factory/tests/run_tests.R`, `src/aider_factory/cli.py` (`_is_test_path`).

---

## 1. Architectural Overview & Design Invariants

The AI Factory pipeline decouples pipeline orchestration from language-specific testing frameworks using a universal command execution contract. Test execution is modeled as a deterministic verification gate that converts subprocess return codes (`0` for success, non-zero for failure) and captured stdout/stderr into actionable feedback loops for LLM-based editing agents.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               LANGUAGE-AGNOSTIC TEST ENGINE                            │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Parameter Substitution: {test_command_prefix} + {test_runner} -> Shell Command     │
│ 2. Subprocess Execution: Popen with pipe redirection & env-var injection               │
│ 3. Log Capture: Streaming output to terminal & teeing to timestamped log               │
│ 4. Verification Gate: Exit Code Evaluation (0 = PASS, !=0 = FAIL)                     │
│ 5. Feedback Escalation: Error log passed as LLM prompt context for iterative fix       │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Core Design Invariants

1. **Deterministic Authority:** The test suite's exit code is the sole authority for code validity. No LLM or secondary model evaluation overrides a passing or failing exit code.
2. **Zero-Mock Integration Testing:** Integration and End-to-End (E2E) tests must execute real entrypoints against temporary on-disk fixtures (`tempfile`) and physical OS processes without mocking the system under test.
3. **Language & Environment Agnosticism:** Execution wrappers operate seamlessly across local native environments, Python `uv` sandboxes, Docker containers, and custom SSH or Bash wrappers.
4. **Context Window Protection:** Test runners must filter uninformative warning blocks, noise, or verbose progress indicators to prevent context window bloat during LLM feedback passes.

---

## 2. Configuration & Parameter Substitution Framework

Test execution parameters are declared at the root or phase level of `.env.yml` pipeline configurations.

### Configuration Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `test_command_prefix` | `string` | `""` | Execution wrapper prefix (e.g., `docker exec -i ...`, `uv run --with pytest`, `bash`). |
| `test_runner` | `string` | `"Rscript .aider_factory/tests/run_tests.R {file}"` | Command template with `{file}` placeholder. |
| `test_naming_and_path` | `string` | `"tests/testthat/test-{stem}.R"` | Pattern to derive test paths from target stems. Set to `""` for static suites. |
| `loop_aider_test` | `integer` | `1` | Global outer loop retry limit for iterative test fixes. |

### Parameter Substitution Mechanics

The orchestrator (`orchestrate.py`) evaluates the active file stem and constructs the final executable command:

$$\text{Command} = \text{test\_command\_prefix} \space + \text{ " " } + \text{substitute}(\text{test\_runner}, \text{"\{file\}"}, \text{test\_file})$$

If `test_naming_and_path` is explicitly empty (`""`), the placeholder substitution is bypassed, and the command template is executed verbatim.

### Multi-Language Configuration Examples

```yaml
# R / testthat with Docker wrapper
test_command_prefix: "docker exec -i --user myuser -w /path/to/project my-container"
test_runner: "Rscript .aider_factory/tests/run_tests.R {file}"
test_naming_and_path: "tests/testthat/test-{stem}.R"

# Python / pytest with uv sandbox
test_command_prefix: "uv run --with pytest"
test_runner: "pytest {file}"
test_naming_and_path: "tests/test_{stem}.py"

# Rust / cargo test
test_command_prefix: ""
test_runner: "cargo test --test {stem}"
test_naming_and_path: "tests/{stem}.rs"

# Go / go test
test_command_prefix: ""
test_runner: "go test {file}"
test_naming_and_path: "tests/{stem}_test.go"

# Direct Shell Script Runner
test_command_prefix: "bash"
test_runner: "{file}"
test_naming_and_path: ""
```

---

## 3. Test File Discovery & Classification Logic

The `cli.py` module exposes `_is_test_path(rel_path)` to classify repository paths and ensure structural isolation between source code and test files.

```
                      Path Classification Flow (_is_test_path)
                                         │
                        Is path in a known test directory?
                        (tests/, testthat/, __tests__/, etc.)
                                   ┌─────┴─────┐
                                  YES          NO
                                   │           │
                             Return True   Matches delimited pattern?
                                           (test_*.py, *-test.R, etc.)
                                               ┌─────┴─────┐
                                              YES          NO
                                               │           │
                                         Return True   Matches exact harness file?
                                                       (conftest.py, tests.rs, etc.)
                                                           ┌─────┴─────┐
                                                          YES          NO
                                                           │           │
                                                     Return True   Matches CamelCase class?
                                                                   (AuthTest.java, etc.)
                                                                       ┌─────┴─────┐
                                                                      YES          NO
                                                                       │           │
                                                                 Return True   Return False
```

### Classification Patterns

1. **Test Directory Names:** `test`, `tests`, `testing`, `testthat`, `__tests__`, `spec`, `specs`, `e2e`, `end-to-end`, `fixtures`, `testdata`, `test_fixtures`, `benchmarks`, `benches`.
2. **Delimited Regex:** `r"(^|/)((tests?|specs?|unit_?tests?)[_\-\.][^/]+|.+[_\-\.](tests?|specs?|unit_?tests?)\.[^/]+)$"`
3. **Exact Harness Files:** `conftest.py`, `tests.py`, `tests.rs`, `test_helper.rb`, `setupTests.*`.
4. **CamelCase Test Classes:** `r"(^|/)[a-zA-Z0-9_]*(Test|Tests|TestCase|Spec)\.[a-zA-Z0-9]+$"`.

---

## 4. Combined Unit & End-to-End (E2E) Test Suite Execution

To support complex systems requiring both fast unit checks and real integration passes, the pipeline supports multi-suite execution within a single command pass.

### Execution Pattern

```yaml
test_command_prefix: ""
test_runner: "uv run --with pytest pytest src/aider_factory/tests/unit/test_validator*.py src/aider_factory/tests/e2e/test_e2e_*.py"
test_naming_and_path: ""
```

### Key Operational Characteristics

- **Ephemeral Sandboxing:** `uv run --with pytest` provisions testing dependencies on the fly without polluting production virtual environments or global system state.
- **Interactive `/test` Trigger:** In interactive pair-programming sessions (`pair_programming: true`), issuing `/test` in the Aider chat prompt executes the full multi-suite command and streams results directly into context.
- **Combined Reporting:** Failures in either unit or E2E components trigger an exit code of `1`, passing the consolidated log to the LLM agent for resolution.

---

## 5. Test-Fix Retry Loops, Escalation & Deterministic Authority

When `iterate_test: true` is enabled, the pipeline enters an autonomous loop to resolve failing tests.

```
                             Autonomous Iteration Loop
                                         │
                              Execute Test Command
                                         │
                             Did Test Pass? (rc == 0)
                                   ┌─────┴─────┐
                                  YES          NO
                                   │           │
                             Return True   Format Failure Log as Prompt
                                               │
                                           Run Aider Edit Pass
                                               │
                                  Reached Max Outer Loops?
                                       ┌───────┴───────┐
                                      YES              NO
                                       │               │
                            Run final_check pass    Continue Next Attempt
                                       │
                              Return Exit Code
```

### Inner vs. Outer Loop Mechanics

1. **Aider Internal Loops (`auto_test: true`):** Aider manages up to 3 fast internal fix-and-test attempts before yielding back to Python.
2. **Orchestrator Outer Loops (`loop_aider_test`):** `orchestrate.py` manages the outer loop ceiling (defaulting to 1). On each outer attempt, fresh failure logs are captured and passed as a new prompt to Aider.
3. **Outer Loop Tracking (`VALIDATION_ATTEMPT`):** The orchestrator injects `VALIDATION_ATTEMPT: str(attempt)` into the test subprocess environment. This allows contextual validators (like `validator.py`) to track outer loop progress and reset their no-progress ledgers on attempt 0.

### Eliminating False Positives: `Task.final_check` & `Task.soft_fail`

Because Aider's iterative loop verifies attempt $N-1$ at the start of attempt $N$, the *final* edit in a sequence is not automatically re-tested by the loop structure itself.

To prevent false-positive failure reports when the final edit actually fixed the issue:

- **`Task.final_check`:** Re-executes the test command exactly once after loop exhaustion. If the test passes, the task returns `TaskStatus.SUCCESS`.
- **`Task.soft_fail`:** In evidence grounding or multi-phase review flows, loop exhaustion is treated as a soft success, deferring terminal judgment to a downstream `finalize` step.

---

## 6. Bundled Test Runners & Reference Implementations

The AI Factory packages optimized reference test runners in `src/aider_factory/tests/`.

### R / testthat Reference Runner (`src/aider_factory/tests/run_tests.R`)

The bundled R test runner provides noise reduction and precision handling:

```r
options(cli.unicode = FALSE)
args <- commandArgs(trailingOnly = TRUE)
if (length(args) == 0) {
  stop("Must provide a test filter pattern or file path")
}

input_arg <- args[1]
base_name <- basename(input_arg)
base_name <- sub("\\.R$", "", base_name, ignore.case = TRUE)
if (grepl("^test-", base_name)) {
  base_name <- sub("^test-", "", base_name)
}

test_filter <- paste0("^", base_name, "$")

Sys.setenv(TESTTHAT_MAX_FAILS = "Inf")
options(testthat.max_fails = Inf)

# Suppress global warnings to prevent context window bloat
options(warn = -1)
options(bit64.promoteInteger64ToCharacter = TRUE)

res <- testthat::test_dir("tests/testthat", filter = test_filter)

if (length(res) == 0) {
  quit(status = 1)
}

res_df <- as.data.frame(res)
fails <- sum(unlist(res_df$failed), na.rm = TRUE)
errs <- sum(unlist(res_df$error), na.rm = TRUE)

if ((fails + errs) > 0) {
  quit(status = 1)
}

quit(status = 0)
```

### Key Features of `run_tests.R`

1. **Warning Suppression (`options(warn = -1)`):** Blocks non-fatal package warnings (e.g., `bit64` integer conversions) from cluttering LLM context windows.
2. **Precision Filter Extraction:** Strips path prefixes and `.R` extensions to convert file paths into exact `testthat` filter regexes (`^stem$`).
3. **Uncapped Failure Capture (`TESTTHAT_MAX_FAILS = Inf`):** Prevents `testthat` from aborting early so the LLM receives the full set of failures across the test suite.
