# Dual Static Repository Mapping & Test Path Classification

`aider-factory` features a zero-clutter repository mapping engine that generates separate, token-budgeted static AST maps for production code vs. test suites.

---

## 1. Dual-Map Architecture

Standard repository maps mix test fixtures, unit tests, and source code together, overflowing context windows and degrading KV-cache retention. The AI Factory generates two isolated maps:

1. **`static_repo_map.md` (Source-Only)**: Contains AST tags and call graphs for application source code. All tests, benchmarks, and fixtures are excluded.
2. **`static_repo_map_tests.md` (Test-Only)**: Contains AST symbols for test suites and test helpers. All production source code is excluded.

```bash
# Generate source-only repository map
aider-factory --repo-map

# Generate test-only repository map
aider-factory --repo-map-tests

# Generate both maps simultaneously
aider-factory --repo-map-all

# Override token budget (default: 4096 tokens)
aider-factory --repo-map --map-tokens 8192
```

---

## 2. Multi-Tier Test Path Classifier (`_is_test_path`)

The classifier in `cli.py` uses a 4-tier decision waterfall to detect test files across all major programming languages:

```python
def _is_test_path(rel_path: str) -> bool:
    clean_path = rel_path.replace("\\", "/").strip("/")
    parts = clean_path.split("/")
    
    # Tier 1: Directory Component Check
    for p in parts[:-1]:
        if p.lower() in TEST_DIR_NAMES:
            return True
            
    # Tier 2: Delimited Filename Pattern (case-insensitive)
    if TEST_DELIMITED_RE.search(clean_path):
        return True
        
    # Tier 3: Exact Test Harness Filenames (case-insensitive)
    if TEST_EXACT_RE.search(clean_path):
        return True
        
    # Tier 4: CamelCase Class Files (case-sensitive)
    if TEST_CAMEL_RE.search(clean_path):
        return True
        
    return False
```

### Classification Rules Breakdown
| Tier | Target Patterns | Examples |
| :--- | :--- | :--- |
| **1. Directories** | `TEST_DIR_NAMES` | `tests/`, `testthat/`, `__tests__/`, `spec/`, `e2e/`, `fixtures/`, `benchmarks/` |
| **2. Delimited Patterns** | `TEST_DELIMITED_RE` | `test_auth.py`, `user.test.ts`, `risk-test.R`, `order_spec.rb` |
| **3. Exact Files** | `TEST_EXACT_RE` | `conftest.py`, `tests.py`, `tests.rs`, `test_helper.rb`, `setupTests.ts` |
| **4. CamelCase Classes** | `TEST_CAMEL_RE` | `UserTest.java`, `AuthSpec.scala`, `OrderTestCase.php` |

---

## 3. Ephemeral `.aiderignore` Synthesis (`_build_repomap_ignore_content`)

To generate maps without mutating the user's workspace `.aiderignore`, the generator creates ephemeral ignore files (`.aiderignore_source` and `.aiderignore_tests`):

1. **User Rule Preservation (`_read_user_aiderignore`)**: Reads active rules from workspace `.aiderignore`.
2. **Dynamic Exclusion**: Scans all repository files via `git ls-files` and filters them using `_is_test_path()`.
3. **Execution**: Invokes `aider --map-tokens <N> --show-repo-map` targeting the ephemeral ignore file.
4. **Cleanup**: Automatically unlinks the ephemeral ignore file upon completion.

---

## 4. KV-Cache & VRAM Optimization

By locking static repository maps into context (`--read .aider_factory/markdown/static_repo_map.md`), you can set:
```yaml
toggles:
  map_tokens: 0       # Disables dynamic background map generation
  map_refresh: manual # Prevents periodic repository re-scans
```
This ensures the LLM's system prompt prefix remains 100% stable across all turns, maximizing KV-cache hit rates on local inference servers.
