# Session Management & Cold-Storage Caching

The `aider-factory` framework provides an enterprise-grade session lifecycle and cold-storage archiving subsystem designed for deterministic task resumption and multi-workspace isolation.

---

## 1. Executive Overview & Foundational Invariants

The session management subsystem forms the persistence and resource control backbone of the AI Factory pipeline. It guarantees strict workspace isolation, non-destructive safety backups, and DAG node state isolation across local and remote environments.

### Foundational Invariants
- **Local Workspace Sandboxing**: Every session is strictly self-contained within `.aider_factory/sessions/<slug>/`, pinned to the workspace repository root.
- **DAG Node State Isolation (Vaulting)**: Concurrent or sequential tasks within a phase isolate their conversational context by vaulting state files (`.aider.chat.history.md`, `.oracle_session.json`, etc.) into a `chat_history/` subdirectory using a `history_stem`, preventing cross-task state bleed unless explicitly shared.
- **Safety-by-Default Cold-Storage**: Destructive session operations are non-destructive by default. Before removing active session files, the workspace's `.aider_factory` directory is synchronized to the user's cold-storage cache directory.
- **Append-Only KV-Cache Persistence**: Side-agents (`aider-helper`, `aider-oracle`) maintain persistent sessions mathematically optimized for Prefix Caching on local inference servers, appending heavy documents once to achieve 100% KV cache hits on subsequent turns.
- **Global Workspace Registry**: Projects are auto-registered in a global `registry.json` (`~/.config/aider_factory/registry.json`) to allow managing sessions across multiple repositories from any directory.

---

## 2. System Topology & Lifecycle Flowcharts

### Workspace Session Topology

```text
.aider_factory/
├── .env.yml                        # Global DAG fallback configuration
├── .helper_session.json            # Configuration assistant KV history
├── .helper_terminal_session.json   # Terminal assistant KV history
├── temp/                           # Ephemeral storage (e.g., apply_agent specs)
├── logs/
│   ├── chat_history/               # Timestamped Aider chat archives
│   ├── llm_history/                # Timestamped raw LLM I/O archives
│   ├── oracle_history/             # Timestamped Oracle RAG retrieval archives
│   └── <config>_run_<time>.log     # Master OSTee execution logs
└── sessions/
    ├── default/
    │   ├── session.yml             # Paired YAML pipeline configuration
    │   ├── .aider.chat.history.md  # Active multi-turn conversational history
    │   ├── .aider.input.history    # Active terminal prompt history
    │   ├── .oracle_session.json    # Active Session-scoped Oracle context
    │   ├── .oracle_session.json.costs.json
    │   ├── .oracle_debate_session.json
    │   ├── .debate_aider_history.md
    │   └── chat_history/           # Vaulted DAG node states
    │       ├── .aider.chat.history_job1_<stem>.md
    │       └── .oracle_session_job1_<stem>.json
    ├── feature_auth/
    │   ├── session.yml
    │   └── ...
    └── session_20260401_143022/            # Auto-archived unnamed run
        └── session.yml
```

### Session Lifecycle & KV-Cache Restoration Flowchart

```text
                       ┌────────────────────────────────────────────────────────┐
                       │  User runs: aider-factory refactor_ohlcv               │
                       └───────────────────────────┬────────────────────────────┘
                                                   │
                                     Does session directory exist?
                                     ┌─────────────┴─────────────┐
                                    YES                          NO
                                     │                           │
                   ┌─────────────────┴───────────────┐           │
                   │ Reads session.yml & chat history│           │
                   └─────────────────┬───────────────┘           │
                                     │                           │
  ┌──────────────────────────────────┴───────────────────────────┴─────────────────────────────────┐
  │  1. Restores prior conversation via --restore-chat-history                                    │
  │  2. Restores terminal prompt history via --input-history-file                                 │
  │  3. Restores Oracle & Debate state via ORACLE_SESSION_FILE                                    │
  │  4. Re-scans current git working tree & repo map fresh on disk                               │
  │  5. Hits warm local KV-cache (zero warmup latency) if local LLMs remain in memory             │
  └────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Task State Vaulting & Lifecycle Flowchart

```text
                       ┌────────────────────────────────────────────────────────┐
                       │  Task Execution Triggered (orchestrate.py:run_task)    │
                       └───────────────────────────┬────────────────────────────┘
                                                   │
                                      Is history_stem defined?
                                     (shared_history == false)
                                     ┌─────────────┴─────────────┐
                                    YES                          NO
                                     │                           │
                   ┌─────────────────┴───────────────┐           │
                   │ _swap_in_state(history_stem)    │           │
                   │ Moves vaulted files to active   │           │
                   └─────────────────┬───────────────┘           │
                                     │                           │
  ┌──────────────────────────────────┴───────────────────────────┴─────────────────────────────────┐
  │  1. Execute Task Node (Aider / Oracle / Validate)                                              │
  │  2. Archive Histories to .aider_factory/logs/ (chat_history, llm_history, oracle_history)      │
  └──────────────────────────────────┬───────────────────────────┬─────────────────────────────────┘
                                     │                           │
                   ┌─────────────────┴───────────────┐           │
                   │ _swap_out_state(history_stem)   │           │
                   │ Moves active files to vault     │           │
                   └─────────────────────────────────┘           │
                                                             Complete
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### Session Name Sanitization
Session names passed via CLI (e.g. `aider-factory "Refactor / Auth Service"`) are deterministically sanitized into safe directory slugs before any disk operations:
```python
slug = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', target_session)
```

### DAG State Vaulting & Isolation
To prevent context contamination between sequential or parallel tasks (e.g., `job1` vs `job2`), `orchestrate.py` implements a state vaulting mechanism.
1. **`history_stem` Generation**: Derived from the task type and file stem (e.g., `job1_main`). If `shared_history` is true, the stem is `None`.
2. **`_swap_in_state`**: Before task execution, active state files (`.aider.chat.history.md`, `.oracle_session.json`, etc.) are cleared, and matching files from `chat_history/<filename>_<stem>` are copied into the active root.
3. **`_swap_out_state`**: After execution, active state files are moved back into the `chat_history/` vault, preserving the exact KV-cache prefix for that specific node's future iterations.

### Interactive Pair-Programming History Management

When `pair_programming: true` is active and the user remains within a single job
(e.g., the entire session is `job1`), the automatic vault-swap mechanism does **not**
trigger mid-session — it fires only at task boundaries (`run_task` entry/exit).
Aider's built-in `/clear` command resets the in-memory conversation buffer but does
**not** move or delete the on-disk `.aider.chat.history.md` file. On the next turn,
`--restore-chat-history` reloads the file, making the prior context reappear.

This is by design: the active history file is the session's durable KV-cache prefix
and is intentionally preserved for resumption across process restarts.

#### Manual History Reset (Same-Session Epoch Clear)

To archive the current conversation and start fresh **within the same pair-programming
session**, perform the following from a second terminal:

```bash
# Navigate to your workspace root
cd /path/to/project

# Define the active session (match your AI_FACTORY_SESSION or the slug you passed)
SESS=".aider_factory/sessions/<session_name>"
VAULT="$SESS/chat_history"
TIMESTAMP="$(date +%Y%m%dT%H%M%S)"

# Archive current history to vault with a timestamped stem
mkdir -p "$VAULT"
mv "$SESS/.aider.chat.history.md" "$VAULT/.aider.chat.history_epoch_${TIMESTAMP}.md"

# Create a fresh empty active file so aider has a valid path to write into
touch "$SESS/.aider.chat.history.md"
```

After this, the next aider turn in the pair-programming terminal will start with a
clean conversation buffer (aider reads the empty file, finds no prior turns). The
archived file is retrievable from the vault at any time.

#### Optional Shell Alias

For convenience, add to `~/.bashrc` or `~/.zshrc`:

```bash
af-clear-epoch() {
  local sess_dir=".aider_factory/sessions/${AI_FACTORY_SESSION:-default}"
  local hist="$sess_dir/.aider.chat.history.md"
  local vault="$sess_dir/chat_history"
  local ts="$(date +%Y%m%dT%H%M%S)"
  [[ -f "$hist" ]] && mkdir -p "$vault" && mv "$hist" "$vault/.aider.chat.history_epoch_${ts}.md"
  touch "$hist"
  echo "✓ Archived to $vault/.aider.chat.history_epoch_${ts}.md"
}
```

#### When Automation Already Handles This

| Scenario | Vault Swap Automatic? | Action Required |
| :--- | :--- | :--- |
| `shared_history: false`, multiple target files (job1 → job2) | ✅ Yes — `_swap_out_state` fires per task boundary | None |
| `shared_history: false`, same file across sequential jobs | ✅ Yes — each job gets a distinct `history_stem` | None |
| `shared_history: true`, new session resuming | ✅ Yes — fresh `.aider.chat.history.md` per session dir | None |
| **`pair_programming: true`, same job, user wants fresh context mid-session** | ❌ No — no task boundary occurs | **Manual epoch clear (above)** |

### Headless Application & Chat Parsing (`apply_agent.py`)
The `aider-apply` CLI executes headless Aider passes by extracting specifications directly from chat histories.
1. **Chat Parsing**: `parse_chat_history()` scans `.aider.chat.history.md` using `TOKEN_ANCHOR_RE` (`(?m)^>\s*Tokens:\s*[\d\.]+[kKMG]?\s*sent...`) to isolate conversational turns.
2. **Sanitization**: It strips reasoning blocks (`<thinking-content-...>`, `<think>`) and tool artifacts to extract pure architectural directives.
3. **Headless Execution**: It generates a temporary `active_spec.md` in `.aider_factory/temp/` and invokes Aider with `--yes-always`, `--auto-commits`, and `--message-file`, streaming the resulting git diff.

### Cost Accounting & Token Tracking (`cost_tracker.py`)
Financial telemetry is tracked globally and per-session.
1. **Sidecar Ledgers**: Cumulative costs are persisted in `.costs.json` sidecars (e.g., `.oracle_session.json.costs.json`).
2. **In-Memory Tracking**: `_PROCESS_SESSION_COST` aggregates costs during active execution.
3. **Formatting**: `litellm_cost_line()` emits standardized strings (`Tokens: X sent, Y received. Cost: $A message, $B session`) to `stderr`, which are later intercepted by the `OSTee` multiplexer.

### Cold-Storage Backup Engine Mechanics
The backup root is resolved according to the XDG Base Directory Specification (`$XDG_CACHE_HOME/aider_factory_cache/<project_name>/.aider_factory/`), defaulting to `~/.cache/aider_factory_cache/<project_name>/.aider_factory/` when `$XDG_CACHE_HOME` is unset.

1. **Primary (`rsync -a`)**: If `rsync` is installed, `_backup_workspace_cache` executes atomic, delta transfers preserving permissions, timestamps, and symlinks without the `--delete` flag. This allows the cache to accumulate historical sessions over time.
2. **Fallback (`shutil.copytree`)**: If `rsync` is unavailable, the engine falls back to `shutil.copytree(..., dirs_exist_ok=True)`.

### State Restoration vs. Refresh Logic
When a session resumes, state is strictly bifurcated:

| Component | What is Restored (Preserved) | What is Refreshed (Fresh) |
| :--- | :--- | :--- |
| **Aider Chat Engine** | • Multi-turn discussion context<br>• Terminal prompt history (Up-Arrow)<br>• LLM KV-cache prefix | • Current git working tree<br>• Active file contents on disk<br>• Repo map AST symbols |
| **Paired Configuration** | • Prior conversation state maintained seamlessly | • Edits to models, context files, or phase toggles in `session.yml` take immediate effect on resume |
| **Knowledge Oracle** | • Multi-turn debate context & RAG history | • Vector store queries fresh chunks against latest code |
| **Task Retry Loops** | • Conversation memory is retained across attempts (no clobbering) | • Fresh test failure logs are passed to the next loop attempt |

### Static Repository Map Generation
`aider-factory` generates static, token-budgeted repository maps using ephemeral ignore files (`.aiderignore_source`, `.aiderignore_tests`), ensuring the main `.aiderignore` is never mutated. This provides a stable AST reference for the LLM context window.

---

## 4. Exhaustive CLI & Parameter Reference

### Unified Command Matrix & Flag Permutations
To bypass the cold-storage backup and permanently delete files, pass the `--forever` flag to any clearing command.

| Action | Local Command | Global Command (`--global` / `-g`) | Disk Artifact Path | Behavior & Invariants |
| :--- | :--- | :--- | :--- | :--- |
| **Start / Resume Session** | `aider-factory <name>`<br>`aider-factory -s <name>` | — | `.aider_factory/sessions/<slug>/` | Creates directory if new; restores prior chat and input history if resuming. |
| **Start with Explicit Config** | `aider-factory <cfg.yml> <name>`<br>`aider-factory <name> <cfg.yml>` | — | `.aider_factory/sessions/<name>/session.yml` | Freezes and pairs `<cfg.yml>` to the session directory as `session.yml`. |
| **Resume Paired Config** | `aider-factory <name>` | — | `.aider_factory/sessions/<name>/session.yml` | If no YAML is passed, automatically loads and executes the session's existing `session.yml`. |
| **Auto-Archived Unnamed Run** | `aider-factory`<br>`aider-factory .env.yml` | — | `.aider_factory/sessions/session_YYYYMMDD_HHMMSS/` | Generates a timestamped session folder, clones active `.env.yml` into it, and saves conversation. |
| **Headless Apply** | `aider-apply <files> --session <name>` | — | `.aider_factory/temp/active_spec.md` | Parses chat history to extract specs, then runs headless Aider to apply diffs. |
| **List All Sessions** | `aider-factory --list-sessions` | `aider-factory --list-sessions -g` | Scans `.aider_factory/sessions/` | Prints session slugs, timestamps, sizes (KB), and config pairing status (`paired` vs `no config`). |
| **Inspect System Status** | `aider-factory --status` | `aider-factory --status -g` | Dynamic scan | Reports active sessions, side-agent memory, and remote inference cluster slots. |
| **Clear Specific Session** | `aider-factory --clear-session <name>`<br>`... --forever` | `aider-factory --clear-session <proj>/<name> -g`<br>`... --forever` | Deletes `.aider_factory/sessions/<slug>/` | Backs up to `~/.cache/aider_factory_cache/<project>/` by default before deleting. Use `--forever` to purge permanently without cache. |
| **Clear All Sessions** | `aider-factory --clear-all`<br>`... --forever` | `aider-factory --clear-all -g`<br>`... --forever` | Deletes `.aider_factory/sessions/` | Backs up all sessions to cache by default before deleting. Supports `--global` (`-g`) and `--forever`. |
| **Clear All Sidecars** | `aider-factory --clear-side-sessions`<br>`... --forever` | `aider-factory --clear-side-sessions -g`<br>`... --forever` | Deletes sidecar JSONs | Backs up sidecars to cache by default and deletes files. Supports `--forever`. |
| **Clear Specific Sidecar** | `aider-factory --clear-side-session <target>`<br>`... --forever` | `aider-factory --clear-side-session <target> -g`<br>`... --forever` | Deletes target sidecar files | Backs up target sidecar to cache by default before deleting. Supports `--forever`. |
| **Clear Active Oracle Context** | `aider-oracle --clear` | — | Deletes `.oracle_session.json` & `.oracle_debate_session.json` | Respects `ORACLE_SESSION_FILE` and wipes only the active session's Knowledge Oracle and debate history. |

### Target Aliases for `--clear-side-session`
* `helper` or `config`: Clears `.helper_session.json`.
* `terminal` or `term`: Clears `.helper_terminal_session.json`.
* `oracle`: Clears `.oracle_session.json` and `.oracle_session.json.costs.json`.
* `debate`: Clears active `.oracle_debate_session.json` and `.debate_aider_history.md`, as well as any vaulted orphan artifacts in the `chat_history/` directory.
* `<session_name>`: Clears session-scoped sidecars under `sessions/<session_name>/`.

### Repository Map Commands
* `aider-factory --repo-map`: Generates source-only map (`static_repo_map.md`).
* `aider-factory --repo-map-tests`: Generates test-only map (`static_repo_map_tests.md`).
* `aider-factory --repo-map-all`: Generates both maps.
* `aider-factory --repo-map --map-tokens 8192`: Overrides token budget (default: 4096).
* `aider-factory --repo-map-all --global`: Generates static maps across all registered workspaces globally.

---

## 5. Configuration Schema & YAML Knobs

### Global Workspace Registry Schema (`registry.json`)
Located at `~/.config/aider_factory/registry.json`:

```json
{
  "projects": [
    "/home/user/projects/finance-core",
    "/home/user/projects/trading-engine"
  ]
}
```

* **`projects`** (`list[str]`): Array of absolute workspace directory paths.
* **Auto-Registration Mechanics**: Every time `aider-factory` runs inside a directory, that project root is appended if missing.
* **Auto-Pruning Mechanics**: When enumerating projects, non-existent or moved directories are pruned from disk automatically.

### Paired Configuration Schema (`session.yml`)
When a session is created with an explicit configuration (e.g., `aider-factory custom.yml my_session`), the YAML file is cloned into `.aider_factory/sessions/my_session/session.yml`. Resuming this session automatically reloads this paired file, ensuring pipeline execution remains deterministic and isolated from global workspace changes.

#### Critical State Toggles
* **`toggles.shared_history`** (`bool`): Defaults to `false`. When `true`, disables DAG node state vaulting (`history_stem = None`), forcing all tasks in a phase to share a single `.aider.chat.history.md` file. This risks context contamination but is useful for linear, highly interdependent tasks.

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

### Diagnostic Status Dashboard (`--status`)
Running `aider-factory --status` (or `--status --global`) prints real-time diagnostics:
1. **Main Aider Sessions**: Lists session names, last modified timestamp, chat history size (KB), and config pairing status (`paired` vs `no config`). *Note: For tasks using `shared_history: false`, the reported history size accurately reflects the aggregate size of all vaulted isolated histories inside the `chat_history/` directory, rather than just the active `.aider.chat.history.md` file.*
2. **Side-Agent Sessions & KV Caches**: Reports turn counts, disk sizes, and timestamps for `helper`, `terminal`, `oracle`, and `debate` sessions.
3. **Remote Inference Cluster Endpoints**: Queries configured cluster endpoints to verify ONLINE/OFFLINE health status.

### Operational Edge Cases & Mitigations

| Edge Case | Failure Mode / Symptom | Mitigation / Behavior |
| :--- | :--- | :--- |
| **E2BIG OS Buffer Limit** | `Argument list too long` when passing massive code files or failing test logs to the Oracle CLI. | `oracle_agent.py` automatically writes large prompts to temporary files (`.oracle_prompt_<tmp>.txt`) and executes via the `--file` argument, bypassing kernel limits. |
| **Missing `rsync` Binary** | System lacks `rsync` utility during session clear operations. | Engine falls back gracefully to Python's `shutil.copytree` with `dirs_exist_ok=True`. |
| **Unset `$XDG_CACHE_HOME`** | System environment variable for cache root is undefined. | Path resolution defaults safely to `~/.cache/aider_factory_cache/<project>/.aider_factory/`. |
| **Unsafe CLI Session Names** | Pass arguments with spaces or special characters (e.g. `"Refactor / Auth"`). | Deterministically sanitized via regex `re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name)` before directory creation. |
| **Corrupted Sidecar JSON** | Invalid JSON syntax in `.oracle_session.json` or `.helper_session.json`. | Exception handled gracefully; sidecar is treated as empty and overwritten on next turn. |
| **Vault Orphans** | A task crashes mid-execution, leaving active state files un-vaulted. | `_swap_in_state` forcefully clears active files before swapping in the correct vaulted state, ensuring the next task begins with a clean, deterministic prefix. |

### Master Logging & Telemetry Extraction
The `OSTee` interceptor captures all `stdout/stderr` into `.aider_factory/logs/<config>_run_<time>.log`. Post-execution, `aggregate_costs.py` regex-scans this master log for `COST_PATTERN` (`Tokens: ... Cost: ...`) to compute the exact total run cost, bridging the gap between isolated node executions.
