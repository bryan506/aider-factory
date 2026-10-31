# Strategy Template (Source of Truth)

## Scope Analysis
```yaml
files:
  target_files: []          # Specify EXACTLY ONE existing primary anchor file (drives <stem> naming)
  extra_editable_files: []  # Additional existing files to edit alongside the anchor file in this pass
  test_files: []            # Leave empty ([]) to auto-assign unit test file via <stem>, or specify 1 test file
  context_files_job: []     # Read-only reference files for implementation (Job 1 & Job 2)
  context_files_test: []    # Read-only reference files for unit testing (Job 3 & Verify)
```

## 1. Scope
- [Define implementation/refactoring scope and objectives]

## 2. Definitions & Formulas
- [Exact definitions, formulas, and domain rules with source citations]

## 3. Inputs & Outputs
- [Names, types, units, and valid ranges]

## 4. Edge Cases & Constraints
- [Boundary behavior and error handling expectations]

## 5. Acceptance Criteria
- [Concise, testable statements]
