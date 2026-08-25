# Dual Static Repository Mapping & Test Path Classification

## 1. Executive Overview & Foundational Invariants

The `aider-factory` pipeline features a zero-clutter repository mapping engine that generates separate, token-budgeted static Abstract Syntax Tree (AST) maps for production code versus test suites. Standard repository maps mix test fixtures, unit tests, and source code together, overflowing LLM context windows, contaminating AST symbol trees, and degrading KV-cache retention. The AI Factory strictly isolates these domains.

### Foundational Invariants
- **Domain Isolation:** Production source code ($D_{src}$) and test suite code ($D_{test}$) must never share the same AST context map.
- **KV-Cache Stability:** Static maps must be pre-computed and passed as read-only context (`--read`) to freeze the LLM's system prompt prefix, ensuring $100\%$ KV-cache hit rates on local inference servers.
- **Ephemeral Immutability:** The user's root `.aiderignore` file must never be permanently mutated by the mapping engine; all domain filtering relies on ephemeral drop-in files (`.aiderignore_source`, `.aiderignore_tests`) that are cleaned up immediately post-generation.
- **Zero-Loss Fallback:** If Git tracking fails or is unavailable in the execution environment, file discovery must gracefully fall back to physical filesystem traversal (`os.walk`) without dropping structural rules.

---

## 2. System Topology & Lifecycle Flowcharts

The repository mapping lifecycle dynamically discovers workspace files, classifies them via a multi-tier regex cascade, and synthesizes targeted AST maps using Aider's core Tree-Sitter tag engine.

```text
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                          DUAL STATIC REPOSITORY MAPPING LIFECYCLE                         │
├─────────────────────────┬──────────────────────────┬──────────────────────────────────────┤
│ 1. Discovery            │ 2. Classification        │ 3. Synthesis & Cleanup               │
├─────────────────────────┼──────────────────────────┼──────────────────────────────────────┤
│                         │                          │ ┌─► .aiderignore_source (Ephemeral)  │
│ ┌─► git ls-files        │ ┌─► _is_test_path()      │ │   └─► static_repo_map.md           │
│ │   (Fast Path)         │ │   (4-Tier Regex)       │ │                                    │
│ ├───────────────────────┤ ├────────────────────────┤ ├────────────────────────────────────┤
│ │                       │ │                        │ │                                    │
│ └─► os.walk fallback    │ └─► User .aiderignore    │ ┌─► .aiderignore_tests (Ephemeral)   │
│     (If Git fails)      │     (Base Rules)         │ │   └─► static_repo_map_tests.md     │
│                         │                          │ │                                    │
│                         │                          │ └─► os.remove(*ephemeral_files)      │
└─────────────────────────┴──────────────────────────┴──────────────────────────────────────┘
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### 3.1 Mathematical Domain Isolation
Let the complete workspace file set be $F = \{f_1, f_2, \dots, f_n\}$. We partition $F$ into two strictly disjoint subsets using the classification predicate $\text{is\_test\_path}(f) \in \{\text{True}, \text{False}\}$:

$$D_{test} = \{ f \in F \mid \text{is\_test\_path}(f) = \text{True} \}$$

$$D_{src} = \{ f \in F \mid \text{is\_test\_path}(f) = \text{False} \} = F \setminus D_{test}$$

By formulation:
$$D_{src} \cap D_{test} = \emptyset \quad \text{and} \quad D_{src} \cup D_{test} = F$$

This formal partitioning guarantees that symbol graph generation for $D_{src}$ operates in complete isolation from $D_{test}$, preventing AST node pollution and token inflation.

### 3.2 Dual-Map Architecture
The engine generates two isolated maps:
1. **`static_repo_map.md` (Source-Only)**: Represents $D_{src}$. Contains AST tags, definitions, and call graphs for application source code. All tests, benchmarks, and fixtures are excluded.
2. **`static_repo_map_tests.md` (Test-Only)**: Represents $D_{test}$. Contains AST symbols for test suites and test harness helpers. All production source code is excluded.

### 3.3 Multi-Tier Test Path Classifier (`_is_test_path`)

The classifier in `cli.py` uses a 4-tier decision waterfall to detect test files across Python, R, JavaScript/TypeScript, Rust, C/C++, Java, Go, and Ruby:

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

### 3.4 Ephemeral `.aiderignore` Synthesis (`_build_repomap_ignore_content`)

To generate maps without mutating the user's workspace `.aiderignore`, the generator creates ephemeral ignore files (`.aiderignore_source` and `.aiderignore_tests`):

1. **User Rule Preservation (`_read_user_aiderignore`)**: Reads active rules from workspace `.aiderignore`.
2. **Dynamic Exclusion**: Scans all repository files via `git ls-files` (falling back to `os.walk` if Git is unavailable) and filters them using `_is_test_path()`.
3. **Execution**: Invokes `aider --map-tokens <N> --show-repo-map` targeting the ephemeral ignore file.
4. **Cleanup**: Automatically unlinks the ephemeral ignore file upon completion.

---

## 4. Exhaustive CLI & Parameter Reference

The repository mapping engine is invoked directly via the `aider-factory` CLI or the `aider-helper` CLI wrapper.

| Command | Description | Exit Codes | Runtime Behaviors |
| :--- | :--- | :--- | :--- |
| `aider-factory --repo-map` | Generates source-only repository map (`static_repo_map.md`). | `0`: Success<br>`1`: Process Error | Synthesizes `.aiderignore_source`, runs Aider AST extraction (default: 4096 tokens), unlinks ephemeral ignore file. |
| `aider-factory --repo-map-tests` | Generates test-only repository map (`static_repo_map_tests.md`). | `0`: Success<br>`1`: Process Error | Synthesizes `.aiderignore_tests`, runs Aider AST extraction (default: 4096 tokens), unlinks ephemeral ignore file. |
| `aider-factory --repo-map-all` | Generates both maps sequentially. | `0`: Success<br>`1`: Process Error | Executes source mapping pass followed immediately by test mapping pass. |
| `aider-factory --repo-map --map-tokens <N>` | Overrides AST token budget for generated map. | `0`: Success<br>`1`: Invalid Token Value | Passes `--map-tokens <N>` directly to Aider subprocess to adjust tree depth. |
| `aider-helper query --repo-map -t "<prompt>"` | Injects `static_repo_map.md` into helper query context. | `0`: Success<br>`1`: Missing Map File | Reads `.aider_factory/static_repo_map.md` or `.aider_factory/markdown/static_repo_map.md` and appends it to the `<repository_map>` block. |

---

## 5. Configuration Schema & YAML Knobs

Runtime repository mapping parameters are configured under the `toggles:` block in `.env.yml` or session-specific `session.yml` files. These settings directly map to `orchestrate.py` and `run_workflow.py` configuration compilation logic.

```yaml
phases:
  - name: "Implementation Phase"
    toggles:
      map_tokens: 0                     # type: int, default: None
                                        # Overrides Aider --map-tokens. Setting to 0 disables dynamic AST map generation.

      map_refresh: "manual"             # type: str, default: None ("auto")
                                        # Overrides Aider --map-refresh. Options: "auto", "manual", "always".

      map_multiplier_no_files: 0.0      # type: float, default: None
                                        # Overrides Aider --map-multiplier-no-files. Multiplier when no files are open.

      max_chat_history_tokens: 100000   # type: int, default: None
                                        # Overrides Aider --max-chat-history-tokens. Caps conversation history token budget.

    files:
      context_files_job:
        - ".aider_factory/markdown/static_repo_map.md"
```

### Parameter Mapping & KV-Cache Impact
- **`map_tokens: 0`**: Prevents Aider from continuously re-generating dynamic repo maps during editing passes, maintaining a static system prompt prefix.
- **`map_refresh: "manual"`**: Freezes AST map recalculation, eliminating periodic tree recalculation overhead.
- **`context_files_job`**: Loading `.aider_factory/markdown/static_repo_map.md` as read-only context (`--read`) freezes the map into the prompt prefix, guaranteeing $100\%$ KV-cache retention on local inference servers.

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

| Failure Mode / Edge Case | Signature | Recovery Procedure / Mitigation |
| :--- | :--- | :--- |
| **Git Executable Missing** | `subprocess.run(["git", "ls-files"])` throws `FileNotFoundError` or returns non-zero exit code. | The pipeline automatically falls back to `os.walk`, excluding a hardcoded list of directories (`.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`) to prevent indexing massive binaries. |
| **Ephemeral Cleanup Failure** | Process terminates unexpectedly mid-generation, leaving `.aiderignore_source` on disk. | The `finally` block in `_generate_repo_maps` guarantees cleanup. If a hard `SIGKILL` occurs, subsequent runs automatically overwrite stale ephemeral files before execution. |
| **Token Budget Truncation** | A massive repository results in an AST larger than `--map-tokens`. | Aider's core engine automatically truncates the AST graph, prioritizing files recently modified or referenced in active git commits. Increase token budget (`--map-tokens 8192`) if critical symbol nodes are missing. |
| **Missing Baseline `.aiderignore`** | The root `.aiderignore` is deleted or corrupted by user scripts. | `_ensure_baseline_aiderignore()` detects missing baseline files and reinstantiates the `BASELINE_AIDERIGNORE` template to prevent indexing of `.aider_factory/lanceDB/` and other heavy artifacts. |
| **Helper Map Missing Warning** | `aider-helper` logs `⚠️ [aider-helper] Warning: --repo-map requested, but '.aider_factory/static_repo_map.md' not found.` | Generate the static map prior to helper invocation by running `aider-factory --repo-map`. |
