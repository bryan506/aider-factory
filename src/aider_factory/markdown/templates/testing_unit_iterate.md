# Autonomous Unit Test Iteration & Self-Healing Playbook

---

## Task Configuration (User-Specified Parameters)

- **Target Source File**: `path/to/source_file`
- **Target Test File**: `path/to/test_file`
- **Test Execution Command**: `pytest path/to/test_file` # e.g., cargo test, npm test, pytest, go test
- **Diagnostic / Error Trace**:
```text
<Paste raw test runner output, failing assertion, and stack trace here>
```

---

## 1. Foundational Invariants (Primacy Anchor)

1. **Deterministic-First Test Isolation**: Every test must run deterministically in any sequence without cross-test state leakage. Scoped fixtures and ephemeral environments (`tmp_path`, `tempfile.TemporaryDirectory`) must be used for disk mutations.
2. **Zero-Mock Core Logic (Boundary-Only Mocking)**:
   - **Internal Computation**: Never mock internal transformation logic, parsing algorithms, data models, or core business rules. Execution must flow through real application code.
   - **External I/O Interception**: Mock strictly at external system boundaries (remote HTTP/gRPC endpoints, database connections, message queues, third-party RPCs, hardware sensors).
3. **Preservation of Passing Contracts**: Existing passing tests and established public interface signatures must remain intact. Do not weaken assertions or skip tests to mask unhandled failure modes.
4. **Minimal-Delta Scoping**: Repair logic strictly at the root cause. Do not refactor unrelated subsystems or perform wholesale file rewrites. Split changes into manageable, chunked edit blocks.
5. **Strict File Scope**: Confine edits exclusively to the assigned target source file and target test file.

---

## 2. Self-Healing ReAct Feedback Loop & Anti-Oscillation

When diagnosing and fixing test failures, structure iterative turns into three distinct phases:

1. **`Observation`**: Ingest the raw diagnostic telemetry (failing assertion, line number, exit code, type error) without truncation or paraphrasing (*Fidelity at the Boundary*).
2. **`Reflection`**: Identify the mechanical root cause (e.g., parameter edge case, off-by-one, stale mock return schema, race condition) rather than treating surface symptoms.
3. **`Action`**: Apply a minimal-delta code edit to the target source or test file.

### Anti-Oscillation & Debug Pruning Rules:
- **Prune Stale Traces**: In iterative repair loops, drop obsolete intermediate error traces from earlier attempts ($0 \dots N-1$). Retain only:
  1. The immutable system prefix and active task parameters.
  2. The most recent patch/diff.
  3. The fresh error trace from the latest run.
- **Circuit Breaker**: If an error oscillates or fails to resolve within 3 iterations, halt execution, preserve the diagnostic state, and escalate rather than cycling indefinitely.

---

## 3. Mocking & Test Execution Directives

- **Fixture Hermeticity**: Use factory constructors or deep copies for shared test payloads to prevent in-place reference mutations from leaking across test cases.
- **Affirmative In-Place Edits**: Extend and repair existing test files in place, matching existing codebase style, naming conventions, and assertion libraries.
- **Concrete Mock Implementations**: Implement complete mock responses matching required downstream schemas. Avoid unresolved placeholders or stubs.
- **Chunked Search/Replace**: Structure modifications into concise, unambiguous edit blocks matching exact indentation and whitespace.

---

## 4. Required Output Format (Recency Anchor)

```markdown
## Scope Analysis

### Target Files:
1. `path/to/source_file`
2. `path/to/test_file`

### Root-Cause Diagnosis:
- **Failure Mechanism**: `<exact assertion failure, unexpected state, or type error>`
- **Correction Strategy**: `<precise logic or fixture adjustment to satisfy invariant>`

---

## Implementation Plan

### [Task ID: 001] - [Source Repair or Test Expansion]
- **Target File**: `path/to/target_file`
- **Essential Elements**: `target_function_or_method()`
- **Tight Description**: `Precise logic update, parameter bounds, and expected return value`
- **Syntax Example**:
```code
# Concrete snippet matching target language idioms without placeholders
```
```

---

## 5. Terminal Verification Checklist

- [ ] Diagnosed failing test telemetry down to exact line number and invariant violation.
- [ ] Mocks restricted strictly to external I/O boundaries; internal processing executes fully.
- [ ] Source and test edits split into minimal, targeted replacement chunks.
- [ ] No state mutations leak between test cases (deep copies / ephemeral sandboxes used).
- [ ] All tests in target test suite pass deterministically with clean OS exit code `0`.
- [ ] Regression suite and public API contracts remain unbroken.
