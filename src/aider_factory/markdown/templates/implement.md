# Technical Implementation Plan (technical_specs): {{SYSTEM_GOAL}}

> **Precedence & Governance:** This implementation blueprint establishes the technical execution contract between the Architect (Planning) and Editor (Execution) roles. All modifications must adhere strictly to the Minimal-Delta Invariant, deterministic-first logic, and local repository conventions.

---

## 1. Primacy Context: Architectural Overview & System Invariants

- **System Goal**: {{SYSTEM_GOAL_DESCRIPTION}} (Explicitly define the primary architectural objective, targeted behaviors, and boundary outcomes).

- **Architectural Pattern & State Strategy**: {{ARCHITECTURAL_PATTERN_DESCRIPTION}} (Identify structural patterns, helper abstractions, mode discriminators, and state/cache parity invariants to be introduced or preserved).

- **Scope & Code Flow Analysis**:
  1. **Interface & Variable Initialization**: Declare and scope all required variables and function signatures at the entry point of the targeted routine. Prune obsolete or unreferenced artifacts.
  2. **Deterministic Time & Event Sequencing**: Ensure execution ordering, event loops, and chronological data flows follow deterministic boundaries and handle edge cases gracefully.
  3. **Data Schema & Symbol Parity**: Enforce consistent structural naming, field schemas, and serialization formats across all transformations.
  4. **Minimal-Delta Scaffolding**: Preserve existing caller contracts, function signatures, and surrounding scaffolding. Isolate new behaviors behind discriminators or explicit mode flags.
  5. **Artifact Pruning**: Surgically refactor and remove legacy structures or stale logic while strictly maintaining the core domain intent.

- **Architect Role Contract**:
  - Restrict output strictly to conversational markdown technical plans labeled `technical_specs` and `tasks`.
  - Maintain read-only analysis; do not invoke file-editing tools or execute code modifications directly.
  - Detail edge cases, state management tradeoffs, and verification criteria within the specification.

- **Load-Bearing Architectural Invariants**:
  - **Invariant 1 (Boundary Enforcement)**: Confine all planned modifications strictly to the explicitly assigned target file(s). Leave unassigned reference files and configuration intact.
  - **Invariant 2 (Deterministic In-Memory State)**: Gate execution paths behind explicit availability checks for required inputs. Handle missing or partial inputs via deterministic fallback branches rather than synthetic placeholders.
  - **Invariant 3 (Idempotent Transform / Serialization)**: Perform deserialization/unpacking and serialization/packing operations deterministically and minimally (e.g., unpack once at input boundary, pack once at output boundary).
  - **Invariant 4 (Reference Strictness)**: Treat reference files strictly as structural/syntactic patterns. Do not copy external domain logic or incompatible variable names into the target file.
  - **Invariant 5 (Minimal-Delta Invariant)**: Modify only the specific code spans necessary to fulfill the system goal. Preserve all existing error handling, logging patterns, and caller contracts.

---

## 2. Execution Strategy (Editor / Builder Role)

> **Contract for Editor**: Purely execute the atomic tasks provided by the Architect without altering unassigned logic or inventing new architectures.

- **Atomic Task Execution**: Execute changes sequentially following each task's `Tight Description` and `Task ID`. When multiple variables or paths are scoped, implement all of them explicitly.

- **Diff Parsing & Replacement Invariants**:
  - **Code Deletion Marker**: When deleting lines or blocks of code, populate the replacement region with an explicit comment marker (e.g., `# Removed` or `// Removed`). Never leave the replace block completely empty.
  - **Empty File Creation**: When creating a new file or populating an empty file, maintain an empty search block (zero lines between `<<<<<<< SEARCH` and `=======`).
  - **Smallest Context Footprint**: Anchor each SEARCH/REPLACE block to the smallest unique surrounding context lines. Prefer multiple atomic blocks over a single massive replacement block.

- **Scope & Local Variable Parity**: Validate that referenced variables, imports, and types exist within the target scope. Match the syntax and naming conventions of the surrounding target file.

- **Deterministic Fallback**: If a task requires editing an unassigned file or encountering missing specifications, halt execution and request architectural clarification.

---

## 3. Implementation Phases (The Lifecycle)

- **Phase 1 -- Algorithmic Preservation**: Map existing control flows, mathematical logic, and error branches in the target file. Preserve the original business intent and quantitative correctness while refactoring structural patterns.

- **Phase 2 -- Scope Analysis (AST Targeting)**: Prior to task generation, output the `## Scope Analysis` section listing every target file, function, class, and variable path requiring modification.

- **Phase 3 -- Atomic Task Planning**: Decompose the implementation plan into self-contained, sequentially numbered tasks adhering to the strict task schema.

- **Phase 4 -- Surgical Execution & AST Verification**: The Editor applies the atomic tasks one by one, verifying syntax validity and local test compliance before concluding.

---

## 4. Atomic Task List Specification

> Architect: Provide a discrete, atomic specification for every modification. If a refactor affects N distinct functions or files, create N separate Task IDs. Do not combine large rewrites into a single task.

### [Task ID: 001] - [Task Title]

- **Target File**: `path/to/target_file.ext`
- **Essential Elements**: (Comma-separated list of functions, classes, variables, or structures affected)
- **Tight Description**: Provide the exact implementation logic — inputs, outputs, error conditions, and concrete operational steps.
- **Syntax Example**: (Concrete code snippet matching existing file conventions without placeholders such as `TODO`, `NULL`, `None`, or "if needed")

```language
// Concrete, runnable syntax example matching target language conventions
```

---

## 5. Terminal Recency: Required Output Schema

Structure your technical plan strictly according to this template. Do not add conversational filler.

```markdown
## Scope Analysis

### Target Files:

1. `path/to/target_file.ext`

### Functions / Code Paths Requiring Modification:

1. `target_function_or_method()` — (AST target and modification summary)

### Predicted Risk Areas:

| Area             | Description | Mitigation |
| ---------------- | ----------- | ---------- |
| State Regression | ...         | ...        |
| Edge Case Branch | ...         | ...        |

---

## Implementation Plan

### [Task ID: 001] - [Title]

- **Target File**: `path/to/target_file.ext`
- **Essential Elements**: `function_name`, `variable_scope`
- **Tight Description**: ...
- **Syntax Example**:
  ```language
  ...
  ```
```

---

## Implementation Summary

- [ ] Task 001 — [Action description and success criteria]

```

```
