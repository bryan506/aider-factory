# Session Management, Cluster Architecture & Cold-Storage Infrastructure

The `aider-factory` framework provides an enterprise-grade session lifecycle, multi-node inference cluster orchestration, and cold-storage archiving subsystem designed for deterministic task resumption, KV-cache prefix optimization, and multi-workspace isolation.

---

## 1. Executive Overview & Foundational Invariants

The session management and cluster infrastructure forms the persistence, routing, and resource control backbone of the AI Factory pipeline. It guarantees strict workspace isolation, non-destructive safety backups, prefix-cached model interactions, and deterministic Directed Acyclic Graph (DAG) node state management across local GPU workstations and remote inference clusters.

```
       +-------------------------------------------------------------------------+
       |                           AI Factory Pipeline                           |
       |  (orchestrate.py / run_workflow.py / factory_launcher.py / cli.py)      |
       +------------------------------------+------------------------------------+
                                            |
                    +-----------------------+-----------------------+
                    |                                               |
       +------------v------------+                     +------------v------------+
       |   Session Persistence   |                     |     Cluster Routing     |
       |   & Vault Isolation     |                     |     & Load Balancing    |
       |  (.aider_factory/sess)  |                     |    (LiteLLM / Routers)  |
       +------------+------------+                     +------------+------------+
                    |                                               |
                    | (Backup / Purge)                              | (Inference Calls)
       +------------v------------+                     +------------v------------+
       |   Cold-Storage Archive  |                     | Multi-Backend Workers   |
       |   ($XDG_CACHE_HOME)     |                     | (vLLM / llama / Cloud)  |
       +-------------------------+                     +-------------------------+
```

### Foundational Invariants

1. **Local Workspace Sandboxing**: Every pipeline session is strictly self-contained within `.aider_factory/sessions/<slug>/`, deterministically anchored to the workspace repository root (`working_directory` or `os.getcwd()`). No pipeline execution ever writes un-isolated session state into the root project directory.
2. **DAG Node State Isolation (Vaulting)**: Sequential and parallel tasks within a phase isolate conversational context by vaulting state files (`.aider.chat.history.md`, `.aider.input.history`, `.aider.llm.history`, `.oracle_session.json`, `.oracle_debate_session.json`, `.debate_aider_history.md`, `.oracle_chat.history.md`, `.pair_capture.log`) into `chat_history/` subdirectories keyed by `history_stem` (e.g., `job1_main`), eliminating cross-task context bleed unless explicitly unified via `shared_history: true`.
3. **Safety-by-Default Cold Storage**: Destructive session clearing operations (`--clear-session`, `--clear-all`, `--clear-side-session`, `--clear-side-sessions`) are non-destructive by default. Before deleting active session artifacts, the workspace's `.aider_factory/` state is atomically mirrored to cold storage (`$XDG_CACHE_HOME/aider_factory_cache/<project>/.aider_factory/` or `~/.cache/aider_factory_cache/<project>/.aider_factory/`). Deletion without backup occurs strictly when the user passes the explicit `--forever` flag.
4. **Deterministic Configuration Pairing**: When a pipeline run initializes with an explicit YAML configuration (`aider-factory <config.yml> <session_name>` or `aider-factory -s <session_name> <config.yml>`), the configuration is frozen into `.aider_factory/sessions/<slug>/session.yml`. Subsequent invocations resuming `<slug>` automatically bind to this paired configuration, insulating the running session from global config mutations.
5. **Append-Only KV-Cache Prefix Preservation**: Multi-turn sessions and side-agents (`aider-oracle`, `aider-helper`) maintain immutable prompt prefixes. Context additions are injected as append-only deltas to guarantee maximal hardware KV-cache prefix hits on vLLM, llama-server, and cloud inference endpoints.
6. **Cluster Router Multiplexing & Failover**: Remote LLM calls route through OpenAI-compatible LiteLLM proxy clusters with automated health probing (`probe_router`), automatic model ID normalization (`openai/` prefix injection), and session stickiness headers (`x-litellm-session-id: <UUID>`). Local weak models and embeddings remain strictly isolated from cluster endpoints unless explicitly compatible.
7. **Global Workspace Registry**: Projects are auto-registered in a global `registry.json` (`~/.config/aider_factory/registry.json`), permitting cross-workspace session inspection, cache audits, and global cleanup operations from any shell location.

---

## 2. System Topology & Lifecycle Flowcharts

### 2.1 Workspace Session Topology

The on-disk filesystem layout encapsulates the active workspace state, session-isolated contexts, historical archives, and the global registry:

```text
<workspace_root>/
├── .aider_factory/
│   ├── .env.yml                        # Fallback pipeline configuration
│   ├── .aider.conf.yml                 # Local Aider global flags override
│   ├── .aider.model.settings.yml       # Base model configurations & reasoning parameters
│   ├── .helper_session.json            # Configuration assistant KV history
│   ├── .helper_terminal_session.json   # Terminal assistant KV history
│   ├── static_repo_map.md              # Token-budgeted source AST map (source files)
│   ├── static_repo_map_tests.md        # Token-budgeted test AST map (test harnesses)
│   ├── temp/                           # Ephemeral workspace storage
│   │   ├── active_spec.md              # Extracted spec for headless apply
│   │   ├── .aider_repair_prompt_*.txt  # Iterative test repair prompts
│   │   └── .apply.chat.history_*.md    # Isolated apply execution logs
│   ├── logs/
│   │   ├── <config>_run_<time>.log     # Master multiplexed OSTee run execution log
│   │   ├── chat_history/               # Timestamped Aider chat session archives
│   │   │   └── <stamp>_<task_id>.md
│   │   ├── llm_history/                # Timestamped raw LiteLLM prompt/response archives
│   │   │   └── <stamp>_<task_id>.llm.log
│   │   ├── oracle_history/             # Timestamped Oracle RAG retrieval transcripts
│   │   │   └── <stamp>_<task_id>.md
│   │   ├── validations/                # Pre-debate grounding and claim audit logs
│   │   └── debates/                    # Multi-turn deliberation transcripts & ledgers
│   └── sessions/
│       ├── default/                    # Default unnamed session sandbox
│       │   ├── session.yml             # Frozen paired configuration
│       │   ├── .aider.chat.history.md  # Active Aider conversational history
│       │   ├── .aider.input.history    # Active readline prompt history
│       │   ├── .aider.llm.history      # Active raw token prompt/response history
│       │   ├── .oracle_session.json    # Active Oracle session context
│       │   ├── .oracle_session.json.costs.json # Cumulative Oracle cost sidecar
│       │   ├── .oracle_debate_session.json     # Active deliberation Oracle memory
│       │   ├── .debate_aider_history.md        # Active deliberation Architect memory
│       │   ├── .pair_capture.log       # Interactive pair-programming terminal capture
│       │   └── chat_history/           # Vaulted DAG node states (history_stem)
│       │       ├── .aider.chat.history_job1_main.md
│       │       ├── .aider.input.history_job1_main
│       │       ├── .oracle_session_job1_main.json
│       │       └── .oracle_debate_session_job1_main.json
│       └── refactor_auth/              # Named session sandbox
│           ├── session.yml
│           └── ...
│
~/.config/aider_factory/
└── registry.json                       # Global workspace directory registry
│
$XDG_CACHE_HOME/aider_factory_cache/ (or ~/.cache/aider_factory_cache/)
└── <project_name>/
    └── .aider_factory/                 # Safety cold-storage backup mirror
```

---

### 2.2 Session Lifecycle & KV-Cache Restoration Flowchart

The lifecycle state machine governs configuration pairing, directory instantiation, conversational history restoration, and inference warmup:

```text
                          +-------------------------------------------------------+
                          |                  CLI Invocations                      |
                          |  aider-factory [session_name] [config_file.yml]       |
                          +---------------------------+---------------------------+
                                                      |
                                                      v
                                        +---------------------------+
                                        |  Sanitize Session Slug    |
                                        |  re.sub(r'[^a-zA-Z0-9_.-]')
                                        +-------------+-------------+
                                                      |
                                                      v
                                     Does session directory exist?
                                     +--------------+--------------+
                                    YES                            NO
                                     |                             |
                       +-------------v-------------+ +-------------v-------------+
                       | Read paired session.yml   | | Create session directory  |
                       | If config passed, freeze  | | Copy specified/default    |
                       | new config into session   | | config to session.yml     |
                       +-------------+-------------+ +-------------+-------------+
                                     |                             |
                                     +--------------+--------------+
                                                    |
                                                    v
                               +--------------------------------------------+
                               | Append project root to ~/.config/registry  |
                               +--------------------+-----------------------+
                                                    |
                                                    v
                          +-------------------------------------------------------+
                          |                 Session Initialization                |
                          |  1. Pass --chat-history-file to Aider                 |
                          |  2. Pass --input-history-file to Aider                |
                          |  3. Pass --llm-history-file to Aider                  |
                          |  4. Export ORACLE_SESSION_FILE & ORACLE_DEBATE...     |
                          |  5. Re-scan physical git working tree & repo map      |
                          +-------------------------+-----------------------------+
                                                    |
                                                    v
                          +-------------------------------------------------------+
                          |                   Task DAG Execution                  |
                          |  • If state exists: warm KV-cache hit on local GPU    |
                          |  • Tasks execute in sequence via orchestrate.py       |
                          +-------------------------+-----------------------------+
                                                    |
                                                    v
                          +-------------------------------------------------------+
                          |                    Post-Run Teardown                  |
                          |  • Multiplexed log closed by OSTee                    |
                          |  • aggregate_costs.py computes exact token sum        |
                          |  • Session artifacts remain durable on disk           |
                          +-------------------------------------------------------+
```

---

### 2.3 Task State Vaulting & Lifecycle Flowchart

Within a multi-job phase (e.g., `job_one` $\to$ `job_two` $\to$ `job_three` $\to$ `verify`), `orchestrate.py` isolates context per node using the state vaulting mechanism:

```text
                  +-------------------------------------------------------+
                  |         Task Dispatched (orchestrate.py:run_task)     |
                  +---------------------------+---------------------------+
                                              |
                                              v
                               Is history_stem defined?
                              (shared_history == false)
                               +--------------+--------------+
                              YES                            NO
                               |                             |
                 +-------------v-------------+               |
                 |   _swap_in_state(stem)    |               |
                 | 1. Unlink active files    |               |
                 | 2. Copy vaulted files to  |               |
                 |    active session root    |               |
                 +-------------+-------------+               |
                               |                             |
                               +--------------+--------------+
                                              |
                                              v
                 +-------------------------------------------------------+
                 |                 Execute Task Node                     |
                 |  • Programmatic Oracle Job (oracle_agent.py --auto)   |
                 |  • Evidence Grounding Audit (validator.py)            |
                 |  • Two-Party Deliberation (deliberate.py)             |
                 |  • Code Implementation / Repair (Aider subprocess)    |
                 +----------------------------+--------------------------+
                                              |
                                              v
                 +-------------------------------------------------------+
                 |                 Log Archival Routine                  |
                 |  Copy active chat, llm, and oracle transcripts to     |
                 |  .aider_factory/logs/{chat,llm,oracle}_history/       |
                 +----------------------------+--------------------------+
                                              |
                               Is history_stem defined?
                              (shared_history == false)
                               +--------------+--------------+
                              YES                            NO
                               |                             |
                 +-------------v-------------+               |
                 |   _swap_out_state(stem)   |               |
                 | 1. Copy active state to   |               |
                 |    chat_history/<stem>    |               |
                 | 2. Sync node deletions    |               |
                 +-------------+-------------+               |
                               |                             |
                               +--------------+--------------+
                                              |
                                              v
                  +-------------------------------------------------------+
                  |                 Advance to Next Task                  |
                  +-------------------------------------------------------+
```

---

### 2.4 LiteLLM Cluster & Inference Routing Topology

The AI Factory interfaces with remote and distributed inference clusters through a centralized, load-balanced LiteLLM proxy router architecture:

```text
+---------------------------------------------------------------------------------------------------+
|                                      Local Development Host                                       |
|                                                                                                   |
|  +--------------------+    +--------------------+    +--------------------+    +---------------+  |
|  |   Aider Architect  |    |    Aider Editor    |    |   Knowledge Oracle |    | Grounding Ver |  |
|  |     (Ask Mode)     |    |   (Diff Engine)    |    |   (LanceDB RAG)    |    |  (MiniCheck)  |  |
|  +---------+----------+    +---------+----------+    +---------+----------+    +-------+-------+  |
|            |                         |                         |                       |          |
|            | HTTP / SSE Stream       | HTTP / SSE Stream       | HTTP / SSE Stream     | HTTP     |
|            | (LITELLM_BASE_URL)      | (LITELLM_BASE_URL)      | (LITELLM_BASE_URL)    | (/v1/cc) |
+------------|-------------------------|-------------------------|-----------------------|----------+
             |                         |                         |                       |
             v                         v                         v                       v
+---------------------------------------------------------------------------------------------------+
|                                 LiteLLM Proxy Router Cluster                                      |
|                               (http://cluster-host:4000/v1)                                       |
|                                                                                                   |
|  Features:                                                                                        |
|  • Health & Model Probing: GET /v1/models (probe_router)                                          |
|  • Sticky Session Pinning: Header 'x-litellm-session-id: <UUID>'                                  |
|  • Model ID Normalization: Prepends 'openai/' to bare local IDs                                   |
|  • Dynamic Rate Limit & Cost Tracking: completion_cost calculation                                |
+---------------------------------------------------------------------------------------------------+
             |                         |                         |                       |
   +---------+---------+     +---------+---------+     +---------+---------+   +---------+---------+
   |                   |     |                   |     |                   |   |                   |
   v                   v     v                   v     v                   v   v                   v
+-------------+ +-------------+ +-------------+ +-------------+ +-------------+ +--------------------+
| Worker GPU  | | Worker GPU  | | Worker GPU  | | Cloud LLM   | | Cloud LLM   | | Grounding Node     |
| Node A      | | Node B      | | Node C      | | Endpoint    | | Endpoint    | | (MiniCheck-Flan-T5)|
| (vLLM /     | | (llama.cpp  | | (Ollama /   | | (Google     | | (Anthropic  | | Port 8090          |
| Qwen-27B)   | | DeepSeek)   | | Strix / RDNA| | Gemini API) | | Claude API) | | (FastAPI / PyTorch)|
+-------------+ +-------------+ +-------------+ +-------------+ +-------------+ +--------------------+
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### 3.1 Session Name Sanitization & Slugification

Session names provided via the CLI (e.g., `aider-factory "Refactor / User Auth Engine"`) undergo deterministic string sanitization prior to filesystem operations. Characters outside the POSIX-safe set (`[a-zA-Z0-9_.-]`) are collapsed into underscore characters:

$$S_{\text{sanitized}} = \text{regex\_replace}\left(\left[\text{\textasciicircum a-zA-Z0-9\_}\setminus\text{-}\setminus\text{.}\right] \to \text{"\_"}, S_{\text{raw}}\right)$$

In `orchestrate.py`, `run_workflow.py`, and `cli.py`:
```python
session_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", session_name.strip())
```
If an invocation omits an explicit session identifier, the runner synthesizes a timestamped slug:
```python
session_name = datetime.datetime.now().strftime("session_%Y%m%d_%H%M%S_%f")
```

---

### 3.2 DAG State Vaulting & Prefix Preservation

To prevent conversational pollution between independent tasks while retaining full prefix caching within a task across retry loops, `orchestrate.py` implements the State Vault.

#### Active State File Set
The active state set $\mathcal{F}_{\text{active}}$ comprises nine mutable runtime files located at `.aider_factory/sessions/<slug>/`:
$$\mathcal{F}_{\text{active}} = \left\{
\begin{array}{l}
\text{.aider.chat.history.md}, \text{.aider.input.history}, \text{.aider.llm.history}, \\
\text{.oracle\_session.json}, \text{.oracle\_session.json.costs.json}, \\
\text{.oracle\_debate\_session.json}, \text{.debate\_aider\_history.md}, \\
\text{.oracle\_chat.history.md}, \text{.pair\_capture.log}
\end{array}
\right\}$$

#### Vault Path Transformation
Vaulted files are persisted under `.aider_factory/sessions/<slug>/chat_history/` transformed with the task stem:
$$\text{VaultPath}(F, \text{stem}) = \text{Directory}(F) \parallel \text{"/chat\_history/"} \parallel \text{StemMap}(F, \text{stem})$$

```python
def _get_vault_path(self, active_path: str, stem: str) -> str:
    vault_dir = os.path.join(str(self.session_dir), "chat_history")
    base = os.path.basename(active_path)
    mapping = {
        ".aider.chat.history.md": f".aider.chat.history_{stem}.md",
        ".aider.input.history": f".aider.input.history_{stem}",
        ".aider.llm.history": f".aider.llm.history_{stem}",
        ".oracle_session.json": f".oracle_session_{stem}.json",
        ".oracle_session.json.costs.json": f".oracle_session_{stem}.json.costs.json",
        ".oracle_debate_session.json": f".oracle_debate_session_{stem}.json",
        ".debate_aider_history.md": f".debate_aider_history_{stem}.md",
        ".oracle_chat.history.md": f".oracle_chat.history_{stem}.md",
        ".pair_capture.log": f".pair_capture_{stem}.log",
    }
    return os.path.join(vault_dir, mapping.get(base, f"{base}_{stem}"))
```

#### State Swapping Routines
- **`_swap_in_state(stem)`**:
  1. Iterates over $f \in \mathcal{F}_{\text{active}}$. If $f$ exists in the active session root, it is unlinked via `os.remove(f)`.
  2. Resolves $\text{VaultPath}(f, \text{stem})$. If the vaulted copy exists, it is copied to $f$ via `shutil.copy2`.
- **`_swap_out_state(stem, purge_missing=False)`**:
  1. Ensures `.aider_factory/sessions/<slug>/chat_history/` exists.
  2. Iterates over $f \in \mathcal{F}_{\text{active}}$. If $f$ exists in the active session root, it is copied to $\text{VaultPath}(f, \text{stem})$.
  3. If $f$ does not exist and `purge_missing=True`, any stale file at $\text{VaultPath}(f, \text{stem})$ is removed.

#### Mathematical Prefix Caching Formulation
Preserving exact byte alignment across consecutive task runs enables hardware-accelerated RadixAttention and Prefix Caching on local engines (vLLM, llama-server). The Cache Hit Ratio ($\text{CHR}$) is defined as:

$$\text{CHR} = \frac{L_{\text{prefix}}}{L_{\text{total}}} = \frac{L_{\text{system}} + L_{\text{conventions}} + L_{\text{vault\_history}}}{L_{\text{system}} + L_{\text{conventions}} + L_{\text{vault\_history}} + L_{\text{delta}}}$$

Where:
- $L_{\text{system}}$: Fixed tokens for system and persona instructions.
- $L_{\text{conventions}}$: Fixed tokens for `CONVENTIONS.md`.
- $L_{\text{vault\_history}}$: Preserved tokens loaded from the vaulted history file.
- $L_{\text{delta}}$: Newly introduced query tokens or error trace tokens for the current attempt.

When $L_{\text{delta}} \ll L_{\text{prefix}}$, $\text{CHR} \to 1.0$, reducing TTFT (Time-To-First-Token) from seconds to milliseconds.

---

### 3.3 Interactive Pair-Programming History Management

When `pair_programming: true` is activated, Aider executes as an interactive pseudo-terminal (PTY) wrapper (`script -qfe -c ...` on Linux, `script -q ...` on macOS, piped Popen on Windows). Because the user drives interactive exploration within a single task, `orchestrate.py` does not cross task boundaries, and the automated vault swap does not fire mid-session.

Aider's native `/clear` command purges the in-memory context buffer but intentionally preserves `.aider.chat.history.md` on disk. If the session restarts or drops, `--restore-chat-history` reloads the entire conversation.

#### Same-Session Epoch Reset Procedure
To wipe conversational memory without terminating the interactive shell, execute an epoch clear from an adjacent terminal window:

```bash
# 1. Define active session parameters
SESSION_NAME="${AI_FACTORY_SESSION:-default}"
SESS_DIR=".aider_factory/sessions/${SESSION_NAME}"
VAULT_DIR="${SESS_DIR}/chat_history"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# 2. Archive active chat history to vault
mkdir -p "${VAULT_DIR}"
if [ -f "${SESS_DIR}/.aider.chat.history.md" ]; then
    mv "${SESS_DIR}/.aider.chat.history.md" "${VAULT_DIR}/.aider.chat.history_epoch_${TIMESTAMP}.md"
fi

# 3. Instantiate empty active history file
touch "${SESS_DIR}/.aider.chat.history.md"
```

#### Automation vs. Manual Epoch Decision Matrix

| Scenario | Vault Swap Behavior | Action Required |
| :--- | :--- | :--- |
| **`shared_history: false`, sequential target files (`f1.py` $\to$ `f2.py`)** | Automated via `run_task` boundaries | None |
| **`shared_history: false`, multi-job sequence (`job1` $\to$ `job2`)** | Automated via distinct `history_stem` values | None |
| **`shared_history: true`, distinct named sessions** | Isolated across `.aider_factory/sessions/<slug>/` | None |
| **`pair_programming: true`, mid-session conversation reset** | Not triggered (single continuous task invocation) | **Execute manual epoch clear** |

---

### 3.4 Headless Specification Extraction (`apply_agent.py`)

The `aider-apply` tool bridges conversational planning and headless execution. It parses `.aider.chat.history.md` to extract specifications without requiring user interaction:

1. **Turn Delimitation**: Chat turns are isolated using the regex anchor:
   $$R_{\text{token}} = \text{\textasciicircum}>\setminus\text{s}*\text{Tokens:}\setminus\text{s}*[\setminus\text{d}\setminus.]+[kKMG]?\setminus\text{s}*\text{sent},\setminus\text{s}*[\setminus\text{d}\setminus.]+[kKMG]?\setminus\text{s}*\text{received}.*\$$
2. **Artifact Scrubbing**:
   - Thinking tags (`<thinking-content-...>`, `<think>...</think>`) are stripped.
   - Slash commands (`/add`, `/run`, `/ask`) and banner artifacts (`> Added ...`, `Tokens: ...`) are filtered.
3. **Specification Synthesis**:
   - If `turns == 1`: Formats directive as `# Directive\n<user>\n\n# Specification & Implementation Plan\n<assistant>`.
   - If `turns > 1`: Formats multi-turn context blocks under `## Prior Context Turn N` and `## Active Directive`.
4. **Isolated Execution**:
   - Writes specification to `.aider_factory/temp/active_spec.md`.
   - Strips `read` and `files` keys from `.aider.conf.yml` to prevent ambient context inflation.
   - Executes Aider with `--edit-format editor-diff`, `--message-file active_spec.md`, and `--auto-commits`.
   - Emits a clean `git diff` against `HEAD~1` (falling back to the Git empty tree SHA `4b825dc642cb6eb9a060e54bf8d69288fbee4904` on initial commits).

---

### 3.5 Cluster Inference & LiteLLM Router Integration

The pipeline coordinates inference across multi-model setups through LiteLLM:

```python
# env_utils.py: Probing LiteLLM router capabilities
def probe_router(base_url: str, api_key: Optional[str] = None, timeout: int = 2) -> Optional[list]:
    if not is_valid_endpoint(base_url):
        return None
    try:
        headers = {}
        if api_key and not is_dummy_key(api_key):
            headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", [])
        return sorted(
            m["id"] if "/" in m["id"] else f"openai/{m['id']}"
            for m in data if isinstance(m, dict) and "id" in m
        )
    except Exception:
        return None
```

- **Session Pinning**: Requests sent by `oracle_agent.py`, `validator.py`, and `bootstrap.py` include the header `x-litellm-session-id: <UUID>`, pinning turns to identical physical worker instances across multi-node vLLM clusters.
- **Model Setting Synthesis**: Local model settings are compiled on the fly into `.aider.model.settings.yml` via `ensure_model_settings()`, establishing `api_base`, `api_key`, and custom reasoning effort parameters without overwriting existing workspace defaults.

---

### 3.6 Cost Accounting & Financial Telemetry

Cost tracking operates across in-process calls and headless subprocesses:

1. **LiteLLM Completion Parsing**:
   $$\text{Tokens: } T_{\text{sent}} \text{ sent, } T_{\text{received}} \text{ received. Cost: \$} C_{\text{msg}} \text{ message, \$} C_{\text{sess}} \text{ session.}$$
   $C_{\text{msg}}$ is computed from the LiteLLM model pricing dictionary.
2. **Session Sidecars**: Cumulative sidecar files (`.oracle_session.json.costs.json`) maintain total expenditure:
   $$C_{\text{session}} = C_{\text{prior}} + C_{\text{msg}}$$
3. **Master Run Aggregation**: `factory_launcher.py` tees all stdout/stderr through `OSTee` into `.aider_factory/logs/<config>_run_<time>.log`. Upon pipeline termination, `aggregate_costs.py` executes a single-pass regex scan across the log:
   $$C_{\text{run}} = \sum_{m=1}^{M} C_{\text{msg}}(m), \quad T_{\text{total\_sent}} = \sum_{m=1}^{M} T_{\text{sent}}(m), \quad T_{\text{total\_recv}} = \sum_{m=1}^{M} T_{\text{recv}}(m)$$

---

### 3.7 Cold-Storage Archiving Engine

The backup root is resolved using the XDG Base Directory specification:

$$\text{CacheRoot} = \begin{cases}
\$XDG\_CACHE\_HOME/\text{aider\_factory\_cache}/<repo>/.aider\_factory/ & \text{if } \$XDG\_CACHE\_HOME \text{ is set} \\
\sim/.cache/\text{aider\_factory\_cache}/<repo>/.aider\_factory/ & \text{otherwise}
\end{cases}$$

#### Archiving Workflow (`cli.py:clean_sessions`)
1. **Directory Enumeration**: Resolves target directories matching `.aider_factory/sessions/<slug>/`.
2. **Safety Transfer**: Unless `--forever` is passed, invokes `_backup_workspace_cache(cwd, project_name)`:
   - **Primary (`rsync -a`)**: `rsync -a --no-delete <workspace>/.aider_factory/ <CacheRoot>/`. Timestamps, permissions, and directory structures are preserved.
   - **Fallback (`shutil.copytree`)**: If `rsync` is absent, invokes `shutil.copytree(src, dst, dirs_exist_ok=True)`.
3. **Artifact Removal**: Deletes targeted sessions or sidecars only after transfer confirmation.

---

### 3.8 Static Repository Map Generation

Repository maps provide AST context without dynamic repomap overhead (`--map-tokens 0`). `aider-factory --repo-map` creates static maps using isolated ignore rules:

- **Source Map (`static_repo_map.md`)**: Synthesized using `.aiderignore_source`, ignoring tests and documentation.
- **Test Harness Map (`static_repo_map_tests.md`)**: Synthesized using `.aiderignore_tests`, ignoring non-test source files.
- **Integrity Guarantee**: The primary `.aiderignore` in the workspace root is never modified.

---

## 4. Exhaustive CLI & Parameter Reference

### 4.1 Master Command Matrix

| Command | Subcommands / Target | Flags | Description & Invariants |
| :--- | :--- | :--- | :--- |
| `aider-factory` | `[session_name]` `[config.yml]` | `-s, --session <name>` | Launch pipeline DAG. Freezes paired config, creates session sandbox, restores chat history if session exists. |
| `aider-factory` | `--status` | `-g, --global` | Inspect workspace sessions, sidecar sizes, and cluster endpoint health. Scans globally if `-g` is passed. |
| `aider-factory` | `--list-sessions` | `-g, --global` | Enumerate active session slugs, byte sizes, timestamps, and config pairing status (`paired` vs `no config`). |
| `aider-factory` | `--clear-session <slug>` | `--forever`, `-g` | Delete specific session sandbox. Backs up to cold storage first unless `--forever` is passed. |
| `aider-factory` | `--clear-all` | `--forever`, `-g` | Delete all sessions in workspace or globally. Backs up to cold storage first unless `--forever` is passed. |
| `aider-factory` | `--clear-side-sessions` | `--forever`, `-g` | Delete all side-agent session files. Backs up to cold storage first unless `--forever` is passed. |
| `aider-factory` | `--clear-side-session <alias>` | `--forever`, `-g` | Delete specific side-agent session file by alias (`helper`, `terminal`, `oracle`, `debate`, `<session>`). |
| `aider-factory` | `--repo-map` | `--map-tokens <N>`, `-g` | Generate `static_repo_map.md` (source code AST). Default budget: 4096 tokens. |
| `aider-factory` | `--repo-map-tests` | `--map-tokens <N>`, `-g` | Generate `static_repo_map_tests.md` (test harnesses AST). |
| `aider-factory` | `--repo-map-all` | `--map-tokens <N>`, `-g` | Generate both source and test static repository maps. |
| `aider-launcher` | `[session_name]` `[config.yml]` | `-h, --help` | Cross-platform Python equivalent of `factory` launcher. Multiplexes stdout via `OSTee` and runs `aggregate_costs.py`. |
| `aider-apply` | `<files...>` | `-s, --spec <file>`, `-t, --turns <N>`, `-m, --model <m>`, `--stream`, `--no-diff` | Execute headless edit pass applying spec from chat history or file. Emits clean git diff. |
| `aider-oracle` | `"<query>"` | `--clear`, `--collection <name>`, `--mode <m>`, `--debate [mode]` | Query Knowledge Oracle RAG. `--clear` wipes active oracle & debate history. |
| `aider-helper` | `"<query>"` | `--clear`, `--terminal`, `--file <path>`, `--ask` | Query Configuration Helper or Terminal assistant. `--clear` wipes session. |
| `aider-clean-lancedb`| `<collection>` | `--project-dir <path>` | Remove ephemeral RAG artifacts (images, validation logs, debates) while preserving LanceDB tables. |

---

### 4.2 Parameter & Flag Definitions

| Flag | Applicable Tools | Value Type | Description |
| :--- | :--- | :--- | :--- |
| `--forever` | `aider-factory` (clearing) | Boolean (Switch) | Bypass cold-storage backup. Permanently purge session or sidecar artifacts from disk. |
| `-g, --global` | `aider-factory` | Boolean (Switch) | Operate across all workspaces recorded in `~/.config/aider_factory/registry.json`. |
| `-s, --session` | `aider-factory`, `aider-apply` | String (Identifier) | Explicit session slug. Overrides `AI_FACTORY_SESSION` environment variable. |
| `--spec, -s` | `aider-apply` | String (Path) | Path to explicit markdown specification file. Bypasses chat history extraction. |
| `--turns, -t` | `aider-apply` | Integer | Number of recent conversational turns to extract from chat history (default: `1`). |
| `--stream` | `aider-apply` | Boolean (Switch) | Stream raw inner Aider subprocess stdout/stderr to terminal (default: quiet). |
| `--no-diff` | `aider-apply` | Boolean (Switch) | Suppress printing `git diff HEAD~1 HEAD` upon completion. |
| `--map-tokens` | `aider-factory` (repomap) | Integer | Token budget ceiling for static repository AST generation (default: `4096`). |
| `--clear` | `aider-oracle`, `aider-helper` | Boolean (Switch) | Wipe targeted sidecar session history and KV-cache prefix from disk. |
| `--terminal` | `aider-helper` | Boolean (Switch) | Target `.helper_terminal_session.json` instead of `.helper_session.json`. |

---

### 4.3 Sidecar Target Aliases

When executing `aider-factory --clear-side-session <alias>`, `<alias>` maps to specific files:

| Alias | Target Disk Files | Description |
| :--- | :--- | :--- |
| `helper`, `config` | `.aider_factory/.helper_session.json` | Clears configuration bootstrapping conversational context. |
| `terminal`, `term` | `.aider_factory/.helper_terminal_session.json` | Clears interactive terminal helper context. |
| `oracle` | `.aider_factory/.oracle_session.json`<br>`.aider_factory/.oracle_session.json.costs.json` | Clears default Knowledge Oracle retrieval session and cost sidecar. |
| `debate` | `.aider_factory/.oracle_debate_session.json`<br>`.aider_factory/.debate_aider_history.md`<br>`.aider_factory/sessions/*/chat_history/*debate*` | Clears active deliberation sessions and vaulted debate contexts. |
| `<session_slug>` | `.aider_factory/sessions/<session_slug>/.oracle_session.json`<br>`.aider_factory/sessions/<session_slug>/.oracle_session.json.costs.json`<br>`.aider_factory/sessions/<session_slug>/.oracle_debate_session.json`<br>`.aider_factory/sessions/<session_slug>/.debate_aider_history.md` | Clears all side-agent state files scoped to a specific named session. |

---

### 4.4 Process Exit Codes

| Exit Code | Meaning | Originating Subsystem | Description |
| :--- | :--- | :--- | :--- |
| `0` | Success | Pipeline / Aider / Tools | Pipeline completed, tests passed, apply succeeded, or cleanup verified. |
| `1` | General Failure | Pipeline DAG / Runner | Task assertion failed, missing required configuration, or invalid arguments. |
| `2` | Syntax / Usage Error | CLI Argparse | Missing required positional argument or unrecognized CLI flag. |
| `130` | SIGINT Termination | Operating System | Execution interrupted by user (`Ctrl+C`). Subprocess trees terminated safely. |
| Timeout (`rc != 0`) | Execution Timeout | Subprocess Watchdog | Subprocess exceeded time limit (`AIDER_STREAM_TIMEOUT`, default: 300s/600s). Process tree killed via `kill_proc_tree()`. |

---

## 5. Configuration Schema & YAML Knobs

### 5.1 Remote Cluster & Model Endpoints Schema (`endpoints:`)

The `endpoints:` block in `.env.yml` configures connectivity to local inference instances, remote LiteLLM proxies, and dedicated verification nodes:

```yaml
endpoints:
  # LiteLLM Proxy Router or local llama-server for primary planning
  architect_api_base: "http://cluster-host:4000/v1"

  # Fast instruction-tuned model for code edits
  editor_api: "http://cluster-host:4000/v1"

  # Fallback model for test-iteration escalations
  editor_api_fallback: "http://cluster-host:4000/v1"

  # Low-parameter model (7B-8B) for repo mapping and git commit messages
  weak_model_api_base: "http://127.0.0.1:8000/v1"

  # Dedicated Knowledge Oracle endpoint (LanceDB RAG retrieval & synthesis)
  rag_agent_api: "http://cluster-host:4000/v1"

  # MiniCheck grounding verifier endpoint (Option 1: minicheck_server.py)
  grounding_agent_api: "http://127.0.0.1:8090/v1"

  # Cross-Encoder Reranking endpoint (e.g. TEI / BAAI / Jina reranker)
  ranking_api_base: "http://127.0.0.1:8080/v1"

  # OpenAI-compatible embedding server (bge-m3 / text-embedding-004)
  embed_api_base: "http://127.0.0.1:8081/v1"

  # Vision-capable server for OCR raster ingestion
  ocr_api_base: "http://127.0.0.1:8082/v1"
```

---

### 5.2 Session & Execution Toggles Schema (`toggles:`)

The `toggles:` block within each phase controls session isolation, interaction modes, and Aider flags:

```yaml
phases:
  - name: "Implementation Phase"
    enabled: true
    toggles:
      # History & Isolation Knobs
      shared_history: false           # false: vault chat history per task; true: share across phase
      pair_programming: false         # true: launch interactive PTY session; false: autonomous DAG
      sticky_context: false           # true: carry completed target files into downstream read lists
      
      # Execution Flow
      run_job_one: true               # Implementation pass
      run_job_two: false              # Spec audit pass
      run_job_three: false            # Test harness authoring pass
      iterate_test: true              # Execute automated test/fix loop
      auto_test: false                # true: Aider internal 3-loop; false: external DAG loop
      
      # Safety & Automation
      yes_always: true                # Automatically accept Aider prompts (non-interactive)
      auto_accept_architect: true     # Automatically apply Architect recommendations
      auto_commits: true              # Automatically create git commits upon successful edits
      auto_lint: true                 # Automatically run linter after edits
      lint_cmd: "flake8"              # Custom lint command
      
      # Context Window & Repomap Knobs
      map_tokens: 2048                # AST repository map token budget (0 = disabled)
      map_refresh: "manual"           # 'auto' or 'manual' AST repomap refresh
      map_multiplier_no_files: 0.0    # Map multiplier when no files are explicitly loaded
      max_chat_history_tokens: 100000 # Chat history truncation ceiling
```

---

### 5.3 Global Workspace Registry Schema (`registry.json`)

The global registry records active workspaces to support multi-repo management:

```json
{
  "projects": [
    "/home/developer/repos/core-pipeline",
    "/home/developer/repos/analytics-engine",
    "/home/developer/repos/infra-controller"
  ]
}
```

- **File Location**: `~/.config/aider_factory/registry.json`.
- **Auto-Registration**: Running `aider-factory` appends `os.getcwd()` if missing.
- **Auto-Pruning**: Listing commands (`--list-sessions -g`, `--status -g`) verify paths on disk and prune missing or deleted workspace directories.

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

### 6.1 Diagnostic Status Dashboard (`--status`)

Executing `aider-factory --status` (or `aider-factory --status --global`) prints a diagnostic report:

```text
======================================================================
AI FACTORY PERSISTENCE & CLUSTER STATUS REPORT
======================================================================
[Workspace]: /home/developer/repos/core-pipeline
Active Sessions (Total: 3):
  • default                      [paired]    (Modified: 2026-04-01 10:15:22)
    - Active Chat History:       14.2 KB
    - Vaulted Histories (3):     88.4 KB (chat_history/)
  • refactor_auth                [paired]    (Modified: 2026-04-01 12:45:10)
    - Active Chat History:       45.1 KB
    - Vaulted Histories (0):     0.0 KB
  • session_20260401_091211      [no config] (Modified: 2026-04-01 09:12:11)
    - Active Chat History:       8.3 KB

Side-Agent Session KV Caches:
  • Config Helper (.helper_session.json):           12 turns, 24.1 KB
  • Terminal Helper (.helper_terminal_session.json): 4 turns, 8.2 KB
  • Oracle Active (.oracle_session.json):           6 turns, 18.5 KB
  • Debate Active (.oracle_debate_session.json):    2 turns, 6.4 KB

Cluster Endpoint Health:
  • Architect API (http://cluster:4000/v1):         ONLINE (12 models available)
  • Editor API (http://cluster:4000/v1):            ONLINE
  • Grounding API (http://127.0.0.1:8090/v1):       ONLINE (minicheck-flan-t5-large)
  • Ranking API (http://127.0.0.1:8080/v1):         ONLINE
  • Embed API (http://127.0.0.1:8081/v1):           ONLINE
======================================================================
```

---

### 6.2 Operational Edge Cases & Mitigation Matrix

| Failure Mode / Edge Case | Root Cause | System Mitigation / Recovery Behavior |
| :--- | :--- | :--- |
| **`Argument list too long` (E2BIG)** | Large source files or massive test failure logs passed as CLI arguments to Oracle. | `oracle_agent.py` catches argument overflow by writing large prompts to `.aider_factory/temp/.oracle_prompt_<tmp>.txt` and passing via `--file`. |
| **Subprocess Hanging / Runaway Loop** | Model enters infinite generation loop or compilation hangs. | `kill_proc_tree()` monitors subprocess execution; upon reaching `AIDER_STREAM_TIMEOUT` (300s/600s), sends `SIGKILL` to the entire process group (`os.killpg`) or invokes `taskkill /F /T` on Windows. |
| **Mid-Execution Session Crash** | Power loss, kernel OOM, or unhandled exception mid-task. | Stale un-vaulted files in active root are cleaned up by `_swap_in_state` on the next run, which restores known vaulted states from `chat_history/`. |
| **Remote Cluster Router Offline** | Network failure or LiteLLM proxy crash. | `probe_router()` reports failure with non-zero exit code. Side-agents print clear diagnosis to `stderr` and fall back to local direct endpoints if configured. |
| **Missing `rsync` Binary** | Minimal Docker containers or clean POSIX installs lacking `rsync`. | `_backup_workspace_cache()` catches missing binary exceptions and falls back to Python's built-in `shutil.copytree(..., dirs_exist_ok=True)`. |
| **Undefined `$XDG_CACHE_HOME`** | Shell environment lacks explicit XDG base configuration. | Path resolution defaults safely to `os.path.expanduser("~/.cache/aider_factory_cache/<project>/")`. |
| **Unsafe CLI Session Names** | User provides spaces, slashes, or symbols (`"Test / Run #1"`). | Slug sanitization regex `re.sub(r'[^a-zA-Z0-9_\-\.]', '_', s)` converts input into `Test___Run__1`. |
| **Corrupted Sidecar JSON** | Premature process termination while writing `.costs.json`. | Sidecar loading routines catch `json.JSONDecodeError`, initialize a fresh empty state, and overwrite the corrupted file safely. |
| **Cloud Weak Model Endpoint Leak** | Local endpoint accidentally passed to cloud weak model (e.g. `gemini/`). | `env_utils.is_local_model()` checks provider prefixes; if cloud-based, automatically sets `weak_model_api_base = None`, preventing routing failures. |

---

### 6.3 Recovery & Troubleshooting Runbooks

#### Runbook A: Recovering from a Mid-Execution Crash
If a pipeline run crashes mid-phase (e.g., due to an out-of-memory event):
1. **Inspect Log**: Examine the latest master log at `.aider_factory/logs/<config>_run_<timestamp>.log`.
2. **Review Session State**: Run `aider-factory --status` to identify which task completed and vaulted its history.
3. **Resume Session**: Re-run the launcher pointing to the same session slug:
   ```bash
   aider-factory <session_name>
   ```
   The engine reads the paired `session.yml`, restores the last vaulted chat history, and resumes execution from the next pending DAG task.

#### Runbook B: Resuming and Modifying a Paired Session
To modify parameters for an existing session:
1. **Locate Paired Config**: Open `.aider_factory/sessions/<session_name>/session.yml`.
2. **Adjust Knobs**: Modify models, edit phase toggles (e.g., change `max_aider_loops` or update `target_files`), or update `endpoints:`.
3. **Resume Pipeline**:
   ```bash
   aider-factory <session_name>
   ```
   The pipeline resumes using the updated `session.yml` while preserving conversation context from prior turns.

#### Runbook C: Debugging Remote Cluster Router Health and Auth
If inference calls stall or return authorization errors:
1. **Verify Router Connectivity**:
   ```bash
   curl -s -H "Authorization: Bearer ${LITELLM_API_KEY:-sk-dummy}" \
     "${LITELLM_BASE_URL:-http://localhost:4000/v1}/models" | jq .
   ```
2. **Verify Session Pinning**: Confirm that responses return healthy model IDs and that `x-litellm-session-id` headers are passed through without proxy rejection.
3. **Check Model Settings**: Inspect `.aider_factory/sessions/<session_name>/.aider.model.settings.yml` to verify that synthesized API base URLs and keys match your cluster requirements.
