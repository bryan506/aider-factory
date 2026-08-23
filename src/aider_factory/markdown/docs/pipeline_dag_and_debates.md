# 4-Stage Autonomous DAG Pipeline & Pre-Edit Debates

`run_workflow.py` and `orchestrate.py` implement an industrial-grade, 4-stage software engineering DAG with granular pre-edit debate insertion, dynamic strategy injection, and OS-level stream multiplexing.

---

## 1. The 4-Stage Autonomous Pipeline Architecture

The pipeline divides software development into four discrete, testable nodes:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   THE 4-STAGE AUTONOMOUS DAG                                    │
├───────────────────┬───────────────────┬─────────────────────────┬───────────────────────────────┤
│ STAGE 1:          │ STAGE 2:          │ STAGE 3:                │ STAGE 4:                      │
│ Implementation    │ Spec Audit        │ Write Tests             │ Self-Healing Loop             │
│ (`run_job_one`)   │ (`run_job_two`)   │ (`run_job_three`)       │ (`iterate_test`)              │
├───────────────────┼───────────────────┼─────────────────────────┼───────────────────────────────┤
│ • Architect plans │ • Senior reviewer │ • Writes unit tests for │ • Re-runs test suite          │
│ • Editor writes   │   spec audit      │   new implementation    │ • Captures failure logs       │
│   initial code    │ • Strategy-locked │ • Broad-scope coverage  │ • Auto-fixes code in a loop   │
│ • Pre-Debate: J1  │ • Pre-Debate: J2  │ • Pre-Debate: J3        │ • Final check confirmation    │
└───────────────────┴───────────────────┴─────────────────────────┴───────────────────────────────┘
```

---

## 2. Granular Pre-Edit Debates (`insert_debate`)

Before making file modifications in Job 1, Job 2, or Job 3, the Architect can consult the Knowledge Oracle in an autonomous multi-turn debate.

### Configuration Syntax (`.env.yml`)
```yaml
oracle:
  pre_edit_debate:
    enabled: true
    insert_debate: [1, 0, 0]      # [Job 1: Implement, Job 2: Audit, Job 3: Write Tests]
    loops: 3                      # Debate turns per job
    job_debate_template:          # Specialized template(s)
      - "src/aider_factory/markdown/oracle_pre_plan/strategy_instruct_template.md"
      - "src/aider_factory/markdown/internal/analyze_bugs.md"
      - ""
    job_debate_collection:        # Specialized vector collection(s)
      - "project_docs"
      - "project_specs"
      - "test_fixtures"
```

### Parsing & Resolution Mechanics
* **3-Tuple Normalization (`_parse_insert_debate`)**: Converts lists, tuples, or comma-separated strings (e.g. `[1, 0, 1]` or `"1, 0, 0"`) into `(bool(j1), bool(j2), bool(j3))`.
* **Template Routing (`_resolve_job_debate_template`)**: Index-matches the active job number to the template list, falling back to index 0.
* **Collection Routing (`_resolve_job_debate_collection`)**: Points each debate turn at a dedicated LanceDB collection directory.

---

## 3. Dynamic Strategy Injection (`_render_validate_template`)

When moving from Phase 0 (Planning) to Phase 1 (Execution), `_render_validate_template()` ensures the senior code reviewer in Job 2 audits code against the exact specifications established during planning:

1. Discovers `strategy_template.md` (or completed markdown outputs from prior phases).
2. Reads the default audit template (`markdown/templates/validate.md`).
3. Injects the strategy text directly into `## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS`.
4. Saves the rendered template to `.aider_factory/sessions/<slug>/templates/<stem>_validate_rendered.md` for Aider execution.

---

## 4. Multi-Round Escalation Reflexion (`escalation_debate`)

If the unit test suite fails during Stage 4 (`iterate_test`), the orchestrator triggers an escalation debate:

* **Debate Rounds (`rounds: 2`)**: Chained full debate cycles (Debate $\to$ Apply $\to$ Re-Test).
* **Cross-Round Memory (`pass_round_history: true`)**: Carries prior turn context and model KV caches across rounds.
* **Ledger Chaining**: Passes `<stem>.job_verdict_r1.md` and `<stem>.job_debate_r1.json` to Round 2 to prevent repeating failed proposals.

---

## 5. OS-Level File Descriptor Multiplexing (`OSTee`)

Standard Python logging does not capture subprocess stdout/stderr (such as child pytest, Rscript, Docker, or PTY terminal streams). `run_workflow.py` wraps execution in `OSTee`:

```python
self.orig_stdout_fd = os.dup(1)
self.orig_stderr_fd = os.dup(2)
self.pipe_r, self.pipe_w = os.pipe()
os.dup2(self.pipe_w, 1)
os.dup2(self.pipe_w, 2)
```

A background daemon thread continuously drains the pipe to the real terminal while recording an unbuffered, timestamped log file (`.aider_factory/logs/<config>_run_<timestamp>.log`).
