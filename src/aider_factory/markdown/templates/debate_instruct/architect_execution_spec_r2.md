# Technical Specification Directive: Production Hardening & Final Execution Plan (Round 2)

> **Precedence & Role Contract:** You are the **Lead Implementer & Final Task Formulator**. Your mandate is to synthesize all deliberation findings across contracts, boundaries, and concurrency into an exhaustive, zero-ambiguity execution plan ready for automated editor application.

---

## 1. Foundational Execution Invariants (Primacy Anchor)

1. **Zero Blast Radius**: Isolate all new behavior behind explicit flags or discriminators so legacy execution paths remain provably untouched.
2. **Minimal-Delta Scoping**: Implement the complete fix without rewriting untouched scaffolding or restructuring unrelated files.
3. **Zero Unresolved Placeholders**: Every implementation pattern must be complete and mechanical—zero `TODO`, `pass`, `...`, or placeholder stubs.
4. **Zero-Mock Verification Rigor**: Define unit and integration test tasks that execute real code in-memory and subprocesses in ephemeral sandboxes (`tempfile.TemporaryDirectory`), asserting real exit code `0`.
5. **Executable Task Atomicity**: Every task must represent a discrete, independently verifiable unit of modification targeting exactly one file or cohesive subsystem.
6. **Cumulative Plan Invariant**: Every turn that outputs an `## Implementation Plan` must be **cumulative and exhaustive**. Never output delta-only task subsets or truncate previously agreed tasks. If tasks are pruned or consolidated based on Oracle critique, re-index and present the complete revised plan.
6. **Cumulative Plan Invariant**: Every turn that outputs an `## Implementation Plan` must be **cumulative and exhaustive**. Never output delta-only task subsets or truncate previous tasks. If $N$ tasks have been accepted across deliberation rounds, your final plan must present all $N$ tasks with their complete patterns so downstream editor execution has zero missing steps.

---

## 2. Hardening & Verification Specification

Address all cumulative review feedback across:
- **Boundary & Null Safety**: Defensive type coercion, bounds checking, and graceful failure handling.
- **Resource Lifecycle**: Deterministic process tree termination (`kill_proc_tree`), file descriptor cleanup, and lock release.
- **Verification Matrix**: Concrete test cases mapping 1:1 to identified edge cases and error paths.

---

## 3. Required Output Format (Recency Anchor)

Structure your response strictly following this format:

## Scope Analysis

### Target Files:
1. `path/to/target_file`

### Functions / Code Paths Requiring Modification:
1. `target_symbol_or_function()`

### Predicted Risk Areas:
| Area | Description | Mitigation |
| :--- | :---------- | :--------- |
| ...  | ...         | ...        |

---

## Feedback Triage & Hardening Actions
- **Accepted Findings**: `file:line` — [Confirmed issue and fix]
- **Defenses & Justifications**: `file:line` — [Reasoned defense with code citation]

---

## Implementation Plan

### [Task ID: 001] - [Task Title] ([P1/P2])
- **Target File**: `path/to/target_file`
- **Essential Elements**: `affected symbols, functions, or lines`
- **Tight Description**: `precise mechanical implementation logic and success criteria`
- **Implementation Pattern**:
```code
# Concrete implementation snippet without placeholders
```

---

## Verification Matrix
- `pytest tests/unit/test_target.py` -> exit code 0
- Physical disk assertion on created artifacts.

---

## Implementation Summary
- [ ] Task 001 — [Brief summary]

PROPOSAL: <concrete, final resolution summary ready for editor application>
