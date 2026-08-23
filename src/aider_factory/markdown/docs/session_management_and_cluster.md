# Session Management, Cold-Storage Caching & Cluster Resource Management

The `aider-factory` framework provides an enterprise-grade session lifecycle, cold-storage archiving, and cluster management subsystem designed for deterministic task resumption, multi-workspace isolation, and zero-leakage GPU inference slot management.

---

## 1. Local Workspace Session Sandboxing & Paired Configuration

Every session in `aider-factory` is self-contained within `.aider_factory/sessions/<slug>/`, pinned to the workspace repository root:

```text
.aider_factory/
├── .env.yml                        # Global DAG fallback configuration
├── .helper_session.json            # Configuration assistant KV history
├── .helper_terminal_session.json   # Terminal assistant KV history
├── .oracle_session.json            # Knowledge Oracle multi-turn LLM context
├── .oracle_session.json.costs.json # Oracle cumulative cost accounting ledger
├── .oracle_debate_session.json     # Refereed escalation debate context
├── .debate_aider_history.md        # Architect debate turn history
└── sessions/
    ├── default/
    │   ├── session.yml             # Paired YAML pipeline configuration
    │   ├── .aider.chat.history.md  # Multi-turn conversational history
    │   ├── .aider.input.history    # Terminal prompt history (arrow-up recall)
    │   ├── .oracle_session.json    # Session-scoped Oracle context
    │   ├── .oracle_session.json.costs.json
    │   └── .oracle_debate_session.json
    ├── feature_auth/
    │   ├── session.yml
    │   └── ...
    └── session_20260401_143022/            # Auto-archived unnamed run
        └── session.yml
```

### Session Name Sanitization
Session names passed via CLI (e.g. `aider-factory "Refactor / Auth Service"`) are sanitized into safe directory slugs:
```python
slug = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', target_session)
```

---

## 2. Session Lifecycle & KV-Cache Restoration Flowchart

```
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

### What is Restored vs. What is Refreshed

| Component | What is Restored (Preserved) | What is Refreshed (Fresh) |
| :--- | :--- | :--- |
| **Aider Chat Engine** | • Multi-turn discussion context<br>• Terminal prompt history (Up-Arrow)<br>• LLM KV-cache prefix | • Current git working tree<br>• Active file contents on disk<br>• Repo map AST symbols |
| **Paired Configuration** | • Prior conversation state maintained seamlessly | • Edits to models, context files, or phase toggles in `session.yml` take immediate effect on resume |
| **Knowledge Oracle** | • Multi-turn debate context & RAG history | • Vector store queries fresh chunks against latest code |
| **Task Retry Loops** | • Conversation memory is retained across attempts (no clobbering) | • Fresh test failure logs are passed to the next loop attempt |

---

## 3. Safety-by-Default Cold-Storage Backup Engine

Destructive session operations in `aider-factory` are non-destructive by default. Before removing any active session files or sidecar artifacts, the workspace's `.aider_factory` directory is synchronized to the user's cold-storage cache directory.

### Cache Directory Resolution
The backup root is resolved according to the XDG Base Directory Specification:
* `$XDG_CACHE_HOME/aider_factory_cache/<project_name>/.aider_factory/`
* Defaults to `~/.cache/aider_factory_cache/<project_name>/.aider_factory/` when `$XDG_CACHE_HOME` is unset.

### Transfer Mechanics (`rsync` with `shutil` Fallback)
1. **Primary (`rsync -a`):** If `rsync` is installed, `_backup_workspace_cache` executes atomic, delta transfers preserving permissions, timestamps, and symlinks without the `--delete` flag. This allows the cache to accumulate historical sessions over time.
2. **Fallback (`shutil.copytree`):** If `rsync` is unavailable, the engine falls back to `shutil.copytree(..., dirs_exist_ok=True)`.

---

## 4. Session Invocations, Clearing & Permanent Deletion (`--forever`)

To bypass the cold-storage backup and permanently delete files, pass the `--forever` flag.

### Unified Command Matrix & Flag Permutations

| Action | Local Command | Global Command (`--global` / `-g`) | Disk Artifact Path | Behavior & Invariants |
| :--- | :--- | :--- | :--- | :--- |
| **Start / Resume Session** | `aider-factory <name>`<br>`aider-factory -s <name>` | — | `.aider_factory/sessions/<slug>/` | Creates directory if new; restores prior chat and input history if resuming. |
| **Start with Explicit Config** | `aider-factory <cfg.yml> <name>`<br>`aider-factory <name> <cfg.yml>` | — | `.aider_factory/sessions/<name>/session.yml` | Freezes and pairs `<cfg.yml>` to the session directory as `session.yml`. |
| **Resume Paired Config** | `aider-factory <name>` | — | `.aider_factory/sessions/<name>/session.yml` | If no YAML is passed, automatically loads and executes the session's existing `session.yml`. |
| **Auto-Archived Unnamed Run** | `aider-factory`<br>`aider-factory .env.yml` | — | `.aider_factory/sessions/session_YYYYMMDD_HHMMSS/` | Generates a timestamped session folder, clones active `.env.yml` into it, and saves conversation. |
| **List All Sessions** | `aider-factory --list-sessions` | `aider-factory --list-sessions -g` | Scans `.aider_factory/sessions/` | Prints session slugs, timestamps, sizes (KB), and config pairing status (`paired` vs `no config`). |
| **Inspect System Status** | `aider-factory --status` | `aider-factory --status -g` | Dynamic scan | Reports active sessions, side-agent memory, and remote inference cluster slots. |
| **Clear Specific Session** | `aider-factory --clear-session <name>`<br>`... --forever` | `aider-factory --clear-session <proj>/<name> -g`<br>`... --forever` | Deletes `.aider_factory/sessions/<slug>/` | Backs up to `~/.cache/aider_factory_cache/<project>/` by default before deleting. Use `--forever` to purge permanently without cache. |
| **Clear All Sessions** | `aider-factory --clear-all`<br>`... --forever` | `aider-factory --clear-all -g`<br>`... --forever` | Deletes `.aider_factory/sessions/` | Backs up all sessions to cache by default before deleting. Supports `--global` (`-g`) and `--forever`. |
| **Clear All Sidecars + Slots** | `aider-factory --clear-side-sessions`<br>`... --forever` | `aider-factory --clear-side-sessions -g`<br>`... --forever` | Deletes sidecar JSONs and releases slots | Backs up sidecars to cache by default, deletes files, and releases remote cluster inference slots. Supports `--forever`. |
| **Clear Specific Sidecar** | `aider-factory --clear-side-session <target>`<br>`... --forever` | `aider-factory --clear-side-session <target> -g`<br>`... --forever` | Deletes target sidecar files | Backs up target sidecar to cache by default before deleting. Supports `--forever`. |
| **Clear Active Oracle Context** | `aider-oracle --clear` | — | Deletes `.oracle_session.json` & `.oracle_debate_session.json` | Respects `ORACLE_SESSION_FILE` and wipes only the active session's Knowledge Oracle and debate history. |

### Target Aliases for `--clear-side-session`
* `helper` or `config`: Clears `.helper_session.json`.
* `terminal` or `term`: Clears `.helper_terminal_session.json`.
* `oracle`: Clears `.oracle_session.json` and `.oracle_session.json.costs.json`.
* `debate`: Clears `.oracle_debate_session.json` and `.debate_aider_history.md`.
* `<session_name>`: Clears session-scoped sidecars under `sessions/<session_name>/`.

---

## 5. Side-Agent & Helper Persistence Architecture

### The "Append-Only" KV-Cache Persistence Model
`aider-helper` and `aider-oracle` maintain persistent sessions mathematically optimized for Prefix Caching on local inference servers (llama.cpp, vLLM).

When passing heavy documents (`--master`, `--expert`, `--context`), they are appended once to the persistent `.json` history. Subsequent user turns append short queries, achieving 100% KV cache hits on inference backends.

### Side-Agent Session Files
- `.helper_session.json` — Configuration assistant conversational state.
- `.helper_terminal_session.json` — General AI terminal assistant state.
- `.oracle_session.json` — Regular Knowledge Oracle query state.
- `.oracle_debate_session.json` — Multi-turn refereed debate context.

---

## 6. Global Workspace Registry (`registry.json`)

To allow managing sessions across multiple repositories from any directory, `aider-factory` maintains a global workspace registry at `~/.config/aider_factory/registry.json`:

```json
{
  "projects": [
    "/home/user/projects/finance-core",
    "/home/user/projects/trading-engine"
  ]
}
```

* **Auto-Registration:** Every time `aider-factory` runs inside a directory, that project root is registered in `registry.json`.
* **Auto-Pruning:** When enumerating projects, deleted or moved directories are automatically pruned from the registry file.

---

## 7. Diagnostic Status Dashboard (`--status`)

Run `aider-factory --status` (or `aider-factory --status --global`) to inspect active sessions, side-agent memory, and remote inference server health:

```bash
aider-factory --status
aider-factory --status --global
```

### Dashboard Output Sections
1. **Main Aider Sessions**: Lists session names, last modified timestamp, chat history size (KB), and config pairing status (`paired` vs `no config`).
2. **Side-Agent Sessions & KV Caches**: Reports turn counts, disk sizes, and timestamps for `helper`, `terminal`, `oracle`, and `debate` sessions.
3. **Remote Inference Cluster & KV Slots**: Queries cluster endpoints (from `endpoints:` in `.env.yml` and environment variables), probing active slots on `llama-server` instances.

---

## 8. Remote Cluster Slot Probing & VRAM Freeing (`/slots`)

When running local inference servers (such as `llama-server`), active sessions hold KV cache memory in allocated server "slots". Over time, stale sessions occupy GPU VRAM.

### How Slot Probing Works (`_probe_cluster_slots`)
Queries `{base_url}/slots` with a 1.0s timeout:
* Returns total available slots and currently active processing slots.
* Surfaces connection state: `ONLINE (0/4 slots active via http://.../slots)`.

### How Slot Release Works (`_release_cluster_slots`)
When clearing side sessions (`--clear-side-sessions`), `aider-factory` executes a POST request to `{base_url}/slots/{slot_id}?action=release` for every allocated slot on the cluster:
* Immediately frees the allocated context buffer in GPU VRAM.
* Resets the server slot state to idle without needing to restart the `systemd` service.

---

## 9. Static Repository Map Generation

`aider-factory` generates static, token-budgeted repository maps using ephemeral ignore files, ensuring the main `.aiderignore` is never mutated:

```bash
# Generate source-only repository map (excludes test directories) -> static_repo_map.md
aider-factory --repo-map

# Generate test-only repository map (excludes source files) -> static_repo_map_tests.md
aider-factory --repo-map-tests

# Generate both maps
aider-factory --repo-map-all

# Override map token budget (default: 4096)
aider-factory --repo-map --map-tokens 8192

# Generate static maps across all registered workspaces globally
aider-factory --repo-map-all --global
```
