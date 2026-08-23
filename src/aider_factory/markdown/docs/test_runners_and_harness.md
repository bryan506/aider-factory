# Language-Agnostic Test Harness & Execution Engine

> **Context Anchor & Authoring Directive:**  
> This document is the definitive master specification for language-agnostic test suite integration, containerized execution wrappers, test-fix retry loops, and deterministic final-check verification.  
> **Source References:** `factory_service_manual.md` under headers `### Containerized Test Execution (Docker)`, `### Customizing the Test Runner (language-agnostic)`, `#### How Combined Unit + E2E Testing Operates`, `### Iteration Loops & Fallback Logic`, `#### The same skeleton in CODE mode`.  
> **Codebase References:** `src/aider_factory/python/orchestrate.py` (`Task`, test execution loops, `Task.final_check`, `Task.soft_fail`), `src/aider_factory/tests/run_tests.R`, `src/aider_factory/cli.py` (`_is_test_path`).  
> **Target Scope to Reconcile:**  
> 1. **Language-Agnostic Test Configuration:** Mapping `{test_command_prefix} {test_runner}` with `{file}` substitution across R (`testthat`), Python (`pytest`), Rust (`cargo test`), Go (`go test`), and Bash scripts.  
> 2. **Combined Unit + E2E Execution:** Multi-suite pytest execution (`uv run --with pytest pytest ...`) with ephemeral sandbox dependencies.  
> 3. **Autonomous Test-Fix Loops & Escalation:** Mechanics of `iterate_test: true`, `auto_test: true`, `loop_aider_test`, and escalation debate triggers.  
> 4. **Deterministic Authority (`Task.final_check` & `Task.soft_fail`):** Eliminating false-positive failures by re-evaluating the test suite exit code after loop exhaustion.  
> 5. **Mandatory 6-Section Topology:** Adhere strictly to `implement_docs.md`.
