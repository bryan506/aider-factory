# Environment Variables & Multi-Provider API Key Resolution (`env_utils.py`)

## 1. Executive Overview & Foundational Invariants

The `env_utils.py` module serves as the foundational substrate for environment management, multi-provider credential resolution, endpoint validation, model topology classification, settings persistence, and process lifecycle control across the AI Factory pipeline. It underpins all agent execution layers (`oracle_agent.py`, `validator.py`, `bootstrap.py`, `rag_manager.py`, `apply_agent.py`, `orchestrate.py`, `run_workflow.py`, and `cli.py`), establishing a single source of truth for runtime configurations.

### Architectural Role in the Pipeline DAG
In a multi-phase DAG execution, tasks transition across heterogeneous environments: local model servers (e.g., llama.cpp, LM Studio, Ollama) requiring dummy authentication tokens, authenticated LiteLLM router proxies requiring unified bearer credentials, and third-party cloud providers (Gemini, Anthropic, OpenAI, Groq, DeepSeek) demanding vendor-specific cryptographic keys. `env_utils.py` decouples authentication and endpoint topology from task execution nodes, guaranteeing that every subprocess and in-process API call receives sanitized, validated, and correctly scoped credentials.

### Foundational Invariants
1. **Non-Destructive Environmental Precedence:** The environment loader (`load_env_files`) strictly preserves existing process environment variables (`if k and k not in os.environ:`). Active shell exports and CLI overrides take precedence over `.env.local`, which in turn overrides `.env`.
2. **Strict Dummy Key Segregation:** Cloud API endpoints reject dummy credentials (`sk-dummy`, `dummy`, `none`, `null`), returning `None` to trigger downstream client fallback or clean failure. Conversely, local inference endpoints (`api_base`) automatically fallback to `"sk-dummy"` to fulfill strict upstream SDK schemas (OpenAI SDK, LiteLLM) without leaking production credentials.
3. **Multi-Tier Hierarchical Loading:** Environment files are discovered and loaded across two hierarchical scopes: the root working directory (`cwd`) and the workspace config directory (`<cwd>/.aider_factory`), ensuring localized tool configurations do not collide with global project definitions.
4. **Deterministic Dummy Filtering:** Any credential matching `DUMMY_KEYS` (case-insensitive `sk-dummy`, `dummy`, `none`, `null`, `""`, or prefixed with `sk-dummy`) is treated as entirely unconfigured during cloud model routing.
5. **Local Endpoint Sanitization & Verification:** An endpoint is recognized as valid (`is_valid_endpoint`) only if it is a non-empty string starting with `http://` or `https://`, is not a dummy key, and contains no template placeholders (`<`, `>`, `your-router-host`).
6. **Atomic Settings Persistence:** Mutating model endpoint definitions on disk (`ensure_model_settings`) is guaranteed atomic via temporary file allocation (`tempfile.mkstemp`) followed by atomic filesystem replacement (`os.replace`), eliminating race conditions in parallel task execution.
7. **Cross-Platform Process Tree Reclamation:** Termination of worker and tool processes (`kill_proc_tree`) recursively reclaims all child processes across Windows (`taskkill /F /T /PID`) and POSIX (`os.killpg(pgrp, SIGKILL)`), ensuring orphaned background inference and test processes do not leak system resources.
8. **Structural Test Path Isolation:** Repository paths are deterministically partitioned into test and source files (`is_test_path`) to enforce zero blast radius between implementation code and verification suites.

---

## 2. System Topology & Lifecycle Flowcharts

### 2.1 Environment File Ingestion Hierarchy
```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              load_env_files(cwd) Workflow                              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│   Active Shell Environment (os.environ)                                                │
│   [Highest Precedence - Immutable to file loading]                                     │
│          ▲                                                                             │
│          │ (if key not in os.environ)                                                  │
│   ┌──────┴─────────────────────────────────────────────────────────────────────┐       │
│   │ Check Hierarchy:                                                           │       │
│   │   1. <cwd>/.env.local                  (Workspace overrides)               │       │
│   │   2. <cwd>/.env                        (Workspace defaults)                │       │
│   │   3. <cwd>/.aider_factory/.env.local   (Pipeline-specific overrides)       │       │
│   │   4. <cwd>/.aider_factory/.env         (Pipeline-specific defaults)        │       │
│   └──────┬─────────────────────────────────────────────────────────────────────┘       │
│          ▼                                                                             │
│   Parsing Rules per Line:                                                              │
│     ├── Strip whitespace & comment-only lines (#...)                                   │
│     ├── Strip leading 'export ' keyword                                                │
│     ├── Split on first '=' into key, value                                             │
│     ├── Strip inline comments (' #...')                                                │
│     ├── Strip surrounding quotes ('...', "...")                                        │
│     └── Assign: os.environ[key] = value (non-destructive)                              │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Two-Tier API Key & Endpoint Resolution
```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│               resolve_api_key(model, api_base, explicit_key) Logic Flow                │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│                            [Incoming Resolution Request]                               │
│                                          │                                             │
│                                          ▼                                             │
│                           Is api_base specified & valid?                               │
│                                    /           \                                       │
│                           YES     /             \   NO                                 │
│                                  ▼               ▼                                     │
│                     ┌──────────────────────┐   ┌───────────────────────────────────┐   │
│                     │ Local / Proxy Branch │   │        Direct Cloud Branch        │   │
│                     └──────────┬───────────┘   └─────────────────┬─────────────────┘   │
│                                │                                 │                     │
│    Is explicit_key set & non-dummy?             Is explicit_key set & non-dummy?       │
│         ├── YES ──► Return explicit_key              ├── YES ──► Return explicit_key   │
│         └── NO                                       └── NO                            │
│              │                                            │                            │
│    Scan Proxy Environment Keys:                 Inspect model prefix in                │
│    1. LITELLM_API_KEY                           PROVIDER_ENV_KEYS:                     │
│    2. ORACLE_AGENT_API_KEY                      gemini/google   ──► GEMINI_API_KEY...  │
│    3. OPENAI_API_KEY                            anthropic/claude──► ANTHROPIC_API_KEY..│
│         ├── Found & non-dummy? ──► Return key   openrouter      ──► OPENROUTER_API_KEY │
│         └── None valid                          groq            ──► GROQ_API_KEY       │
│              │                                  deepseek        ──► DEEPSEEK_API_KEY   │
│              ▼                                  mistral         ──► MISTRAL_API_KEY    │
│         Return "sk-dummy"                       openai          ──► OPENAI_API_KEY     │
│         (Satisfies SDK schemas)                      ├── Match found? ──► Return key   │
│                                                      └── No match / key dummy          │
│                                                           │                            │
│                                                 Scan ALL_PROVIDER_KEYS fallback list:  │
│                                                 [GEMINI, GOOGLE, ANTHROPIC, OPENAI,    │
│                                                  OPENROUTER, GROQ, DEEPSEEK, MISTRAL]  │
│                                                      ├── Match found? ──► Return key   │
│                                                      └── Exhausted ──► Return None     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Subprocess Environment Inheritance & Process Tree Cleanup
```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Subprocess Lifecycle & Process Group Isolation                  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│   run_workflow.py / orchestrate.py                                                     │
│     ├── Evaluates is_local_model(model) & is_valid_endpoint(api_base)                  │
│     ├── Generates LITELLM_SESSION_ID (UUIDv4) for KV-cache stickiness                  │
│     ├── Resolves router key: LITELLM_API_KEY -> OPENAI_API_KEY / LM_STUDIO_API_KEY     │
│     └── Spawns Worker Process:                                                         │
│           POSIX:   subprocess.Popen(..., start_new_session=True)  [New PGID]           │
│           Windows: subprocess.Popen(..., creationflags=...)                            │
│                           │                                                            │
│                           ├── Execution Timeout / User Cancellation                    │
│                           ▼                                                            │
│                    kill_proc_tree(p)                                                   │
│                           │                                                            │
│                           ├─ Windows: taskkill /F /T /PID <pid>                        │
│                           └─ POSIX:   pgrp = os.getpgid(p.pid)                         │
│                                       os.killpg(pgrp, SIGKILL)                         │
│                                       Close streams (stdin, stdout, stderr)            │
│                                       p.wait(timeout=5)                                │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### 3.1 Mathematical Formulations

#### 1. Credential Resolution Function $\mathcal{K}$
Let $m \in \mathcal{M}$ be the model identifier string, $b \in \mathcal{U} \cup \{\emptyset\}$ be the base URL endpoint, $k_{\text{exp}} \in \mathcal{S} \cup \{\emptyset\}$ be an explicitly provided API key, $\mathcal{D}$ be the set of recognized dummy values, $\mathcal{E}$ be the environment mapping, $\mathcal{P}(m)$ be the provider-specific environment key mapping, and $\mathcal{A}$ be the ordered tuple of all provider fallback keys:

$$\mathcal{K}(m, b, k_{\text{exp}}) = \begin{cases}
k_{\text{exp}} & \text{if } b \ne \emptyset \land k_{\text{exp}} \notin \mathcal{D} \\
\mathcal{E}(k) & \text{if } b \ne \emptyset \land \exists k \in (\text{LITELLM\_API\_KEY}, \text{ORACLE\_AGENT\_API\_KEY}, \text{OPENAI\_API\_KEY}) : \mathcal{E}(k) \notin \mathcal{D} \\
\text{"sk-dummy"} & \text{if } b \ne \emptyset \\
k_{\text{exp}} & \text{if } b = \emptyset \land k_{\text{exp}} \notin \mathcal{D} \\
\mathcal{E}(k) & \text{if } b = \emptyset \land \exists k \in \mathcal{P}(m) : \mathcal{E}(k) \notin \mathcal{D} \\
\mathcal{E}(k) & \text{if } b = \emptyset \land \exists k \in \mathcal{A} : \mathcal{E}(k) \notin \mathcal{D} \\
\text{null} & \text{otherwise}
\end{cases}$$

Where the dummy set $\mathcal{D}$ is defined as:
$$\mathcal{D} = \{\text{null}, \text{""}, \text{"sk-dummy"}, \text{"dummy"}, \text{"none"}, \text{"null"}\} \cup \{s \in \mathcal{S} \mid \text{lower}(s) \text{ starts with "sk-dummy"}\}$$

#### 2. Test Path Classification Predicate $T(p)$
Let $p$ be a normalized relative filesystem path composed of path components $(c_1, c_2, \dots, c_n)$, where $c_n$ represents the base filename with extension $e = \text{ext}(c_n)$. The path classification predicate $T(p) \in \{0, 1\}$ evaluates:

$$T(p) = \begin{cases}
0 & \text{if } p = \emptyset \lor \text{lower}(e) \in \mathcal{E}_{\text{doc}} \\
1 & \text{if } \exists i \in \{1, \dots, n-1\} : \text{lower}(c_i) \in \mathcal{D}_{\text{test}} \\
1 & \text{if } \text{lower}(c_n) \in \mathcal{F}_{\text{harness}} \lor c_n \text{ starts with "setupTests."} \\
1 & \text{if } \text{RegexMatch}(p, \mathcal{R}_{\text{delim}}) \lor \text{RegexMatch}(p, \mathcal{R}_{\text{camel}}) \\
0 & \text{otherwise}
\end{cases}$$

Where:
* $\mathcal{D}_{\text{test}} = \{\text{"test"}, \text{"tests"}, \text{"testing"}, \text{"testthat"}, \text{"\_\_tests\_\_"}, \text{"spec"}, \text{"specs"}, \text{"e2e"}, \text{"end-to-end"}, \text{"fixtures"}, \text{"testdata"}, \text{"test\_fixtures"}, \text{"benchmarks"}, \text{"benches"}\}$
* $\mathcal{E}_{\text{doc}} = \{\text{".md"}, \text{".markdown"}, \text{".txt"}, \text{".rst"}, \text{".json"}, \text{".yaml"}, \text{".yml"}, \text{".toml"}\}$
* $\mathcal{F}_{\text{harness}} = \{\text{"conftest.py"}, \text{"tests.py"}, \text{"tests.rs"}, \text{"test\_helper.rb"}\}$

#### 3. Local Model Discriminator $L(m)$
The discriminator $L(m) \in \{0, 1\}$ categorizes whether model $m$ requires local endpoint routing or cloud provider resolution:

$$L(m) = \begin{cases}
1 & \text{if } m = \text{null} \lor m = \text{""} \\
0 & \text{if } \exists p \in \mathcal{P}_{\text{cloud}} : \text{lower}(m) \text{ starts with } p \\
0 & \text{if } \exists p \in \mathcal{P}_{\text{bare\_cloud}} : \text{lower}(m) \text{ starts with } p \\
0 & \text{if } \exists p \in \mathcal{P}_{\text{openai\_cloud}} : \text{strip\_prefix}(\text{lower}(m), \text{"openai/"}) \text{ starts with } p \\
1 & \text{otherwise}
\end{cases}$$

#### 4. Normalized Character Error Rate (CER) Metric
For OCR ground-truth validation:
$$\text{CER}(R, H) = \frac{\text{Levenshtein}(R_{\text{norm}}, H_{\text{norm}})}{|R_{\text{norm}}|}$$
where $R_{\text{norm}} = \text{RegexReplace}(R, \text{"[\^{}a-z0-9]"}, \text{""})$ and $H_{\text{norm}} = \text{RegexReplace}(H, \text{"[\^{}a-z0-9]"}, \text{""})$.

#### 5. Reciprocal Rank Fusion (RRF) Formulation
For multi-table vector retrieval fusion:
$$\text{RRF}(d) = \sum_{t \in \mathcal{T}} \frac{1}{60 + r_t(d)}$$
where $r_t(d)$ is the 0-indexed rank of chunk $d$ in table $t$.

#### 6. Claim Entailment Verification Cutoff
For MiniCheck verifier output probability $P(\text{supported} \mid D, C)$:
$$\text{Status}(C) = \begin{cases}
\text{SUPPORTED} & \text{if } P(\text{supported} \mid D, C) \ge \tau_{\text{entail}} \quad (\text{default } \tau_{\text{entail}} = 0.5) \\
\text{UNSUPPORTED} & \text{if } P(\text{supported} \mid D, C) < \tau_{\text{entail}}
\end{cases}$$

---

### 3.2 Internal Data Structures & Sets

```python
# Dummy key tokens treated as unconfigured for cloud resolution
DUMMY_KEYS = frozenset({"sk-dummy", "dummy", "none", "null", ""})

# Directory names recognized as test isolation boundaries
TEST_DIR_NAMES = {
    "test", "tests", "testing", "testthat", "__tests__",
    "spec", "specs", "e2e", "end-to-end", "fixtures",
    "testdata", "test_fixtures", "benchmarks", "benches",
}

# Documentation extensions exempt from test classification
DOC_EXTS = {".md", ".markdown", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml"}

# Exact test harness filenames
EXACT_TEST_HARNESS_FILES = {"conftest.py", "tests.py", "tests.rs", "test_helper.rb"}

# Regex patterns for delimited and CamelCase test naming
TEST_DELIMITED_RE = re.compile(
    r"(^|/)((tests?|specs?|unit_?tests?)[_\-\.][^/]+|.+[_\-\.](tests?|specs?|unit_?tests?)\.[^/]+)$",
    re.IGNORECASE,
)
TEST_CAMEL_RE = re.compile(
    r"(^|/)[a-zA-Z0-9_]*(Test|Tests|TestCase|Spec)\.[a-zA-Z0-9]+$"
)

# Provider key mappings (evaluated in order)
PROVIDER_ENV_KEYS = {
    "gemini":     ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AIDER_GEMINI_API_KEY", "GOOGLE_GEMINI_API_KEY"),
    "google":     ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AIDER_GEMINI_API_KEY", "GOOGLE_GEMINI_API_KEY"),
    "anthropic":  ("ANTHROPIC_API_KEY", "AIDER_ANTHROPIC_API_KEY"),
    "claude":     ("ANTHROPIC_API_KEY", "AIDER_ANTHROPIC_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY", "AIDER_OPENROUTER_API_KEY"),
    "groq":       ("GROQ_API_KEY", "AIDER_GROQ_API_KEY"),
    "deepseek":   ("DEEPSEEK_API_KEY", "AIDER_DEEPSEEK_API_KEY"),
    "mistral":    ("MISTRAL_API_KEY", "AIDER_MISTRAL_API_KEY"),
    "openai":     ("OPENAI_API_KEY", "AIDER_OPENAI_API_KEY"),
}

# Exhaustive fallback list for unrecognized model prefixes
ALL_PROVIDER_KEYS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "AIDER_GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
    "DEEPSEEK_API_KEY",
    "MISTRAL_API_KEY",
)
```

---

### 3.3 Algorithmic Step-by-Step Logic

#### 1. `kill_proc_tree(p)`
* **Input:** A `subprocess.Popen` process instance.
* **Algorithm:**
  1. Guard against null or terminated references.
  2. **Windows Platform:** Invokes `taskkill /F /T /PID <pid>` redirecting stdout/stderr to `DEVNULL`.
  3. **POSIX Platform:** Inspects process group via `os.getpgid(p.pid)`. If `pgrp > 1` and distinct from current process group, sends `signal.SIGKILL` to `os.killpg(pgrp)`. Otherwise, executes direct `p.kill()`. Catches `ProcessLookupError` and falls back to direct `p.kill()`.
  4. Waits up to 5 seconds (`p.wait(timeout=5)`) for process table reap.
  5. Iterates through streams `("stdin", "stdout", "stderr")` and explicitly closes file descriptors.

#### 2. `is_test_path(rel_path)`
* **Input:** A string path relative or absolute.
* **Algorithm:**
  1. Replace backslashes `\` with `/`, strip whitespace and leading `./`.
  2. If path is absolute, compute `os.path.relpath(clean, os.getcwd())`.
  3. Decompose into component segments by `/`.
  4. If any parent directory segment matches `TEST_DIR_NAMES` (case-insensitive), return `True`.
  5. Check file extension; if in `DOC_EXTS`, return `False` (documentation is never a test).
  6. If filename matches `EXACT_TEST_HARNESS_FILES` or starts with `setupTests.`, return `True`.
  7. Check filename against `TEST_DELIMITED_RE` and `TEST_CAMEL_RE`. If matched, return `True`; otherwise `False`.

#### 3. `is_dummy_key(key)`
* **Algorithm:** Return `True` if `key` is `None` or empty. Clean string via `.strip().lower()`. Return `True` if cleaned in `DUMMY_KEYS` or starts with `"sk-dummy"`; otherwise `False`.

#### 4. `is_valid_endpoint(url)`
* **Algorithm:** Return `False` if `url` is `None` or not a string. Strip whitespace. Return `False` if `is_dummy_key(u)` is `True`. Return `False` if `<` in `u`, `>` in `u`, or `"your-router-host"` in `u`. Return `True` if `u` starts with `http://` or `https://`; otherwise `False`.

#### 5. `is_local_model(model_name)`
* **Algorithm:**
  1. If `model_name` is empty or not string, default to `True` (safe local fallback).
  2. Strip and lowercase model identifier.
  3. Check against 12 cloud provider prefixes (`gemini/`, `anthropic/`, `openai/`, etc.). If matched, return `False`.
  4. Check against 4 bare cloud prefixes (`claude-`, `command-`, `deepseek-`, `mistral-`). If matched, return `False`.
  5. Strip leading `openai/` if present. Check against 10 OpenAI proprietary prefixes (`gpt-`, `o1`, `o3`, `chatgpt`, `text-embedding`, etc.). If matched, return `False`.
  6. Return `True` (model represents an unlisted, local, or custom endpoint model).

#### 6. `get_model_settings(model_name, cwd=None)`
* **Algorithm:**
  1. Resolve candidate paths: `AIDER_MODEL_SETTINGS_FILE` (env), `.aider_factory/sessions/<id>/.aider.model.settings.yml`, `.aider_factory/.aider.model.settings.yml`, `.aider.model.settings.yml`.
  2. Read and parse first existing YAML candidate file via `yaml.safe_load`.
  3. Generate model target permutation set: `{raw, bare, raw:tag, bare:tag, openai/raw, openai/bare}`.
  4. Iterate through entries in settings list. If an entry's `name` intersects with the permutation set, return a copy of the dictionary; otherwise return `{}`.

#### 7. `ensure_model_settings(target_path, models_to_configure, base_settings_path=None)`
* **Algorithm:**
  1. Load existing settings into a keyed dictionary `settings_dict` from `base_settings_path` if present.
  2. Load and overlay existing settings from `target_path` if present.
  3. For each configuration in `models_to_configure`:
     * Validate `name` and `is_valid_endpoint(api_base)`.
     * Generate alias variants (bare and `openai/` prefixed).
     * For each variant, update or insert `extra_params: {"api_base": ..., "api_key": ...}`.
  4. Ensure parent directory exists.
  5. Create temporary file via `tempfile.mkstemp(dir=target_dir, suffix=".tmp")`.
  6. Dump updated configuration list via `yaml.safe_dump(..., sort_keys=False)`.
  7. Execute atomic replacement `os.replace(tmp_path, target_path)`.

#### 8. `load_env_files(cwd=None)`
* **Algorithm:**
  1. Inspect base directory `cwd or os.getcwd()` and subfolder `.aider_factory`.
  2. For each directory, search `.env` followed by `.env.local`.
  3. For each existing file, open with UTF-8 encoding and iterate lines:
     * Strip whitespace; ignore empty lines and `#` comments.
     * Strip leading `export ` keyword if present.
     * Split on first `=` into key `k` and value `v`.
     * Strip surrounding quotes (`'`, `"`) and inline comments (` #...`).
     * If `k` is not in `os.environ`, assign `os.environ[k] = v`.

#### 9. `probe_router(base_url, api_key=None, timeout=2)`
* **Algorithm:**
  1. Guard with `is_valid_endpoint(base_url)`.
  2. Construct `GET {base_url}/models` request with 2-second timeout.
  3. Attach `Authorization: Bearer <key>` header if `api_key` is not dummy.
  4. On HTTP 200, extract `data` array.
  5. Format model IDs: prepend `openai/` to any bare identifier lacking a provider prefix.
  6. Return sorted list of model ID strings. On any network or parsing failure, catch exception and return `None`.

#### 10. `resolve_api_key(model="", api_base=None, explicit_key=None)`
* **Algorithm:** Implements the Credential Resolution Function $\mathcal{K}$.
  1. If `api_base` is provided:
     * Return `explicit_key` if non-dummy.
     * Scan `LITELLM_API_KEY`, `ORACLE_AGENT_API_KEY`, `OPENAI_API_KEY`. Return first non-dummy value found.
     * Fallback: return `"sk-dummy"`.
  2. If `api_base` is absent:
     * Return `explicit_key` if non-dummy.
     * Search `PROVIDER_ENV_KEYS` using lowercase `model` substring matching. Return first valid key.
     * Search `ALL_PROVIDER_KEYS` in sequential order. Return first valid key.
     * Fallback: return `None`.

---

## 4. Exhaustive CLI & Parameter Reference

### 4.1 CLI Invocations & Commands Matrix

| Command / Entrypoint | Subsystem | Purpose & Behavior | Exit Codes |
| :--- | :--- | :--- | :--- |
| `aider-helper bootstrap` | Bootstrapper (`bootstrap.py`) | Probes router via `probe_router()`, detects test framework via `_detect_framework()`, scaffolds `.aider_factory/.env_<repo>.yml`. | `0` = Success<br>`1` = Missing API keys |
| `aider-helper "<query>"` | Terminal Helper (`bootstrap.py`) | Resolves active model via `resolve_api_key()`, streams conversational assistant output via LiteLLM. | `0` = Success<br>`1` = Auth/Connection failure |
| `aider-oracle "<question>"` | Knowledge Oracle (`oracle_agent.py`) | Queries LanceDB RAG using `ORACLE_RAG_DB_DIR`, reranks candidates, and returns synthesized answer. | `0` = Success<br>`1` = Retrieval/Model error |
| `aider-oracle --debate` | Deliberation Referee (`oracle_agent.py`) | Launches multi-round Architect $\leftrightarrow$ Oracle debate; self-gates on consensus status (`deliberate.py`). | `0` = Agreed/Handled<br>`1` = Exception/Timeout |
| `aider-validate --file ...` | Evidence Auditor (`validator.py`) | Provable verbatim check against OCR source truth (`_grounded`), cosine region check, or MiniCheck entailment. | `0` = All grounded/No progress<br>`1` = Trips remain |
| `aider-apply <files...>` | Headless Applier (`apply_agent.py`) | Headless Aider edit pass applying chat history spec or markdown plan without restoring chat bloat. | `0` = Applied cleanly<br>`1` = Apply failure |
| `aider-launcher` | Workflow Runner (`factory_launcher.py`) | Cross-platform launcher executing `run_workflow.py` with full OS tee and token cost aggregation. | Propagates workflow exit code |

---

### 4.2 Provider Key Mapping Matrix (`PROVIDER_ENV_KEYS`)

| Provider Prefix | Normalized Key Candidate List (Evaluated in Order) | Typical Model Pattern |
| :--- | :--- | :--- |
| `gemini` / `google` | `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `AIDER_GEMINI_API_KEY`, `GOOGLE_GEMINI_API_KEY` | `gemini/gemini-2.5-flash`, `google/gemini-pro` |
| `anthropic` / `claude`| `ANTHROPIC_API_KEY`, `AIDER_ANTHROPIC_API_KEY` | `anthropic/claude-3-7-sonnet-20250219` |
| `openai` | `OPENAI_API_KEY`, `AIDER_OPENAI_API_KEY` | `openai/gpt-4o`, `openai/o3-mini` |
| `openrouter` | `OPENROUTER_API_KEY`, `AIDER_OPENROUTER_API_KEY` | `openrouter/anthropic/claude-3.5-sonnet` |
| `groq` | `GROQ_API_KEY`, `AIDER_GROQ_API_KEY` | `groq/llama-3.3-70b-versatile` |
| `deepseek` | `DEEPSEEK_API_KEY`, `AIDER_DEEPSEEK_API_KEY` | `deepseek/deepseek-chat` |
| `mistral` | `MISTRAL_API_KEY`, `AIDER_MISTRAL_API_KEY` | `mistral/mistral-large-latest` |

---

### 4.3 Fallback Key Scanning Sequence (`ALL_PROVIDER_KEYS`)
When a model identifier lacks an explicit provider prefix (or fails initial match), `resolve_api_key` sequentially evaluates:
1. `GEMINI_API_KEY`
2. `GOOGLE_API_KEY`
3. `AIDER_GEMINI_API_KEY`
4. `ANTHROPIC_API_KEY`
5. `OPENAI_API_KEY`
6. `OPENROUTER_API_KEY`
7. `GROQ_API_KEY`
8. `DEEPSEEK_API_KEY`
9. `MISTRAL_API_KEY`

---

## 5. Configuration Schema & YAML Knobs

The pipeline configuration (`.env.yml` or `.aider_factory/.env_<repo>.yml`) defines endpoint routing, models, and execution flags:

```yaml
# ==============================================================================
# AI Factory Master Pipeline Configuration Schema
# ==============================================================================

name: "Enterprise Core Pipeline"
working_directory: "/home/user/workspace/repo"

# Global Test Framework Integration
test_runner: "uv run --with pytest pytest {file}"
test_naming_and_path: "tests/test_{stem}.py"
test_command_prefix: ""
loop_aider_test: 3

# ------------------------------------------------------------------------------
# 1. Endpoint Routing (Passed to resolve_api_key & Subprocesses)
# ------------------------------------------------------------------------------
endpoints:
  # Local inference or LiteLLM router URL (resolves to "sk-dummy" or LITELLM_API_KEY)
  architect_api_base: "http://127.0.0.1:4000/v1"
  editor_api: "http://127.0.0.1:4000/v1"
  editor_api_fallback: "http://127.0.0.1:4000/v1"
  weak_model_api_base: "http://127.0.0.1:4000/v1"

  # RAG & Verification Service Endpoints
  rag_agent_api: "http://127.0.0.1:4000/v1"
  grounding_agent_api: "http://127.0.0.1:8090/v1" # Dedicated MiniCheck verifier
  ranking_api_base: "http://127.0.0.1:8080/v1"    # Cross-encoder reranker
  embed_api_base: "http://127.0.0.1:8081/v1"      # Local embedding endpoint
  ocr_api_base: "http://127.0.0.1:8082/v1"        # Vision OCR endpoint

# ------------------------------------------------------------------------------
# 2. Model Assignments
# ------------------------------------------------------------------------------
models:
  architect_agent: "openai/qwen3.5-122b-a10b-90k:latest"
  editor_agent: "openai/qwen3.6-27b-90k:latest"
  editor_agent_test: "openai/qwen3.6-27b-90k:latest"
  editor_agent_test_fallback: "gemini/gemini-2.5-flash"
  weak_model: "openai/qwen2.5-coder-7b-instruct"
  rag_agent: "openai/qwen3.6-27b-90k:latest"
  ranking_agent: "jinaai/jina-reranker-v3.5"
  embed_model: "BAAI/bge-m3"
  embed_backend: "sentence-transformers" # "sentence-transformers" or "openai"

# ------------------------------------------------------------------------------
# 3. Execution Phases DAG
# ------------------------------------------------------------------------------
phases:
  - name: "Phase_0_Architecture_and_Implementation"
    enabled: true

    toggles:
      run_job_one: true
      run_job_two: false
      run_job_three: false
      iterate_test: true
      auto_test: false
      pair_programming: false
      yes_always: true
      auto_commits: true
      auto_lint: true
      map_tokens: 1024
      max_chat_history_tokens: 32768

    files:
      target_files:
        - "src/core/router.py"
      extra_editable_files: []
      test_files:
        - "tests/test_router.py"
      context_files_job:
        - "README.md"
        - "docs/architecture.md"
      context_files_test:
        - "tests/conftest.py"

    rag:
      collection_name: "core_specs"
      retrieval_mode: "top_k" # "top_k" | "full_document" | "no_retrieve"
      top_k: 5
      recall_k: 50
      type_filter: "code"     # "code" | "docs"

    validation:
      enabled: true
      claims_only: false
      validation_tag: "evidence"
      region_threshold: 0.60
      entail_threshold: 0.50
      verify_all_claims: false
      validation_loops: 3

    escalation_debate:
      loops: 3
      rounds: 1
      pass_history: true
      persist: false
      oracle_persona: ".aider_factory/markdown/personas/strict_critic.md"
      architect_persona: ".aider_factory/markdown/personas/pragmatic_coder.md"
```

---

## 6. Operational Edge Cases, Failure Modes & Telemetry

### 6.1 Diagnostic Matrix & Failure Modes

| Error Signature | Root Cause Mechanism | Recovery & Mitigation Procedure |
| :--- | :--- | :--- |
| `401 Unauthorized` / `APIKeyMissingError` | Cloud model (`gemini/...`, `anthropic/...`) called but provider env key is missing or resolved to `sk-dummy`. | Export required key in `.env.local` or shell (`export GEMINI_API_KEY="..."`). Verify `is_dummy_key()` returns `False`. |
| `422 Unprocessable Entity` (Proxy) | Model identifier mismatch or unsupported parameters sent to remote LiteLLM proxy. | Validate model ID in `probe_router(base_url)`. Check `get_model_settings()` to ensure extra parameters match proxy schema. |
| `502 Bad Gateway` / `ConnectionRefusedError` | `api_base` endpoint unreachable or process crashed (e.g. llama-server, LiteLLM). | Check server status (`systemctl --user status litellm`). Verify endpoint starts with `http://` or `https://` via `is_valid_endpoint()`. |
| `TimeoutExpired` (300s limit) | Subprocess execution in `run_task`, `_aider_ask_turn`, or test runner hanging indefinitely. | Process tree is automatically reclaimed via `kill_proc_tree(p)`. Increase `AIDER_STREAM_TIMEOUT` in environment if tasks genuinely require longer runs. |
| Stale Table Dim Mismatch | LanceDB embedding model changed without dropping existing collection table. | Run `aider-oracle --rm-db` or re-index with `vectordb_overwrite: true` to align table vector dimensions with probed model dimension. |
| Anchor Drop Gate Violation | Quote deleted or re-tagged outside valid anchor vocabulary during heal phase. | Restores original anchor count; checks baseline ledger hash to prevent deletion. |

---

### 6.2 Auto-Injected Subprocess Runtime Variables

During DAG phase compilation in `run_workflow.py`, configuration values are exported to subprocess environments. These govern `aider-oracle`, `aider-validate`, and sub-agents:

#### 1. Routing & Agent Models
* `ORACLE_ARCHITECT_MODEL`: Model identifier utilized for Architect turns during CLI debates.
* `ORACLE_ARCHITECT_API_BASE`: Resolved endpoint URL for the Architect in debates.
* `ORACLE_AGENT_MODEL`: Active model utilized for Oracle inference and RAG response synthesis.
* `ORACLE_AGENT_API_BASE`: Resolved endpoint URL for the Oracle agent.
* `ORACLE_AGENT_API_KEY`: Injected API key (`sk-dummy` for local servers, real key for proxy/cloud).
* `AIDER_WEAK_MODEL`: Secondary weak model for auxiliary commit messages and summary generation.
* `WEAK_MODEL_API_BASE` / `AIDER_WEAK_MODEL_API_BASE`: Local endpoint URL for weak model execution.

#### 2. Vector Retrieval & Database Modifiers
* `ORACLE_RAG_DB_DIR`: Absolute path to active LanceDB directory (`.../lanceDB/<collection>/lancedb`).
* `ORACLE_COLLECTION`: Active table name to query (`*` for multi-table fusion, or specific doc stem).
* `ORACLE_TYPE_FILTER`: Restricts RRF multi-table search to specific corpora (`code` or `docs`).
* `ORACLE_TOP_K`: Number of chunks returned after reranking (default: `5` to `20`).
* `ORACLE_RECALL_K`: Initial candidate pool depth retrieved prior to cross-encoder reranking (default: `30` to `150`).
* `ORACLE_RETRIEVE_MODE`: Retrieval strategy: `top_k` (default), `full_document`, or `no_retrieve`.
* `ORACLE_NO_RAG_INGEST`: If `1`, converts documents/web to Markdown but skips LanceDB vector indexing.
* `ORACLE_EMBED_MODEL`: HuggingFace or cloud embedding model identifier (e.g., `BAAI/bge-m3`).
* `ORACLE_EMBED_BACKEND`: Embedding execution backend: `sentence-transformers` or `openai`.
* `ORACLE_EMBED_API_BASE`: Endpoint for local embedding servers.
* `ORACLE_RANKING_MODEL`: Cross-encoder reranker model identifier (e.g., `jinaai/jina-reranker-v3.5`).
* `ORACLE_RANKING_API_BASE`: Endpoint for remote HTTP reranker services.

#### 3. Inference Parameters & Deliberation Toggles
* `ORACLE_REASONING_EFFORT`: Reasoning parameter for supported models (`low`, `medium`, `high`).
* `ORACLE_TEMPERATURE`: Sampling temperature override for Oracle responses.
* `ORACLE_WEB_WORKERS`: Number of concurrent worker threads for web scraping (`--add-web`).
* `ORACLE_DEBATE_MODE`: Active debate domain (`code` or `review`).
* `ORACLE_DEBATE_LOOPS`: Inner turn loop cap per debate round (default: `3`).
* `ORACLE_DEBATE_ROUNDS`: Outer debate round count (default: `1`).
* `ORACLE_DEBATE_PERSIST`: If `1`, persists consensus ledgers and rotates focus across subsequent audit layers.
* `ORACLE_DEBATE_NO_PASS_HISTORY`: If `1`, isolates debate rounds without passing prior turn history.
* `ORACLE_PERSONA_FILE`: Path to markdown persona file injected into Oracle critique prompts.
* `ARCHITECT_PERSONA_FILE`: Path to markdown persona file injected into Architect prompts.

#### 4. Grounding Validation System (Heal & Apply Nodes)
* `ORACLE_REVIEW_FILE`: Absolute path to generated literature review / target document under audit.
* `ORACLE_SOURCE_FILE`: Absolute path to OCR ground-truth Markdown source file.
* `ORACLE_VALIDATION_FILE`: Path to output validation failures / grounding report.
* `ORACLE_LEDGER_FILE`: Path to per-document JSON ledger tracking no-progress guard states.
* `ORACLE_BASELINE_LEDGER`: Path to debate ledger containing `quote_baseline` hashes for the deletion guard.
* `ORACLE_VALIDATION_TAG`: Resting anchor state tag to verify (default: `evidence`).
* `VALIDATION_ATTEMPT`: Outer-loop attempt counter passed to `validator.py`.
* `GROUNDING_AGENT_MODEL`: Model identifier for MiniCheck entailment verification.
* `GROUNDING_AGENT_API_BASE`: Endpoint URL for MiniCheck server (`minicheck_server.py`).
* `GROUNDING_AGENT_API_KEY`: API key for MiniCheck server.
* `GROUNDING_ENTAIL_THRESHOLD`: Confidence cutoff for claim entailment (default: `0.5`).
* `GROUNDING_VERIFY_ALL`: If `1`, verifies claims across all quotes; if `0`, checks failing quotes only.
* `ORACLE_CLAIMS_ONLY`: If `1`, runs claim-level extraction and verification without requiring anchor tags.

#### 5. Session Stickiness & KV-Cache Header
* `LITELLM_SESSION_ID`: Unique UUID (`uuid.uuid4()`) generated once per pipeline run. Exported to the environment and attached via `custom_headers: {"x-litellm-session-id": ...}` on every LiteLLM completion and embedding request to maintain KV-cache stickiness across remote inference workers.
* `LITELLM_API_KEY`: Master authentication Bearer token for LiteLLM proxies. Automatically mapped into `OPENAI_API_KEY`, `LM_STUDIO_API_KEY`, and subprocesses.
* `LITELLM_BASE_URL`: Root base URL of the LiteLLM router proxy (e.g., `http://10.0.0.5:4000/v1`).
