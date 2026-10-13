# Dual Static Repository Mapping & Context Management

## 1. Executive Overview & Foundational Invariants

The `aider-factory` repository mapping and context engine eliminates AST context contamination and prompt prefix churn by pre-computing dual, token-budgeted static Abstract Syntax Tree (AST) maps. Traditional AI coding agents dynamically recalculate repository maps across conversation turns. This practice invalidates KV-cache prefixes on inference engines (llama.cpp, vLLM, LiteLLM, Gemini, Anthropic), intermixes test fixtures with production code, and rapidly inflates prompt token overhead.

The AI Factory resolves this by decoupling the codebase into two strictly disjoint domains: Production Source ($D_{\text{src}}$) and Test Harnesses ($D_{\text{test}}$).

### Foundational Invariants
- **Domain Orthogonality:** Production source code ($D_{\text{src}}$) and test code ($D_{\text{test}}$) must never share an AST map. Source maps exclude test files; test maps exclude application code.
- **KV-Cache Prefix Immutability:** Runtime tasks must disable dynamic AST generation (`map_tokens: 0`, `map_refresh: manual`) and ingest pre-generated static maps (`static_repo_map.md`) via `--read` context. This freezes the prompt prefix, yielding up to $100\%$ KV-cache retention on local and cloud inference servers.
- **Ephemeral Ignore Isolation:** Permanent workspace ignore files (`.aiderignore`) remain untouched. The mapping engine synthesizes temporary ignore files (`.aiderignore_source`, `.aiderignore_tests`) and unlinks them in a strict `finally` block, ensuring zero blast radius.
- **Zero-Drop Discovery Fallback:** File enumeration prioritizes index scanning (`git ls-files`) but seamlessly falls back to directory traversal (`os.walk`) with standardized exclusionary boundaries if Git is absent.
- **Documentation Non-Classification (`DOC_EXTS`):** Non-code documentation assets (`.md`, `.txt`, `.rst`, `.yaml`, `.json`, `.toml`) are explicitly exempted from test classification, preventing documentation from being misrouted to test domains.
- **Strict Role Boundaries:** Context files loaded via `--read` are immutable reference context. Editors and builders must never output modifications or search/replace blocks targeting read-only context maps.

---

## 2. System Topology & Lifecycle Flowcharts

The repository mapping lifecycle dynamically discovers workspace files, classifies them via a multi-tier regex cascade, and synthesizes targeted AST maps using Aider's core Tree-Sitter tag engine.

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        DUAL STATIC REPO MAP GENERATION PIPELINE                        │
├──────────────────────────┬────────────────────────────┬────────────────────────────────┤
│ 1. Workspace Discovery   │ 2. Classification Engine   │ 3. AST Synthesis & Lifecycle   │
├──────────────────────────┼────────────────────────────┼────────────────────────────────┤
│                          │                            │ ┌─► Ephemeral Ignore File      │
│ ┌─► git ls-files         │ ┌─► is_test_path()         │ │   (.aiderignore_source)      │
│ │   (Indexed Fast-Path)  │ │   ├─► TEST_DIR_NAMES     │ │   └─► aider --show-repo-map  │
│ ├────────────────────────┤ │   ├─► DOC_EXTS guard     │ │       └─► static_repo_map.md │
│ │                        │ │   ├─► EXACT_HARNESS      │ ├──────────────────────────────┤
│ └─► os.walk fallback     │ │   ├─► TEST_DELIMITED_RE  │ ┌─► Ephemeral Ignore File      │
│     (Pruned Fallback)    │ │   └─► TEST_CAMEL_RE      │ │   (.aiderignore_tests)       │
│                          │ └─► Partition into         │ │   └─► aider --show-repo-map  │
│                          │     D_src & D_test         │ │       └─► static_repo_map_   │
│                          │                            │ │           tests.md           │
│                          │                            │ └─► finally: os.remove()       │
└──────────────────────────┴────────────────────────────┴────────────────────────────────┘
```

### Complete Runtime Context Ingestion Architecture

```text
                                 Pipeline YAML (.env.yml)
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
            Job 1 / Job 2 Passes                          Job 3 / Job 4 Passes
           (Production Code / Audit)                    (Test Suite Verification)
                     │                                             │
      ┌──────────────┴──────────────┐               ┌──────────────┴──────────────┐
      ▼                             ▼               ▼                             ▼
Editable Targets              Read-Only Context   Editable Tests / Target       Read-Only Context
(target_files,                (context_files_job) (specific_test_file,          (context_files_test)
 extra_editable_files)              │              extra_editable_files)              │
                                    │                                                 │
                                    ├─► static_repo_map.md                            ├─► static_repo_map_tests.md
                                    ├─► CONVENTIONS.md                                ├─► CONVENTIONS.md
                                    └─► Strategy Plans                                └─► Test Plans
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### 3.1 Mathematical Domain Partitioning
Let $F = \{f_1, f_2, \dots, f_n\}$ represent the universe of tracked workspace files. We partition $F$ into disjoint sets using the deterministic predicate $\chi_{\text{test}}(f) \in \{0, 1\}$:

$$\chi_{\text{test}}(f) = \begin{cases} 1 & \text{if } \text{is\_test\_path}(f) = \text{True} \\ 0 & \text{if } \text{is\_test\_path}(f) = \text{False} \end{cases}$$

The partitioned domains are defined as:

$$D_{\text{test}} = \{ f \in F \mid \chi_{\text{test}}(f) = 1 \}$$

$$D_{\text{src}} = \{ f \in F \mid \chi_{\text{test}}(f) = 0 \} = F \setminus D_{\text{test}}$$

Fundamental set invariants enforce:
$$D_{\text{src}} \cap D_{\text{test}} = \emptyset \quad \text{and} \quad D_{\text{src}} \cup D_{\text{test}} = F$$

#### KV-Cache Retention Ratio Formulation
Dynamic repomaps inject newly computed AST tag trees into the early prompt prefix on every turn. In an inference session with $T_{\text{prefix}}$ static prefix tokens and $T_{\text{dynamic}}$ fluctuating AST tokens, any perturbation in the AST tree invalidates the entire KV cache from that offset forward:

$$R_{\text{cache}} = \frac{T_{\text{cached\_prefix}}}{T_{\text{total\_prompt}}}$$

Under dynamic mapping, $T_{\text{cached\_prefix}} \approx 0$ on turns following file modifications or commits, forcing the inference engine to re-compute attention keys and values across the entire context window.

Under static mapping (`map_tokens: 0`, `map_refresh: manual`, with static maps passed via `--read`):
$$T_{\text{cached\_prefix}} = T_{\text{system}} + T_{\text{static\_map}} + T_{\text{conventions}} + T_{\text{read\_files}}$$

$$R_{\text{cache}} \to 1.0 \quad \text{for all multi-turn debate and iterative healing passes.}$$

### 3.2 Multi-Tier Test Path Classifier (`is_test_path`)
Implemented in `src/aider_factory/python/env_utils.py`, the classification waterfall executes five sequential checks across POSIX and Windows path structures:

```python
def is_test_path(rel_path: str) -> bool:
    """Classify repository paths to ensure structural isolation between source code and test files."""
    clean = (rel_path or "").replace("\\", "/").strip().lstrip("./")
    if not clean:
        return False
    if os.path.isabs(clean):
        try:
            clean = os.path.relpath(clean, os.getcwd()).replace("\\", "/")
        except ValueError:
            pass
    parts = clean.split("/")
    
    # 1. Directory Component Check
    if any(p.lower() in TEST_DIR_NAMES for p in parts[:-1]):
        return True
        
    filename = parts[-1]
    _, ext = os.path.splitext(filename)
    
    # 2. Documentation Extension Exemption Guard
    if ext.lower() in DOC_EXTS:
        return False
        
    # 3. Exact Test Harness Filenames & Prefixes
    if filename.lower() in EXACT_TEST_HARNESS_FILES or filename.startswith("setupTests."):
        return True
        
    # 4. Delimited Filename Regex Pattern Check
    if TEST_DELIMITED_RE.search(clean):
        return True
        
    # 5. CamelCase Class Filename Pattern Check
    if TEST_CAMEL_RE.search(clean):
        return True
        
    return False
```

#### Rule Definitions & Pattern Criteria

| Tier | Component | Pattern / Set Definition | Concrete Matched Examples |
| :--- | :--- | :--- | :--- |
| **Tier 1: Directory** | `TEST_DIR_NAMES` | `{"test", "tests", "testing", "testthat", "__tests__", "spec", "specs", "e2e", "end-to-end", "fixtures", "testdata", "test_fixtures", "benchmarks", "benches"}` | `tests/core/test_auth.py`<br>`src/__tests__/app.test.tsx`<br>`tests/testthat/test-algo.R`<br>`fixtures/mock_payload.json` |
| **Tier 2: Exemption Guard** | `DOC_EXTS` | `{".md", ".markdown", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml"}` | `docs/testing.md`<br>`spec/api_schema.json`<br>`tests_guide.txt`<br>`test_config.yaml` |
| **Tier 3: Exact Harness** | `EXACT_TEST_HARNESS_FILES` | `{"conftest.py", "tests.py", "tests.rs", "test_helper.rb"}` plus `setupTests.*` | `conftest.py`<br>`src/tests.rs`<br>`setupTests.ts`<br>`test_helper.rb` |
| **Tier 4: Delimited Filename** | `TEST_DELIMITED_RE` | `r"(^|/)((tests?\|specs?\|unit_?tests?)[_\-\.][^/]+|.+[_\-\.](tests?\|specs?\|unit_?tests?)\.[^/]+)$"` (case-insensitive) | `test_calculator.py`<br>`calculator_test.go`<br>`auth.spec.js`<br>`model_unit_test.cpp` |
| **Tier 5: CamelCase Class** | `TEST_CAMEL_RE` | `r"(^|/)[a-zA-Z0-9_]*(Test\|Tests\|TestCase\|Spec)\.[a-zA-Z0-9]+$"` | `UserAccountTest.java`<br>`OrderTestCase.py`<br>`PaymentGatewaySpec.scala`<br>`ApiTests.cs` |

### 3.3 Context Topology & 5-Field File Hierarchy
In `run_workflow.py`, phase execution and strategy plan ingestion decompose workspace files into five strictly partitioned functional roles:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          5-FIELD CONTEXT FILE HIERARCHY                                │
├──────────────────────────┬────────────────────────────┬────────────────────────────────┤
│ Field Category           │ Mutability                 │ Consuming Phases & Tasks       │
├──────────────────────────┼────────────────────────────┼────────────────────────────────┤
│ target_files             │ Read-Write (Primary)       │ Job 1 (Implementation), Job 2  │
│ extra_editable_files     │ Read-Write (Secondary)     │ Job 1, Job 2, Job 3, Apply     │
│ test_files               │ Read-Write (Tests Only)    │ Job 3 (Author Tests), Verify   │
│ context_files_job        │ Immutable (--read)         │ Job 1, Job 2, Deliberations    │
│ context_files_test       │ Immutable (--read)         │ Job 3, Job 4 (Iterate Verify)  │
└──────────────────────────┴────────────────────────────┴────────────────────────────────┘
```

#### Plan Parsing & Automatic Test Diversion (`_extract_files_from_plan`)
During strategy plan ingestion, `run_workflow.py` parses either a fenced YAML block under `## Scope Analysis` or structured Markdown bullet sections:

```python
# Automatic Test Diversion in run_workflow.py
rel_p = _canon_rel(raw_path)
dest_cat = "test_files" if (category == "target_files" and is_test_path(rel_p)) else category
if dest_cat == "test_files" or os.path.isfile(abs_p):
    if rel_p not in verified[dest_cat]:
        verified[dest_cat].append(rel_p)
```

If an author accidentally lists `tests/test_auth.py` under `target_files` in their strategy plan, the classifier intercepts it, preventing test files from becoming editable targets during application logic implementation (Job 1).

### 3.4 Sequential & Cross-Phase Context Accumulation
- **Sequential Accumulation (`sticky_context: true`)**: When multiple target files are processed sequentially within a single phase, successfully completed files are appended as read-only context for subsequent files:
  $$\text{Context}_{k} = \text{Context}_{\text{initial}} \cup \bigcup_{j=1}^{k-1} \{ \text{target}_j \}$$
  This prevents target $k$ from accidentally breaking APIs established by target $k-1$.
- **Cross-Phase Propagation (`sticky_phases`)**:
  - `editable: true`: Automatically propagates discovered target and extra editable files from prior strategy plans into subsequent phases if targets are omitted.
  - `readonly: true`: Inherits discovered `context_files_job` and `context_files_test` into downstream phases.

---

## 4. Exhaustive CLI & Parameter Reference

The dual static repository mapping engine is executed via `aider-factory` CLI flags, with support for targeted helper context injection via `aider-helper`.

| Command | Target Output File | Exit Codes | Operational Invariants & Subprocess Execution |
| :--- | :--- | :--- | :--- |
| `aider-factory --repo-map` | `.aider_factory/static_repo_map.md` | `0`: Success<br>`1`: Subprocess error | Synthesizes `.aiderignore_source` by filtering workspace files with `is_test_path() == True`. Executes `aider --map-tokens 4096 --show-repo-map` and unlinks `.aiderignore_source` in a `finally` block. |
| `aider-factory --repo-map-tests` | `.aider_factory/static_repo_map_tests.md` | `0`: Success<br>`1`: Subprocess error | Synthesizes `.aiderignore_tests` by filtering workspace files with `is_test_path() == False`. Executes `aider --map-tokens 4096 --show-repo-map` and unlinks `.aiderignore_tests` in a `finally` block. |
| `aider-factory --repo-map-all` | Both maps sequentially | `0`: Success<br>`1`: Subprocess error | Runs source map extraction followed immediately by test map extraction. Ensures both artifacts exist on disk. |
| `aider-factory --repo-map --map-tokens <N>` | `.aider_factory/static_repo_map.md` | `0`: Success<br>`1`: Invalid token int | Overrides the default 4096 token limit with `<N>` tokens, expanding or compressing AST tree depth. |
| `aider-helper query --repo-map -t "<prompt>"` | Console / Session History | `0`: Success<br>`1`: File missing | Reads `.aider_factory/static_repo_map.md` and binds it into the `<repository_map>` block of the helper query prompt. |

### Subprocess Invocation Invariant
When `aider-factory --repo-map` executes, it isolates the subprocess environment:
```bash
aider --no-check-model-accepts-settings \
      --no-show-model-warnings \
      --no-check-update \
      --no-show-release-notes \
      --no-notifications \
      --no-analytics \
      --map-tokens 4096 \
      --show-repo-map > .aider_factory/static_repo_map.md
```

---

## 5. Configuration Schema & YAML Knobs

Runtime repository mapping parameters, token caps, and context preservation are managed via `toggles`, `files`, and `sticky_phases` in pipeline YAML configs (`.env.yml` / `session.yml`):

```yaml
phases:
  - name: "Core Implementation"
    enabled: true

    toggles:
      # Repomap Token Controls
      map_tokens: 0                     # type: int | null, default: null
                                        # Overrides Aider --map-tokens. Setting to 0 disables dynamic AST repomap generation.
      map_refresh: "manual"             # type: str | null, default: "manual"
                                        # Options: auto, manual, always. "manual" prevents in-turn recalculation.
      map_multiplier_no_files: 0.0      # type: float | null, default: 0.0
                                        # Token multiplier when no files are explicitly loaded.
      max_chat_history_tokens: 100000   # type: int | null, default: 100000
                                        # Caps conversation token accumulation in the active session.
      sticky_context: true              # type: bool, default: false
                                        # Appends prior completed target files into downstream turn context.

    sticky_phases:
      editable: true                    # type: bool, default: false
                                        # Inherits discovered target_files from strategy plans into subsequent phases.
      readonly: true                    # type: bool, default: false
                                        # Inherits context_files into subsequent phases.

    files:
      target_files:
        - "src/core/engine.py"
      extra_editable_files:
        - "src/core/types.py"
      test_files:
        - "tests/test_engine.py"
      context_files_job:
        - ".aider_factory/markdown/static_repo_map.md"
        - "CONVENTIONS.md"
      context_files_test:
        - ".aider_factory/markdown/static_repo_map_tests.md"
        - "CONVENTIONS.md"
```

### Parameter Mapping & KV-Cache Impact

| YAML Knob | Scope | Default | KV-Cache & Runtime Impact |
| :--- | :--- | :--- | :--- |
| `map_tokens` | Phase `toggles` | `null` (Aider default: 1024) | Set to `0` to completely eliminate dynamic AST map recalculation and freeze system prompt prefixes. |
| `map_refresh` | Phase `toggles` | `"manual"` | When set to `"manual"`, Aider never recalculates AST graphs mid-session, avoiding token churn on git commits. |
| `map_multiplier_no_files` | Phase `toggles` | `0.0` | Prevents Aider from dumping a massive fallback repomap when opening tasks with empty file buffers. |
| `max_chat_history_tokens` | Phase `toggles` | `100000` | Limits message history accumulation to prevent context overflow while preserving active debate transcripts. |
| `sticky_context` | Phase `toggles` | `false` | When `true`, completed files in target batches are passed via `--read` to subsequent tasks, preserving API continuity. |
| `sticky_phases.editable` | Phase Root | `false` | When `true`, automatically transfers discovered editable file manifests across sequential DAG phases. |
| `sticky_phases.readonly` | Phase Root | `false` | When `true`, automatically transfers discovered read-only context file manifests across sequential DAG phases. |

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

| Diagnostic / Failure Mode | Root Cause Signature | Automated Recovery & Operational Mitigation |
| :--- | :--- | :--- |
| **Git Binary Missing** | `FileNotFoundError: [Errno 2] No such file or directory: 'git'` | File discovery engine automatically falls back to `os.walk`. To prevent indexing binary blobs or virtual environments, directory traversal rigorously prunes `.git`, `.aider_factory`, `node_modules`, `dist`, `build`, `target`, `.venv`, `venv`, `__pycache__`, `.pytest_cache`, `temp`, `tmp`, `docs`, `doc`, `man`, and `inst`. |
| **Dangling Ephemeral Ignore** | Hard `SIGKILL` or system crash leaves `.aiderignore_source` or `.aiderignore_tests` on disk. | All ignore file generation is wrapped in a `try...finally` block. Subsequent invocations of `aider-factory --repo-map*` explicitly overwrite existing ephemeral files before executing Aider passes. |
| **AST Tree Token Truncation** | Large codebases exceed `--map-tokens 4096`. | Aider's Tree-Sitter tag engine ranks symbols by PageRank centrality and caller references. Low-centrality leaves are dropped first. For massive repositories, increase the token ceiling: `aider-factory --repo-map --map-tokens 8192`. |
| **Fixture Misclassification** | Data files like `tests/fixtures/sample.json` treated as code. | Governed by `DOC_EXTS`: Files with extensions `.json`, `.yaml`, `.yml`, `.md`, `.txt`, `.rst`, and `.toml` are immune to test classification, remaining in reference context. |
| **Missing Helper Static Map** | `⚠️ [aider-helper] Warning: --repo-map requested, but '.aider_factory/static_repo_map.md' not found.` | The helper queries static maps from disk without re-running AST generation. Generate the map prior to querying: `aider-factory --repo-map`. |
| **Test Auto-Diversion Telemetry** | Strategy plan lists `tests/test_api.py` under `target_files:`. | `run_workflow.py` logs `⚠️ [sticky_phases] Rerouting test file to test_files: 'tests/test_api.py'` and moves it to `test_files`, protecting application authoring phases. |
| **Cross-Platform Separator Mismatch** | Windows `\` paths causing regex match failure. | All path inputs are sanitized at entry via `path.replace("\\", "/").strip().lstrip("./")` before executing `is_test_path()`. |
