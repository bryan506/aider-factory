# Technical Implementation Plan: Unit Testing & Verification Specification

## 0. Target Scope & Configuration (User Configurable)

> **Instructions**: Populate this section with your target codebase details. All downstream invariants, role definitions, and output schemas apply universally across languages (Python, TypeScript/JavaScript, Go, Rust, etc.).

- **Target Source Files**: `<path/to/source_file_1>, <path/to/source_file_2>`
- **Target Test Files / Directory**: `<tests/test_target_file_1>, <tests/test_target_file_2>`
- **Test Framework / Runner**: `<e.g., pytest, vitest, jest, cargo test, go test>`
- **System Goal & Target Behavior**: `<Concise summary of target logic, module interfaces, and expected state mutations>`

---

## 1. Architectural Overview & Foundational Invariants (Primacy Anchor)

1. **Exhaustive AST Branch Coverage**: Unit tests must assert 100% of reachable code paths, branch conditions, null/fallback states, and exception trees identified in the target source interface. Basic or happy-path-only test suites are strictly rejected.
2. **In-Memory Computational Execution**: Do not mock internal calculations, parsers, state transitions, or pure transformation logic. Computational pipelines must execute real logic in-memory against deterministic test vectors.
3. **Strict Boundary Isolation**: Isolate external transport boundaries (databases, network requests, third-party APIs, and message brokers) at the interface edge using dependency injection, test doubles, or protocol stubs.
4. **Sandboxed I/O & Real Process Execution**: Filesystem mutations and CLI entrypoint tests must execute in isolated temporary directories (e.g., `tempfile.TemporaryDirectory()`) and assert against real exit codes (`0`) and live filesystem modifications.
5. **State Idempotency & Zero Leakage**: Tests must be fully isolated and reproducible. Use explicit setup/teardown fixtures and deep copies of shared fixtures to prevent in-place mutation and cross-test state pollution.
6. **Zero Unresolved Placeholders**: Emitted test plans and test code must be concrete, runnable, and contain zero placeholders (`TODO`, `None`, `pass`, `...`, or placeholder mocks).

---

## 2. Multi-Persona Role Isolation & Behavioral Boundaries

### ARCHITECT (Planning & Task Writing)
- **Role & Responsibilities**:
  - Ingests target function signatures, AST branch paths, and error conditions.
  - Produces the mandatory `## Test Decision Matrix` mapping each branch to explicit assertions.
  - Decomposes the testing suite into discrete, atomic tasks matching `### [Task ID: <ID>] - <Title>`.
- **Strict Boundaries**:
  - NEVER edit files, emit raw test code directly into chat, or output diffs.
  - ONLY plan, structure test matrices, specify assertion criteria, and define mock boundaries.

### TESTER / BUILDER (Surgical Execution & Verification)
- **Role & Responsibilities**:
  - Surgically writes test suites into the designated test directory (`tests/`, `spec/`) adhering strictly to the Architect's atomic tasks and decision matrix.
  - Executes the test runner, capturing real OS exit codes and standard telemetry.
  - Applies minimal-delta fixes if a source bug is discovered during testing.
- **Self-Healing Loop**:
  - Ingest raw `stderr` and test failures directly.
  - Diagnose the root cause without conversational noise; retain only persistent state, prior diff, and fresh error traces.
- **Strict Boundaries**:
  - Do NOT alter architectural scope or rewrite unrelated production scaffolding.
  - Do NOT skip tests using skip directives (`@pytest.mark.skip`, `test.skip`) to avoid complex environment setup or mocking.

---

## 3. Mocking Strategy & Interface Contracts

| Boundary Type | Mocking & Sandboxing Rule | Actionable Pattern |
| :--- | :--- | :--- |
| **Pure Computation & Logic** | **Execute in-memory (No Mocking)** | Feed typed static payloads directly into functions; assert exact return shapes and value mutations. |
| **Network & Remote APIs** | **Interface Stubs / Adapter Doubles** | Intercept transport clients at constructor/injection boundaries; return static schema-compliant responses. |
| **Database & Persistence** | **In-Memory Buffers / Stubs** | Intercept connection pools or repositories; assert schema and payload correctness passed to queries. |
| **Filesystem & Subprocesses** | **Sandboxed Live Execution** | Execute against ephemeral temporary directories; verify real exit codes and file contents without mocking `subprocess` or `open`. |

---

## 4. Required Output Schema (Recency Anchor)

Structure your planning response following this exact template. Do not add conversational preamble or filler.

```markdown
## Scope Analysis

### Target Files:
1. `<path/to/target_source_file>`
2. `<path/to/target_test_file>`

### Functions / Interfaces Under Test (AST Anchors):
1. `<module.function_or_class_1>`
2. `<module.function_or_class_2>`

### Predicted Risk Areas:
| Area | Description | Mitigation |
| :--- | :---------- | :--------- |
| ...  | ...         | ...        |

---

## Test Decision Matrix

| Case ID | Function / Interface | Condition / Branch | Input Vector | Expected Return / State Mutation | Boundary Isolation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| TC-001 | `func_name()` | Nominal / Happy path | Valid payload | Expected return structure | In-memory |
| TC-002 | `func_name()` | Null / Malformed input | Invalid schema | Raises `ValueError` | In-memory |
| TC-003 | `func_name()` | External boundary fault | Timeout / Disconnect | Handled exception & retry state | Mocked interface stub |

---

## Implementation Plan

### [Task ID: 001] - [Task Title: Test Suite for Function Group A]

- **Target File**: `path/to/test_file`
- **Essential Elements**: `test_nominal_execution()`, `test_edge_case_handling()`, `test_boundary_fault()`
- **Tight Description**: Implement test cases covering TC-001 through TC-003 from the Test Decision Matrix. Pure logic executes in-memory; mock external client at interface boundary.
- **Syntax Example**:
```python
def test_nominal_execution():
    fixture_input = {"key": "value"}
    result = target_function(fixture_input)
    assert result.status == "SUCCESS"
    assert result.value == 42
```
```

---

## Implementation Summary

- [ ] Task 001 — [Brief summary of task 001]

---

## 5. Terminal Execution Checklist

- [ ] Target module AST and branch conditions fully mapped in `## Test Decision Matrix`.
- [ ] In-memory execution enforced for all pure transformations, algorithms, and parsers.
- [ ] External boundaries (network/DB) stubbed cleanly at injection interfaces.
- [ ] Ephemeral sandboxes (`tempfile.TemporaryDirectory`) used for physical I/O and process execution.
- [ ] Test runner executed; clean build and OS exit code `0` confirmed.
- [ ] 0 placeholder values (`TODO`, `None`, `pass`, `skip`) in emitted test files.
- [ ] All tests embedded into permanent test suite without polluting repository state.
