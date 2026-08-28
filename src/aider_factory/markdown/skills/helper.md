---
name: aider-helper
description: Interactive configuration architect and terminal assistant for querying, updating pipeline YAML schemas, and general shell coding tasks.
---

# SKILL: AI Factory Helper (`aider-helper`)

`aider-helper` is an interactive assistance tool for the AI Factory operating in two distinct roles:
1. **Configuration Architect (Default)**: Inspects and modifies pipeline YAML configurations (`.env.yml`) using minimal-delta edits.
2. **Terminal Assistant (`--terminal` / `-t`)**: General-purpose coding and debugging assistant decoupled from pipeline configuration context.

Both modes maintain independent, persistent KV-cache sessions (`.helper_session.json` and `.helper_terminal_session.json`).

## Operational Contract & Invariants

1. **Schema-Safe Modifications**: Delegate pipeline YAML updates to `aider-helper query` to ensure adherence to schema structures.
2. **Read-Only Safety Gate**: Use `--ask` (`-a`) when querying configuration or architecture to prevent modifications to files on disk.
3. **Session Hygiene**: Clear cached sessions (`aider-helper --clear`) when transitioning to an unrelated task to avoid prompt drift.

---

## Command Reference & Parameter Table

| Command / Flag | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `query "<instruction>"` | | *(Required)* | Instruction, question, or configuration edit request. |
| `--terminal` | `-t` | `False` | Activates terminal coding assistant mode (omits YAML configuration context). |
| `--ask` | `-a` | `False` | Forces read-only answering; suppresses modifying configuration files on disk. |
| `--file <path>` | `-f` | Active `.env.yml` | Targets a specific YAML configuration file. |
| `--context <paths>` | `-c` | `None` | Injects comma-separated file paths into prompt context. |
| `--repo-map` | `-r` | `False` | Injects repository map (`.aider_factory/static_repo_map.md`) into context. |
| `--master` | `-m` | `False` | Injects skills reference documents and YAML documentation into context. |
| `--expert` | `-e` | `False` | Injects skills references, YAML documentation, and the full Factory Service Manual into context. |
| `--clear` | | `False` | Resets active helper session history (use `-t --clear` for terminal session). |
| `bootstrap` | | | Launches interactive interview to generate initial workspace files. |

### Environment Variables

| Variable | Default / Fallback | Description |
| :--- | :--- | :--- |
| `AIDER_HELPER_MODEL` | Provider key default / `gemini/gemini-2.5-flash` | Overrides the LLM model used specifically for `aider-helper` queries. |
| `AIDER_HELPER_API_BASE` | `None` / `LITELLM_BASE_URL` | Sets a custom OpenAI-compatible inference base URL (e.g. local llama-server or vLLM). |

---

## Core Operational Workflows

### 1. Configuration Architect Workflows

```bash
# Query active pipeline settings (read-only)
aider-helper query -a "What is the architect model and temperature?"

# Modify configuration safely (rewrites target YAML)
aider-helper query "Update architect model to anthropic/claude-3-5-sonnet-20241022 in phase 1"

# Target specific configuration file with reference context
aider-helper query -f .aider_factory/.env_custom.yml -c docs/spec.md "Update target_files to match specification"

# Query helper with tool skill awareness (Master mode)
aider-helper query -m -a "How do I configure debate loops in the review phase?"

# Query helper with full Factory Service Manual and skills (Expert mode)
aider-helper query -e -a "Explain the mathematical and tag state transitions in validator.py"

# Configure custom local endpoint or cloud model via environment variables
export AIDER_HELPER_MODEL="openai/qwen2.5-coder:latest"
export AIDER_HELPER_API_BASE="http://192.168.100.1:8080/v1"
aider-helper query -a "Verify my phase structure against the schema"
```

### 2. Terminal Assistant Workflows (`-t`)

```bash
# General debugging or unix question
aider-helper query -t "How do I configure a systemd user service with auto-restart?"

# Review code files for concurrency or logic issues
aider-helper query -t -c src/service.py "Analyze error handling and thread safety"

# Query codebase structure using repository map
aider-helper query -t -r "Where are database models and migrations located?"

# Combine POSIX short flags (Terminal + Ask + Repo-Map) for fast architectural queries
aider-helper query -tar "Which files handle the database connection?"
```

### 3. Session Management

```bash
# Clear Configuration Architect session cache
aider-helper --clear

# Clear Terminal Assistant session cache
aider-helper -t --clear
```

---

## Canonical Usage Patterns

```bash
# Pattern A: Updating Pipeline Configuration
# 1. Inspect current phase layout
aider-helper query -a "List all enabled phases"
# 2. Apply configuration adjustment
aider-helper query "Enable pre-edit debate in code phase with 3 loops"

# Pattern B: Standalone Code Review in Terminal
aider-helper query -t -c src/service.py "Identify potential unhandled edge cases in process_request()"
```

---

## Execution Checklist

- [ ] Use `-a` (`--ask`) when only inspecting settings to prevent accidental file writes.
- [ ] Use `-t` (`--terminal`) for non-pipeline programming questions to conserve tokens.
- [ ] Clear session state via `aider-helper --clear` before starting unrelated workflows.
- [ ] Combine short boolean flags where appropriate (e.g., `-mta` for master + terminal + ask).
