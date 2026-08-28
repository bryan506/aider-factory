---
name: aider-factory
description: DAG pipeline orchestrator that resolves task dependencies and executes automated multi-phase AI workflows.
---

# SKILL: Pipeline Orchestrator (`aider-factory`)

`aider-factory` is the core Directed Acyclic Graph (DAG) pipeline orchestrator and workspace manager. It parses YAML workflow definitions, resolves inter-task dependencies, executes multi-phase AI pipelines (knowledge ingestion, architecture planning, code editing, testing, and evidence validation), manages multi-session persistence, generates static repository maps, and inspects cluster health.

## Operational Contract & Invariants

1. **Environment Isolation**: Always execute workflows via the global CLI `aider-factory` or local launcher `.aider_factory/bash/factory` to run within the managed runtime environment.
2. **Deterministic Execution**: Verify configuration settings in the target YAML file prior to triggering pipeline execution.
3. **Resilient Failure Handling**: Individual task failures (e.g., exhausted test iterations) do not crash the pipeline. The DAG records the failure node and completes remaining independent branches.
4. **Session & State Decoupling**: Sessions are persisted in `.aider_factory/sessions/<session_name>/` and automatically backed up to `~/.cache/aider_factory_cache/<repo_name>/` upon clearance unless `--forever` is specified.

---

## Command Reference & Parameter Table

| Command / Flag | Argument | Default | Description |
| :--- | :--- | :--- | :--- |
| `aider-factory` | Positional File/Session | `.aider_factory/.env.yml` | Executes the active default configuration pipeline. |
| `aider-factory <config.yml>` | File Path | `None` | Executes a specific workflow YAML configuration. |
| `aider-factory <session>` | String | `None` | Starts or resumes a named session using the active configuration. |
| `aider-factory <config.yml> <session>` | Path & String | `None` | Pairs a specific workflow configuration with a named session. |
| `--session <name>`, `-s <name>` | String | `None` | Explicitly targets or names the active execution session. |
| `--status` | None | `False` | Displays diagnostics for active sessions, side-agent sessions, and cluster endpoints. |
| `--list-sessions` | None | `False` | Lists all active workspace sessions, modification times, history sizes, and config pairing status. |
| `--clear-session <name>` | String | `None` | Deletes a named session (backed up to cache unless `--forever` is provided). |
| `--clear-all` | None | `False` | Clears all session archives in the current project (or globally with `-g`). |
| `--clear-side-session <name>` | String | `None` | Surgically deletes side-agent sessions (`helper`, `terminal`, `oracle`, `debate`, or `<session>`). |
| `--clear-side-sessions` | None | `False` | Surgically deletes all side-agent JSON and Markdown session files. |
| `--global`, `-g` | None | `False` | Executes command (`--status`, `--list-sessions`, `--clear-all`, repo maps) across all registered workspaces. |
| `--forever` | None | `False` | Permanently deletes sessions without backing up to `~/.cache/aider_factory_cache/`. |
| `--repo-map` | None | `False` | Generates static source repo map at `.aider_factory/static_repo_map.md`. |
| `--repo-map-tests` | None | `False` | Generates static test repo map at `.aider_factory/static_repo_map_tests.md`. |
| `--repo-map-all` | None | `False` | Generates both source and test static repository maps. |
| `--map-tokens <N>` | Integer | `2048` | Specifies the token budget for static repository map generation. |

---

## Core Operational Workflows

### 1. Running Pipeline Configurations & Named Sessions

```bash
# Execute active default workflow (.aider_factory/.env.yml)
aider-factory

# Execute custom workflow configuration
aider-factory .aider_factory/.env_batch_eval.yml

# Start or resume a named session (persisted under .aider_factory/sessions/refactor_core/)
aider-factory refactor_core

# Pair custom configuration with a named session
aider-factory .aider_factory/.env_feature.yml refactor_core
```

### 2. Workspace Diagnostics & Session Management

```bash
# Check status of active sessions, side agents, and cluster inference endpoints
aider-factory --status

# List active sessions in current workspace
aider-factory --list-sessions

# List active sessions across all registered workspaces
aider-factory --list-sessions --global

# Clear a specific session (backed up to ~/.cache/aider_factory_cache/)
aider-factory --clear-session refactor_core

# Permanently delete a session without cache backup
aider-factory --clear-session refactor_core --forever

# Clear side-agent session caches (helper, oracle, debate)
aider-factory --clear-side-session oracle
aider-factory --clear-side-sessions
```

### 3. Static Repository Map Generation

Generate static repository maps to provide cached AST structures to agents without paying runtime overhead:

```bash
# Generate static source repo map (.aider_factory/static_repo_map.md)
aider-factory --repo-map

# Generate static test repo map (.aider_factory/static_repo_map_tests.md)
aider-factory --repo-map-tests

# Generate both source and test maps with custom token budget
aider-factory --repo-map-all --map-tokens 4096

# Generate repo maps across all registered workspaces globally
aider-factory --repo-map-all --global
```

### 4. Automated Cost Tracking & Post-Run Analysis

Pipeline runs stream telemetry live and automatically execute cost aggregation at completion. Log files are archived under `.aider_factory/logs/`:

```bash
# Analyze and aggregate token costs across all pipeline tasks
aider-cost .aider_factory/logs/<config_stem>_run_<timestamp>.log
```

---

## Canonical Pipeline Lifecycle

```bash
# Step 1: Inspect or adjust pipeline phases via helper
aider-helper query -a "What phases are configured in the active pipeline?"

# Step 2: Generate static repo maps for context caching
aider-factory --repo-map-all

# Step 3: Launch autonomous DAG execution with a named session
aider-factory .aider_factory/.env.yml feature_turn_1

# Step 4: Verify task status and cluster health
aider-factory --status
```

---

## Execution Checklist

- [ ] Confirm YAML syntax and active phases before launching `aider-factory`.
- [ ] Verify `pair_programming` setting (`true` for interactive PTY, `false` for headless batch).
- [ ] Run `aider-factory --repo-map` if the codebase structure has changed.
- [ ] Check terminal summary output and `.aider_factory/logs/` for task pass/fail status.
- [ ] Use `aider-factory --list-sessions` and `aider-factory --status` to monitor workspace state.
