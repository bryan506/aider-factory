# Session Management, Global Registry & Cluster Resource Management

`aider-factory` provides an enterprise-grade session lifecycle and cluster management framework designed for deterministic task resumption, multi-workspace isolation, and zero-leakage GPU inference slot management.

---

## 1. Local Workspace Session Sandboxing

All active state is contained within `.aider_factory/sessions/<slug>/`, pinned to the repository root:

```text
.aider_factory/
└── sessions/
    ├── default/
    │   ├── session.yml                     # Paired pipeline configuration
    │   ├── .aider.chat.history.md          # Multi-turn chat history (restored via --restore-chat-history)
    │   ├── .aider.input.history            # Terminal prompt history (arrow up recall)
    │   ├── .oracle_session.json            # Knowledge Oracle multi-turn LLM context
    │   ├── .oracle_session.json.costs.json # Oracle cost accounting ledger
    │   ├── .oracle_debate_session.json     # Refereed debate context
    │   └── .debate_aider_history.md        # Architect debate turn history
    ├── feature_auth/
    │   ├── session.yml
    │   └── ...
    └── session_20260401_143022/            # Auto-archived unnamed run
        └── session.yml
```

### Session Name Sanitization
Session names passed via CLI (e.g. `aider-factory "Refactor / Auth Service"`) are sanitized using regex:
```python
slug = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', target_session)
```

---

## 2. Global Workspace Registry (`registry.json`)

To allow managing sessions across multiple repositories from any directory, `aider-factory` maintains a global workspace registry at `~/.config/aider_factory/registry.json`:

```json
{
  "projects": [
    "/home/user/projects/finance-core",
    "/home/user/projects/trading-engine"
  ]
}
```

* **Auto-Registration**: Every time `aider-factory` runs inside a directory, that project root is registered in `registry.json`.
* **Auto-Pruning**: When enumerating projects, deleted or moved directories are automatically pruned from the registry file.

---

## 3. Diagnostic Status Dashboard (`--status`)

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

## 4. Remote Cluster Slot Probing & VRAM Freeing (`/slots`)

When running local inference servers (such as `llama-server`), active sessions hold KV cache memory in allocated server "slots". Over time, stale sessions occupy GPU VRAM.

### How Slot Probing Works (`_probe_cluster_slots`)
Queries `{base_url}/slots` with a 1.0s timeout:
* Returns total available slots and currently active processing slots.
* Surfaces connection state: `ONLINE (0/4 slots active via http://.../slots)`.

### How Slot Release Works (`_release_cluster_slots`)
When clearing side sessions, `aider-factory` executes a POST request to `{base_url}/slots/{slot_id}?action=release` for every allocated slot on the cluster:
* Immediately frees the allocated context buffer in GPU VRAM.
* Resets the server slot state to idle without needing to restart the `systemd` service.

---

## 5. Unified CLI Matrix: Local vs. Global

| Action | Local Command | Global Command (`--global` / `-g`) |
| :--- | :--- | :--- |
| **Start / Resume Session** | `aider-factory <name>` | — |
| **Start with Config** | `aider-factory <config.yml> <name>` | — |
| **List All Sessions** | `aider-factory --list-sessions` | `aider-factory --list-sessions --global` |
| **Inspect System Status** | `aider-factory --status` | `aider-factory --status --global` |
| **Clear Specific Session** | `aider-factory --clear-session <name>` | `aider-factory --clear-session <project>/<name> -g` |
| **Clear All Sessions** | `aider-factory --clear-all` | `aider-factory --clear-all --global` |
| **Clear Side-Agent Session** | `aider-factory --clear-side-session <alias>` | `aider-factory --clear-side-session <alias> -g` |
| **Clear All Sidecars + Slots** | `aider-factory --clear-side-sessions` | `aider-factory --clear-side-sessions --global` |

### Target Aliases for `--clear-side-session`
* `helper` / `config` — Clears `.helper_session.json`
* `terminal` / `term` — Clears `.helper_terminal_session.json`
* `oracle` — Clears `.oracle_session.json` and `.oracle_session.json.costs.json`
* `debate` — Clears `.oracle_debate_session.json` and `.debate_aider_history.md`
* `<session_name>` — Surgically clears session-scoped sidecars in `sessions/<session_name>/`

---

## 6. Static Repository Map Generation

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
