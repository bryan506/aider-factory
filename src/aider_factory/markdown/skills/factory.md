# SKILL: Pipeline Orchestrator (`aider-factory`)

`aider-factory` is the core DAG (Directed Acyclic Graph) pipeline orchestrator. It reads the active YAML configuration file, resolves file dependencies, and executes the sequence of AI tasks (RAG ingestion, Architect planning, Editor implementation, testing, and validation).

Use this skill to trigger a full pipeline run after you have finished setting up a workspace or modifying the configuration via `aider-helper`.

---

## 1. Running the Pipeline

The orchestrator runs under Aider's bundled Python environment, ensuring all dependencies (LanceDB, LiteLLM, PyYAML) are perfectly isolated.

### Default Execution
If you run the command without arguments, it automatically looks for `.aider_factory/.env.yml` (or `.env.yml` at the project root) and executes it.
```bash
aider-factory
```
*(Note: You can also use the local bash wrapper: `.aider_factory/bash/factory`)*

### Custom Configuration Execution
If you have multiple configurations (e.g., one for autonomous overnight runs, one for interactive RAG ingestion), you can pass the specific YAML file as an argument.
```bash
aider-factory .aider_factory/.env_auto_ocr.yml
```

---

## 2. Cost Aggregation & Log Analysis

Every time `aider-factory` runs, it pipes all output (from Python, Aider, Rscript, and subprocesses) into a timestamped log file located in `.aider_factory/logs/`.

At the end of the run, it automatically aggregates the token costs across all sub-agents (Architect, Editor, Oracle). If you need to re-run the cost analysis on an archived log, use the aggregator script:

```bash
# Run the cost aggregator on a specific log file
~/.local/share/uv/tools/aider-chat/bin/python .aider_factory/python/aggregate_costs.py .aider_factory/logs/<logfile>.log
```

---

## Agent Best Practices

1. **Configure First, Run Second:** Always ensure the YAML configuration is correct (using `aider-helper query`) before invoking `aider-factory`.
2. **Interactive vs Autonomous:** Be aware of the `pair_programming` toggle in the YAML. If `pair_programming: true`, running `aider-factory` will drop you into an interactive PTY session. If `pair_programming: false`, it will run autonomously to completion.
3. **Non-Blocking Failures:** If a specific task fails (e.g., a test loop exhausts its attempts), `aider-factory` does *not* crash. It marks that node as failed and continues executing the rest of the DAG for other files. Check the final terminal output or the log file to see the complete success/failure matrix.
