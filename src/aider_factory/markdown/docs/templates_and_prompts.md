# Interaction Templates & Prompt Engineering Architecture

## 1. Executive Overview & Foundational Invariants

The Interaction Templates & Prompt Engineering Architecture governs how autonomous AI agents behave, reason, and output within the AI Factory pipeline. Every plan, debate instruction, and oracle directive is a user-editable Markdown file acting as a "prompt program."

### Foundational Invariants
- **Strict 3-Tier Hierarchy**: Templates are strictly segregated into User-Customizable, Infrastructure (Parsing-Contract), and Strategy Workflow tiers. Infrastructure templates must never be arbitrarily modified, as they dictate deterministic regex parsing logic.
- **Zero-Placeholder Guarantee**: Templates strictly forbid the generation of `TODO`s, stubs, unexpanded lists, or truncated markdown. Agents are instructed to provide complete, paste-ready outputs.
- **Imperative Persona Design**: All prompts are written in the imperative, second-person voice (e.g., "You are the Lead Systems Architect...").
- **Contextual Determinism**: Templates explicitly define scope boundaries, forbidding agents from modifying reference files, configuration files, or context files outside the assigned target list.

---

## 2. System Topology & Lifecycle Flowcharts

### Template Directory Topology

```text
.aider_factory/markdown/
├── templates/                  # Tier 1: User-Customizable
│   ├── implement.md            # Feature implementation instructions
│   ├── testing.md              # Unit test authoring instructions
│   └── validate.md             # Senior code reviewer audit instructions
├── internal/                   # Tier 2: Infrastructure & Parsing Contracts
│   ├── analyze_bugs.md         # Architect's debug instructions (Code debate)
│   ├── apply_evidence_template.md # Editor rules for verbatim corrections
│   └── deliberation_evidence_template.md # Architect role in evidence debates
└── oracle_pre_plan/            # Tier 3: Strategy Workflow
    ├── strategy_instruct_template.md # Phase-0 Oracle generation instructions
    └── strategy_template.md    # Empty target populated by the architect
```

### Template Injection Lifecycle Flowchart

```text
┌──────────────────────┐       ┌──────────────────────┐       ┌──────────────────────┐       ┌──────────────────────┐
│ Phase 0: Strategy    │       │ Phase 1: Implement   │       │ Phase 2: Validate    │       │ Phase 3: Write Tests │
│ (Oracle Pre-Plan)    │       │ (Job One)            │       │ (Job Two)            │       │ (Job Three)          │
├──────────────────────┤       ├──────────────────────┤       ├──────────────────────┤       ├──────────────────────┤
│ 1. Load strategy_    │       │ 1. Load implement.md │       │ 1. Load validate.md  │       │ 1. Load testing.md   │
│    instruct_template │──────►│ 2. Inject context    │──────►│ 2. Splice strategy   │──────►│ 2. Inject context    │
│ 2. Oracle generates  │       │ 3. Agent executes    │       │    content dynamically│       │ 3. Agent writes tests│
│    strategy_template │       │    modifications     │       │ 3. Agent audits code │       │                      │
└──────────────────────┘       └──────────────────────┘       └──────────────────────┘       └──────────────────────┘
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### YAML Path Resolution Rules (`resolve_template_path`)

The pipeline resolves template paths using a strict 5-priority fallback mechanism implemented in `run_workflow.py`. This ensures that local project overrides take precedence over globally packaged defaults.

1. **Exact Local Path**: Checks if the exact relative or absolute path exists in the `working_directory`.
2. **Local `.aider_factory/`**: Checks under `working_directory/.aider_factory/<path>` (preserving subfolders).
3. **Flat Local Fallback**: Checks `working_directory/.aider_factory/<basename>` (e.g., flat `CONVENTIONS.md`).
4. **Global Package Fallback**: Checks the globally installed `aider_factory` site-packages directory using the relative path.
5. **Global Flat Fallback**: Checks the site-packages root for the basename.

**Relative Scoping Differences:**
- **Phase `plans:` block**: Paths are resolved relative to `.aider_factory/`.
  - *Example*: `"markdown/templates/implement.md"` resolves to `.aider_factory/markdown/templates/implement.md`.
- **Phase `oracle:` block**: Paths are resolved relative to the `working_directory`.
  - *Example*: `".aider_factory/markdown/internal/analyze_bugs.md"`.

### Dynamic Plan Splicing (`_render_validate_template`)

To ensure continuity between implementation and validation, `run_workflow.py` dynamically splices the completed strategy or implementation plan into the validation template.

1. The orchestrator resolves the strategy content by checking `plans.validate_strategy_file`. If unset, it falls back to the last completed `.md` file in the DAG, and finally defaults to `.aider_factory/markdown/oracle_pre_plan/strategy_template.md`.
2. It loads the `validate.md` template.
3. It utilizes `re.sub` to inject the strategy content immediately under the exact header `## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS`.
4. The rendered template is saved ephemerally to `.aider_factory/sessions/<session>/templates/<stem>_validate_rendered.md` and passed to the agent as the `message_file`.

### Prompt Engineering & Negative Constraints

Templates are engineered using strict negative constraints to prevent LLM laziness and hallucination:
- **Anti-Stub Rules**: "Do not use placeholders (NULL, TODO, 'if needed') for any element within this task's scope."
- **Verbatim Contracts**: In infrastructure templates (e.g., `apply_evidence_template.md`), editors are constrained to "insert ONLY the Oracle's verbatim text; never alter the tags."
- **Deterministic Formatting**: Debates enforce machine-parseable boundaries. The Architect must end with `PROPOSAL: <fix>`, and the Oracle must end with `VERDICT: AGREE` or `VERDICT: OBJECT - <reason>`.

---

## 4. Exhaustive CLI Invocations & Command Matrix

While templates are primarily driven by the YAML configuration, CLI commands interact with them by overriding context or invoking specific infrastructure templates during debates.

| Command / Invocation | Target Template / Behavior | Description |
| :--- | :--- | :--- |
| `aider-oracle --file <path>` | Raw File Injection | Bypasses standard templates; sends the exact contents of `<path>` as the raw prompt to the Oracle. |
| `aider-oracle --debate code` | `analyze_bugs.md` | Triggers the infrastructure code debate template, forcing the Oracle to evaluate a failing test log. |
| `aider-oracle --debate review` | `deliberation_evidence_template.md` | Triggers the infrastructure review debate template for exact-substring grounding checks. |
| `aider-validate --autofix` | N/A (Deterministic) | Bypasses agent templates entirely, executing a deterministic Python ellipsis-stitch repair. |

---

## 5. Configuration Schema & YAML Knobs

The assignment of templates is controlled via the `.env.yml` schema under the `plans:` and `oracle:` blocks.

### `plans:` Schema (Resolved relative to `.aider_factory/`)

```yaml
phases:
  - name: "Implementation"
    plans:
      job_one_plan: "markdown/templates/implement.md"
      job_two_plan: "markdown/templates/validate.md"
      job_three_plan: "markdown/templates/testing.md"
      iterate_plan: "markdown/templates/testing_unit_iterate.md"
      deliberate_plan: "markdown/internal/deliberation_evidence_template.md"
      apply_plan: "markdown/internal/apply_evidence_template.md"
      analyze_bugs_plan: "markdown/internal/analyze_bugs.md"
      ocr_phase_plan: "markdown/oracle_pre_plan/strategy_instruct_template.md"
      validate_strategy_file: "markdown/oracle_pre_plan/strategy_template.md"
```

### `oracle:` Schema (Resolved relative to `working_directory`)

```yaml
phases:
  - name: "RAG Review"
    oracle:
      template: ".aider_factory/markdown/templates/literary_review_template.md"
      start_job: true
      full_document: true
      pre_edit_debate:
        enabled: true
        insert_debate: [true, false, false]
        job_debate_template: ".aider_factory/markdown/templates/job_debate.md"
```

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

### Operational Edge Cases & Mitigations

| Edge Case | Failure Mode / Symptom | Mitigation / Behavior |
| :--- | :--- | :--- |
| **Missing Local Template** | User specifies a custom template in YAML that does not exist on disk. | `resolve_template_path` automatically falls back to the globally packaged default in `site-packages`. If completely missing, execution halts with a path resolution error. |
| **Parsing Contract Violation** | User edits `analyze_bugs.md` and removes the instruction to output `PROPOSAL:`. | `deliberate.py` fails to regex-match the proposal, logging `(no PROPOSAL line)` and potentially deadlocking the debate. **Rule:** Never edit Tier 2 Infrastructure templates. |
| **Missing Splicing Header** | User edits `validate.md` and removes `## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS`. | `_render_validate_template` detects the missing header and safely appends the strategy content to the very bottom of the file instead of inline replacement. |
