# SKILL: AI Factory Helper (`aider-helper`)

`aider-helper` is your persistent, interactive AI assistant for the AI Factory. It operates in two distinct personas:
1. **Configuration Architect (Default):** Understands the pipeline YAML schema, loads the active `.env.yml` into context, and safely applies minimal-delta edits to pipeline configurations.
2. **Terminal Assistant (`--terminal`):** A general-purpose software engineering assistant that strips away the YAML configuration context, allowing you to ask general coding, debugging, or unix questions directly from the shell.

Both modes maintain **independent, persistent KV-cache sessions** (`.helper_session.json` and `.helper_terminal_session.json`).

---

## 1. Configuration Architect Mode (Default)

Use this mode to query, understand, or modify the AI Factory pipeline configurations (`.env.yml`). By default, it automatically finds and targets the active project configuration.

### Basic Queries & Modifications
If you ask it to change a setting, it will rewrite the target YAML file automatically.
```bash
# Ask a question about the current configuration
aider-helper query "What is the current architect model?"

# Modify the configuration (automatically writes to the .env.yml file)
aider-helper query "Change the architect model to gemini/gemini-3.5-flash in the first phase."
```

### Targeting Specific Files (`--file` / `-f`)
If you want to modify a specific configuration file instead of the default, use `--file`.
*Note: If the targeted file does not exist, the helper will automatically create it using the master template.*
```bash
aider-helper query -f .aider_factory/.env_custom.yml "Enable run_job_one in the Code phase."
```

### Adding Extra Context (`--context` / `-c`)
Inject external files into the helper's prompt (comma-separated). Useful when you want the helper to configure the pipeline based on the contents of specific scripts or documentation.
```bash
aider-helper query -c src/main.py,docs/api.md "Update target_files to include src/main.py and docs/api.md."
```

### Repository Map (`--repo-map` / `-r`)
Injects the static repository map (`.aider_factory/static_repo_map.md`) into the helper's context. Useful for answering architectural or file-location questions across the entire codebase. 
*(Note: Requires manual generation first via Aider).*
```bash
# 1. Generate the static repo map
aider --map-tokens 4096 --show-repo-map > .aider_factory/static_repo_map.md

# 2. Query the helper with repository map context in terminal mode
aider-helper query -r -t "Which files handle database connections and schema migrations?"
```

### Conversational / Read-Only Mode (`--ask` / `-a`)
Forces the helper to *only* answer the question and prevents it from writing or modifying any YAML files on disk.
```bash
aider-helper query -a "What are the available RAG retrieval modes?"
```

### Master Mode (`--master` / `-m`)
Injects the skills reference documents into the helper's context. This gives the agent knowledge of specific CLI tools and agent capabilities without overwhelming it with deep architectural theory.
```bash
aider-helper query -m --ask "How do I use the aider-oracle debate feature?"
```

### Expert Mode (`--expert` / `-e`)
Injects both the skills reference documents AND the entire `factory_service_manual.md` (the comprehensive architectural documentation) into the helper's context.
*Warning: This consumes a large number of tokens. Use only for deep, complex architectural questions.*
```bash
aider-helper query -e --ask "How do I configure a pre-edit debate with pass_round_history?"
```

---

## 2. Terminal Assistant Mode (`--terminal` / `-t`)

Use this mode when you need general software engineering help that has *nothing to do with the pipeline YAML configuration*. It drops the YAML context to save tokens and acts as a standard coding assistant.

```bash
# Ask a general coding or unix question
aider-helper query -t "Explain compound indexing in SQLite"

# Review specific files for bugs (combining -t and -c)
aider-helper query -t -c src/main.py "Review this file for memory leaks and concurrency risks"

# Ask a general architectural question without modifying files
aider-helper query -t --ask "What is the best way to structure a React application?"
```

---

## 3. Session Management & Clearing (`--clear`)

Because `aider-helper` maintains persistent sessions to keep the LLM KV-cache warm, it remembers previous questions. If the context gets too long or you want to switch topics, you **must** clear the session.

```bash
# Clear the Configuration Architect session (.helper_session.json)
aider-helper --clear

# Clear the Terminal Assistant session (.helper_terminal_session.json)
aider-helper -t --clear
```

---

## 4. Workspace Bootstrapping (`bootstrap`)

Used to initialize a brand new AI Factory workspace. It launches an interactive terminal interview to capture user intent and generates the `.aider_factory/` directory, `.env.yml`, `.aiderignore`, and test runners.
*(Agents should generally advise human users to run this, rather than running it autonomously, as it requires interactive stdin).*
```bash
aider-helper bootstrap
```

---

## 5. Environment Variable Overrides (Model Routing)

You can override the model and API endpoint `aider-helper` uses on the fly by exporting environment variables before your command.

**Using a local model (e.g., llama.cpp, LM Studio, Ollama via LiteLLM):**
```bash
export AIDER_HELPER_MODEL="openai/qwen2.5-coder:latest"
export AIDER_HELPER_API_BASE="http://192.168.100.1:8080/v1"
export OPENAI_API_KEY="sk-dummy"
aider-helper query "..."
```

**Using a cloud provider (e.g., Anthropic):**
```bash
export AIDER_HELPER_MODEL="anthropic/claude-3-5-sonnet-20241022"
export ANTHROPIC_API_KEY="your-api-key"
aider-helper query "..."
```

**Reverting to default:**
```bash
unset AIDER_HELPER_MODEL AIDER_HELPER_API_BASE
```

---

## Agent Best Practices

1. **Do not guess YAML syntax:** If you need to modify the pipeline configuration but aren't sure of the exact YAML keys, use `aider-helper query "instruction"` and let the helper do the YAML writing. It knows the schema perfectly.
2. **Combine flags for precision (POSIX Short Flags):** You can combine short boolean flags into a single string. For example, instead of `-m -t -a`, you can write `-mta`. Note: If you include `-c` (context), it must be the last letter in the cluster because it takes an argument (e.g., `-atc src/main.py`).
3. **Clear stale context:** If you are starting a completely new task, run `aider-helper --clear` first to ensure previous configuration discussions don't hallucinate into your new request.

---

## End-to-End Example: Terminal Assistant

```bash
# 1. Ask a general software engineering question (multi-turn session memory active)
aider-helper query -t "<your general question here>"

# 2. Ask a follow-up question (remembers context!)
aider-helper query -t "<your follow-up question here>"

# 3. Clear the interactive terminal assistant session history when changing topics
aider-helper -t --clear
```
