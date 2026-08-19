# SKILL: Headless Code Application (`aider-apply`)

A specialized, headless execution client that applies the Architect's implementation specifications directly to target files without invalidating local LLM KV caches (Prefix Caches).

It extracts SEARCH/REPLACE diffs from the active session chat history, spins up an isolated editor process to modify files and create Git commits, and streams the `git diff` back to your terminal or Architect session.

---

## 1. The Core Rule: Zero KV-Cache Busting

When running on local model clusters (e.g., `llama-server`, vLLM), loading mutable code files into `/read` or `/add` causes total KV cache invalidation on every edit.

* **Immutable Reference Files**: Safe to load in `/read` (e.g. schemas, conventions, docs).
* **Mutable Target Files**: **NEVER** load into `/read` or `/add`. Introduce target files via the chat stream (`/run cat src/target.py`).
* **Applying Edits**: Always execute edits via `aider-apply` to keep the Architect's reasoning context 100% warm in GPU VRAM.

---

## 2. How to Invoke

Inside an interactive Aider session:
```bash
# 1. Apply edits to a target file using the Architect's latest turn
/run .aider_factory/bash/apply <target_file>
# or
/run aider-apply <target_file>

# 2. Apply edits to multiple target files
/run aider-apply src/service.py src/utils.py

# 3. Include prior discussion context (e.g., last 3 conversation turns)
/run aider-apply src/service.py --turns 3

# 4. Apply from a standalone Markdown spec file (bypasses chat history)
/run aider-apply src/service.py --spec specs/refactor_plan.md

# 5. Target a specific background worker session
/run aider-apply src/service.py --session worker_2
```

From standard terminal or scripts:
```bash
aider-apply <target_files...> [options]
```

---

## 3. Options & Flags

| Flag | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `files` | | *(Required)* | One or more target files to modify. |
| `--turns` | `-t` | `1` | Number of recent conversation turns to include in the synthesized specification. |
| `--spec` | `-s` | `None` | Path to an explicit Markdown specification file. |
| `--model` | `-m` | `None` | Override the editor model (e.g., `openai/qwen3.6-27B-90k:LATEST`). |
| `--session` | | `None` | Target session name (auto-discovered if omitted). |
| `--no-diff` | | `False` | Suppress printing the `git --no-pager diff HEAD~1` output. |

---

## 4. End-to-End Pair-Programming Workflow

```bash
# Step 1: Converse with the Architect in /ask mode
# User: "How should we implement calculate_tax in src/calculator.py?"
# Architect: Explores edge cases, validates formulas, and plans changes.

# Step 2: Request the final SEARCH/REPLACE block
# User: "Output the exact SEARCH/REPLACE blocks for src/calculator.py."
# Architect: Emits standard <<<<<<< SEARCH / ======= / >>>>>>> REPLACE blocks.

# Step 3: Apply the edit without leaving the session
/run aider-apply src/calculator.py

# Step 4: Review git diff and continue
# The diff prints immediately. Follow-up Architect turns evaluate only delta tokens (<1.2s)!
```
