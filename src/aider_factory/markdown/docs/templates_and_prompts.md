# Interaction Templates & Prompt Engineering Architecture

## 1. Executive Overview & Foundational Invariants

The Interaction Templates & Prompt Engineering Architecture establishes a deterministic, type-safe execution substrate for autonomous AI agents within the AI Factory pipeline. Prompts and plan templates within this subsystem are treated as formal software artifacts rather than conversational guides. Every phase instruction, architectural directive, debate critique, and evidence validation query is compiled from modular Markdown files that enforce rigid behavioral boundaries, explicit input/output schemas, and machine-verifiable evaluation contracts.

### Foundational Invariants

1. **Strict 3-Tier Template Hierarchy**:
   Templates are strictly isolated into three functional tiers to decouple user customizations from engine parsing contracts:
   - **Tier 1 (User-Customizable Workflow Templates)**: High-level instructions defining product features, testing methodologies, and architectural code audits (`implement.md`, `validate.md`, `testing.md`, `testing_unit_iterate.md`, `implement_docs.md`). Users may freely adapt these templates to their domain requirements.
   - **Tier 2 (Infrastructure & Parsing Contracts)**: Engine-internal templates that govern multi-agent consensus, automated patch application, and verbatim evidence repair (`analyze_bugs.md`, `deliberation_evidence_template.md`, `apply_evidence_template.md`). Modifying their structural tokens breaks deterministic regex parsing in `deliberate.py` and `validator.py`.
   - **Tier 3 (Strategy Workflow Templates)**: Templates governing pre-flight system planning and automated file manifest synthesis (`strategy_instruct_template.md`, `strategy_template.md`).
   - **Foundational Root (`CONVENTIONS.md`)**: The immutable project invariant file injected into all execution contexts to enforce zero-mock testing, role isolation, and non-destructive modifications.

2. **Parsing Contract Immutability**:
   Agents interacting through infrastructure templates must satisfy exact regular expression boundaries (e.g., `PROPOSAL:`, `VERDICT: AGREE|OBJECT|REVISE`, `<critique>...</critique>`). No conversational preamble or trailing commentary may supersede or alter these contractual tokens. Downstream arbiters parse these lines using strict multi-line regexes; missing or malformed tokens prevent state advancement.

3. **Production-Completeness Guarantee (Zero-Stub Mandate)**:
   Templates explicitly prohibit the synthesis of unfinished code, partial specs, or unresolved placeholders. Any emission of `TODO`, `pass`, `...`, `None`, or unexpanded Markdown tables is treated as a structural contract failure. Agents are strictly instructed to emit complete, paste-ready implementations.

4. **Imperative Multi-Persona Isolation**:
   Prompts enforce strict separation of agent responsibilities across distinct operational roles:
   - **Architect**: Exclusively reasons, analyzes, plans, and writes specifications; strictly forbidden from issuing `SEARCH/REPLACE` blocks or executing shell tools directly in conversational turns.
   - **Editor / Builder**: Surgically applies the Architect's specifications; strictly forbidden from modifying high-level design, altering architectural invariants, or inventing speculative scope.
   - **Oracle**: Evaluates propositions against verified LanceDB context or physical code repositories, issuing verbatim evidence citations and binding consensus verdicts.
   - **Validator / Auditor**: Deterministically verifies claims against raw source truth, executing exact-substring audits without model self-assessment.

5. **Context Window Hygiene & Token Budgeting Invariant**:
   Active context utilization must not exceed $70\text{--}80\%$ of total model context capacity. Token allocation adheres to strict sub-budgets:
   - $T_{\text{prefix}}$ ($5\text{--}10\%$): Immutable byte-parity prefix for KV-cache acceleration.
   - $T_{\text{repomap}}$ ($10\text{--}20\%$): Dependency graph nodes (bypassed with `--map-tokens 0` for isolated single-file tasks).
   - $T_{\text{retrieval}}$ ($20\text{--}30\%$): Deduplicated LanceDB knowledge snippets via Reciprocal Rank Fusion ($k=60$).
   - $T_{\text{history}}$ ($20\text{--}30\%$): Structured ledgers and rolling conversational state.
   - $T_{\text{headroom}}$ ($15\text{--}20\%$): Reserved generation buffer.

6. **The Protected Sentinel Set**:
   Context compression, summarization, and multi-turn state handoffs must never truncate or paraphrase the Sentinel Set: exact physical file paths, exported symbol names, numeric invariants, and active Task IDs.

---

## 2. System Topology & Lifecycle Flowcharts

### Template Directory Inventory

```text
.aider_factory/
├── CONVENTIONS.md                     # Foundational Root Invariants (Read-Only)
└── markdown/
    ├── templates/                     # Tier 1: User-Customizable Workflow Templates
    │   ├── implement.md               # Job 1: Feature implementation and architecture
    │   ├── validate.md                # Job 2: Spec compliance, audit, and verification
    │   ├── testing.md                 # Job 3: Unit and integration test authoring
    │   ├── testing_unit_iterate.md    # Job 4: Test failure fix and iteration constraints
    │   └── implement_docs.md          # Technical documentation authoring plan
    ├── internal/                      # Tier 2: Infrastructure & Parsing Contracts
    │   ├── analyze_bugs.md            # Code debate architect instructions (failing logs)
    │   ├── deliberation_evidence_template.md # Evidence grounding debate template
    │   └── apply_evidence_template.md # Deterministic patch application rules
    └── oracle_pre_plan/               # Tier 3: Strategy Workflow
        ├── strategy_instruct_template.md # Phase-0 Oracle generation instructions
        └── strategy_template.md       # Synthesized strategy & file manifest target
```

### End-to-End Pipeline DAG Lifecycle

The pipeline DAG coordinates planning, implementation, verification, and escalation across discrete job nodes:

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Phase 0: System Strategy & Pre-Planning                                                                │
│                                                                                                        │
│  [strategy_instruct_template.md] ──► (Oracle Pre-Plan Job) ──► [strategy_template.md]                  │
│                                                                       │                                │
│                                         (Sticky File Discovery)       │                                │
│                                         Target & Context Manifest ◄───┘                                │
└───────────────────────────────────────────────────┬────────────────────────────────────────────────────┘
                                                    │
┌───────────────────────────────────────────────────▼────────────────────────────────────────────────────┐
│ Phase 1: Implementation & Pre-Edit Deliberation                                                        │
│                                                                                                        │
│  [implement.md] ──► (Job 1 Pre-Debate: Oracle ◄──► Architect) ──► [job1_verdict.md]                   │
│                                                                           │                            │
│                                              (Headless Aider Session) ◄───┘                            │
│                                              Writes Target Files                                       │
└───────────────────────────────────────────────────┬────────────────────────────────────────────────────┘
                                                    │
┌───────────────────────────────────────────────────▼────────────────────────────────────────────────────┐
│ Phase 2: Specification Audit & Dynamic Validation                                                      │
│                                                                                                        │
│  [validate.md] ───┐                                                                                    │
│                   ├──► (_render_validate_template) ──► [rendered_validate.md] ──► (Job 2 Aider Audit) │
│  [strategy.md] ───┘    Slices Strategy Goals Under                                                     │
│                        "PREVIOUS COMPLETED SYSTEM GOALS"                                               │
└───────────────────────────────────────────────────┬────────────────────────────────────────────────────┘
                                                    │
┌───────────────────────────────────────────────────▼────────────────────────────────────────────────────┐
│ Phase 3: Test Generation & Execution Iteration                                                         │
│                                                                                                        │
│  [testing.md] ───────────────► (Job 3: Write Test Files)                                               │
│                                         │                                                              │
│  [testing_unit_iterate.md] ──► (Verify Loop: Run test_cmd ──► Error? ──► Architect/Editor Fix)          │
│                                         │                                                              │
│                                  (Suite Fails?)                                                        │
│                                         ▼                                                              │
│               [analyze_bugs.md] ──► (Escalation Debate: Oracle ◄──► Architect) ──► [verdict.md]        │
│                                                                                        │               │
│                                  (Apply Task: Gated on agreed verdict) ◄───────────────┘               │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Multi-Turn Deliberation State Machine (`deliberate.py`)

During pre-edit or escalation debates, the Architect and Oracle interact in ask mode. Consensus is governed deterministically without model self-scoring:

```text
                  ┌────────────────────────────────────────┐
                  │ Turn 0: Oracle Pre-Assessment          │
                  │ Input: [template] + [issue] + Context  │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │ Architect Turn (Streaming Ask Mode)    │
                  │ Must terminate with:                   │
                  │ 'PROPOSAL: <one-line summary>'         │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │ Oracle Evaluation Turn                 │
                  │ <critique>...</critique>               │
                  │ 'VERDICT: AGREE | OBJECT | REVISE'     │
                  └───────────────────┬────────────────────┘
                                      │
                          ┌───────────┴───────────┐
                          ▼                       ▼
                  [VERDICT: AGREE]        [VERDICT: OBJECT/REVISE]
                          │                       │
                          ▼                       ├──► Repeated Hash? ──► [DEADLOCK]
                  [Consensus: AGREED]             │
                          │                       └──► Turn < Max?    ──► [CONTINUE Loop]
                          ▼                                                   │
                  write_verdict()                                             └──► Turn == Max? ──► [EXHAUSTED]
                  (Actionable Gate)
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### YAML Path Resolution Rules (`resolve_template_path`)

The pipeline resolves template paths using a deterministic 9-candidate cascade in `run_workflow.py`. This ensures that local project overrides within `.aider_factory/` take strict precedence over packaged site-packages defaults.

```text
Input: path_val (e.g., "markdown/templates/implement.md")
  │
  ├── 1. Absolute Path Check (is abs path on disk? -> return)
  │
  ├── 2. Prefix Normalization
  │      Strip leading ".aider_factory/", "src/aider_factory/", etc.
  │      Compute rel_stripped, flat_filename
  │
  ├── 3. Workspace Priority Scan (base_proj)
  │      [1] base_proj / path_val
  │      [2] base_proj / .aider_factory / rel_stripped
  │      [3] base_proj / .aider_factory / markdown / rel_stripped
  │      [4] base_proj / .aider_factory / flat_filename
  │      [5] base_proj / .aider_factory / markdown / flat_filename
  │
  ├── 4. Package Fallback Scan (pkg_dir)
  │      [6] pkg_dir / rel_stripped
  │      [7] pkg_dir / markdown / rel_stripped
  │      [8] pkg_dir / flat_filename
  │      [9] pkg_dir / markdown / flat_filename
  │
  └── 5. Final Fallback: base_proj / path_val (forward-slash normalized)
```

#### Step-by-Step Resolution Algorithm

1. **Absolute Path Bypass**: If `path_val` is absolute and points to an existing file, it is returned immediately.
2. **Prefix Stripping**: Normalizes input strings by stripping leading `.aider_factory/`, `.aider_factory\`, `src/aider_factory/`, or `src\aider_factory\`. This allows users to copy-paste paths directly from any directory level without breaking resolution.
3. **Workspace Priority Scan (Checked First)**:
   - Candidate 1: `<project_directory>/<path_val>`
   - Candidate 2: `<project_directory>/.aider_factory/<rel_stripped>`
   - Candidate 3: `<project_directory>/.aider_factory/markdown/<rel_stripped>`
   - Candidate 4: `<project_directory>/.aider_factory/<flat_filename>`
   - Candidate 5: `<project_directory>/.aider_factory/markdown/<flat_filename>`
4. **Package Fallback Scan (Checked If Workspace Missing)**:
   - Candidate 6: `<site-packages>/aider_factory/<rel_stripped>`
   - Candidate 7: `<site-packages>/aider_factory/markdown/<rel_stripped>`
   - Candidate 8: `<site-packages>/aider_factory/<flat_filename>`
   - Candidate 9: `<site-packages>/aider_factory/markdown/<flat_filename>`
5. **Final Fallback**: If no file matches, returns `<project_directory>/<path_val>` with normalized forward slashes (`/`).

### Dynamic Plan Splicing (`_render_validate_template`)

To guarantee specification continuity between implementation and audit phases, `run_workflow.py` executes dynamic template splicing:

1. **Strategy Content Resolution**: Identifies the prior plan via `plans.validate_strategy_file`. If omitted, scans backward through the DAG for the most recently completed `.md` target file, defaulting to `.aider_factory/markdown/oracle_pre_plan/strategy_template.md`.
2. **Anchor Injection**: Reads the target validation template (`validate.md`).
3. **Regex Splice**: Executes non-greedy substitution using the regular expression:
   $$\text{Pattern: } \mathtt{r"\#\#\ PREVIOUS\ COMPLETED\ SYSTEM\ GOALS\ AND\ CONSTRAINTS.*?(?=\\n---\\n\#\#\ 2\\.|\\Z)"}$$
   Injects:
   ```markdown
   ## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS

   <strategy_content>
   ```
4. **Fallback Append**: If the anchor header is absent, appends the section to the end of the template.
5. **Ephemeral Persistence**: Emits the combined prompt to `.aider_factory/sessions/<session>/templates/<base_name>_validate_rendered.md`.

### File Manifest Extraction from Strategy Plans (`_extract_files_from_plan`)

When `sticky_phases.editable: true` or `sticky_phases.readonly: true` is configured, `run_workflow.py` parses file assignments directly from the strategy markdown artifact:

1. **Scoped Search Space**: Restricts search space to `## Scope Analysis` if present to avoid false positives in conversational prose.
2. **YAML Priority**: Extracts embedded ````yaml ... ```` blocks containing a `files:` mapping:
   ```yaml
   files:
     target_files: ["src/core.py"]
     extra_editable_files: ["src/utils.py"]
     test_files: ["tests/test_core.py"]
     context_files_job: ["README.md"]
     context_files_test: ["tests/conftest.py"]
   ```
3. **Markdown Header Fallback**: If no YAML block exists, regex matches Markdown list items under section headers:
   - `### Target Files?`
   - `### Extra Editable Files?`
   - `### Test Files?`
   - `### Context Files?`
4. **Path Sanitization & Test Separation**:
   - Strips quotes, backticks, trailing hyphens, and placeholder markers (`path/to/`, `<...>`, `TODO`).
   - Normalizes paths relative to `project_directory`.
   - Calls `is_test_path()`: if a file in `target_files` resides in `tests/`, `spec/`, or matches test filename conventions, it is redirected to `test_files` to preserve structural isolation.
   - Verifies physical file existence on disk (discarding phantom files).

### Mathematical Formulations

#### 1. Reciprocal Rank Fusion (Multi-Corpus RAG Retrieval)
When fusing chunk lists from disparate tables (code vs. documentation), relevance ranks are merged using Reciprocal Rank Fusion ($k=60$):
$$\text{RRF\_Score}(d) = \sum_{m \in M} \frac{1}{60 + \text{rank}_m(d)}$$
where $M$ is the set of queried tables and $\text{rank}_m(d) \in [0, N-1]$ is the zero-indexed ranking of chunk $d$. Secondary sort keys `(source_file, text_prefix)` ensure deterministic rank stabilization.

#### 2. Character Error Rate (OCR Validation)
Normalized Edit Distance evaluates OCR fidelity against embedded PDF text layers:
$$\text{CER}(R, H) = \frac{\text{Levenshtein}(R_{\text{norm}}, H_{\text{norm}})}{|R_{\text{norm}}|}$$
where $R_{\text{norm}}$ and $H_{\text{norm}}$ are reference and hypothesis strings stripped of all non-alphanumeric characters and converted to lowercase. If $|R_{\text{norm}}| = 0$, $\text{CER} = 0.0$.

#### 3. MiniCheck Entailment Pooling
Sentence-level grounding verification evaluates whether each sentence $s_i$ of claim $C$ is entailed by retrieved context $D$:
$$P_{\text{claim}} = \min_{s_i \in \text{sentences}(C)} P_{\text{MiniCheck}}(\text{supported} \mid D, s_i)$$
The conservative minimum operator guarantees that any single ungrounded sentence flags the entire claim passage.

#### 4. Ellipsis-Stitch Verbatim Continuity Constraint
Ellipsis-spliced quotes are deterministically stitched back into verbatim source spans only if the total inter-fragment gap satisfies:
$$\text{gap} = (e_{\text{last}} - s_{\text{first}}) - \sum_{i=1}^n (e_i - s_i) \le 200\text{ characters}$$
where $[s_i, e_i]$ represents the character span of fragment $i$ in normalized source text.

#### 5. Context Window Utilization & Headroom Safety
Total active context must satisfy:
$$U_{\text{active}} = \frac{T_{\text{prefix}} + T_{\text{repomap}} + T_{\text{retrieval}} + T_{\text{history}}}{C_{\text{window}}} \le 0.70$$

### Contract Delimiters & Parsing Mechanics

| Token / Delimiter | Source Module | Regular Expression Definition | Contractual Function |
| :--- | :--- | :--- | :--- |
| `PROPOSAL:` | `deliberate.py` | `(?im)^[\s*>#*_`\-]*PROPOSAL[\s*_`]*[:\-]?[\s*_`]*(.+)$` | Captures Architect's resolution line for hash stability. |
| `VERDICT:` | `deliberate.py` | `(?im)^[\s*>#*_`\-]*VERDICT[\s*_`]*[:\-]?[\s*_`\[]*(AGREE\|OBJECT\|REVISE\|DISAGREE\|REJECT)\b` | Extracts Oracle consensus decision. |
| `<critique>` | `oracle_agent.py` | `(?is)<critique>(.*?)</critique>` | Isolates Oracle reasoning; stripped during verdict parsing. |
| `Tokens Anchor` | `apply_agent.py` | `(?m)^>\s*Tokens:\s*[\d\.]+[kKMG]?\s*sent,\s*[\d\.]+[kKMG]?\s*received.*$` | Delimits distinct conversational turns in `.aider.chat.history.md`. |
| `Slash Commands` | `apply_agent.py` | `^/(add\|run\|read\|drop\|model\|clear\|exit\|undo\|diff\|load\|help)\b` | Identifies and strips interactive Aider commands from extracted specs. |

---

## 4. Exhaustive CLI & Parameter Reference

| Command / Entrypoint | Key Flags & Arguments | Associated Template / Mechanism | Exit Codes & Behaviors |
| :--- | :--- | :--- | :--- |
| `aider-oracle "<query>"` | Positional prompt | `SYSTEM_PROMPT` in `oracle_agent.py` | `0`: Success, outputs response to stdout.<br>`1`: Model failure or missing configuration. |
| `aider-oracle --file <path>` | `--file <path>` | Injects raw file contents into query payload | Reads `<path>`, pairs with inline query, and queries LanceDB context. |
| `aider-oracle --debate [code\|review]` | `--loops <N>`, `--rounds <N>`, `--persist`, `--oracle-persona <p>`, `--architect-persona <p>`, `--oracle-file <f>`, `--architect-file <f>` | Code mode: `analyze_bugs.md`<br>Review mode: `deliberation_evidence_template.md` | Runs multi-turn ask-mode arbitration between Architect and Oracle.<br>`0`: Consensus reached (`AGREE`) or loop exhausted. |
| `aider-apply <files...>` | `--spec <path>`, `--turns <N>`, `--model <m>`, `--stream`, `--no-diff` | Active chat history parsed via `apply_agent.py` or `<path>` | `0`: Surgical edits applied cleanly.<br>`1`: Aider execution failure or invalid spec. |
| `aider-helper ask "<prompt>"` | `--file <path>`, `--context <files>`, `--repo-map`, `--master`, `--expert` | `PERSONA_PROMPT` in `bootstrap.py` | Queries helper agent with injected configuration and reference schemas. |
| `aider-helper bootstrap` | Positional target dir | `default_configs/env.yml` | Scaffolds workspace, detects test runners, and writes `.env_<repo>.yml`. |
| `aider-validate --file <f>` | `--source <s>`, `--report <r>`, `--claims-only`, `--autofix`, `--finalize-unsupported` | Deterministic verification or `_ENTAIL_PROMPT` | `0`: All claims grounded or autofixed.<br>`1`: Ungrounded claims detected, writes `<report>`. |
| `aider-factory [config.yml]` | `-s, --session <name>` | Master DAG pipeline execution via `run_workflow.py` | `0`: All phase tasks completed successfully.<br>`1`: Task failure encountered. |

---

## 5. Configuration Schema & YAML Knobs

The assignment, behavior, and lifecycle splicing of templates is declared in `.env.yml`.

### Complete Pipeline Phase Schema

```yaml
phases:
  - name: "Core Feature Engineering"
    enabled: true

    # 1. Sticky Phase Context Discovery
    sticky_phases:
      editable: true               # Auto-populates files.target_files from strategy plan
      readonly: true               # Auto-populates context_files_job from strategy plan

    # 2. Template Declarations
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

    # 3. Pre-Edit Deliberation Configuration
    oracle:
      template: ".aider_factory/markdown/internal/analyze_bugs.md"
      start_job: true              # True: runs programmatic Oracle synthesis; False: skipped
      full_document: true          # Injects entire collection table instead of top-k search
      pre_edit_debate:
        enabled: true
        insert_debate: [true, false, false] # Injects debate before Job 1, Job 2, Job 3
        loops: 3                   # Max loops per round
        rounds: 1                  # Outer debate rounds
        pass_history: true         # Retains multi-turn chat history across rounds
        persist: false             # If true, continues exploring after provisional agreement
        oracle_persona: ".aider_factory/markdown/personas/critic.md"
        architect_persona: ".aider_factory/markdown/personas/planner.md"
        oracle_file: ".aider_factory/markdown/instructions/oracle_rules.md"
        architect_file: ".aider_factory/markdown/instructions/architect_rules.md"
        job_debate_template: ".aider_factory/markdown/templates/job_debate.md"
        job_debate_collection: "knowledge"

    # 4. Post-Execution Escalation Debate
    escalation_debate:
      loops: 3                     # Debate turns on test suite failure
      rounds: 1
      pass_history: true
      persist: false
      oracle_persona: ""
      architect_persona: ""
      oracle_file: ""
      architect_file: ""

    # 5. Deterministic Grounding & Verification
    validation:
      enabled: true                # Activates autofix ellipsis repair
      post_validate: true          # Activates iterative healing loop
      validation_tag: "evidence"   # Target anchor tag (e.g., [evidence])
      region_threshold: 0.60       # LanceDB cosine similarity floor
      region_margin: 2             # Line expansion margin around claim paragraph
      region_paragraphs: 0         # Additional paragraph context expansion
      region_top_k: 5              # Candidate RAG chunks retrieved for claim audit
      validation_loops: 3          # Max repair iterations
      redo_oracle_job: false       # Re-runs synthesis if output artifact already exists
      verify_all_claims: false     # Evaluates all claims even if verbatim matched
      entail_threshold: 0.50       # MiniCheck support probability threshold
      claims_only: false           # Verifies raw paragraphs without [evidence] anchors
```

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

### Operational Edge Cases & Recovery Procedures

| Failure Scenario | Root Cause & Diagnostic Signature | Automated Engine Behavior | Operator Recovery Procedure |
| :--- | :--- | :--- | :--- |
| **Missing Local Template** | Custom template path specified in YAML does not exist in workspace. | `resolve_template_path` falls back to site-packages bundled copy. Logs info message. | If the file was intentionally customized, ensure it is committed under `.aider_factory/markdown/`. |
| **Parsing Contract Violation** | User edited `analyze_bugs.md` and altered `PROPOSAL:`. | `deliberate.py` captures `(no PROPOSAL line)`. Proposal hash defaults to full turn text. | Revert Tier 2 infrastructure templates to original repository defaults. |
| **Missing Splicing Header** | Custom `validate.md` removed `## PREVIOUS COMPLETED SYSTEM GOALS`. | `_render_validate_template` detects missing anchor and safely appends goals to bottom. | Restore the exact header `## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS` to anchor goals inline. |
| **Deadlock in Deliberation** | Architect repeats identical proposal hash and Oracle objects twice. | `consensus_state()` detects matching hash and flags `deadlock`. Deliberation terminates. | Review failing test logs or LanceDB evidence. Refine template constraints or persona instructions. |
| **Token Budget Saturation** | Prompt payload exceeds $80\%$ of model context window. | Aider truncates older chat history or LiteLLM returns `context_length_exceeded`. | Set `map_tokens: 0` in toggles, decrease `chunk_size_chars`, or filter `context_files_job`. |
| **MiniCheck Server Timeout** | Grounding server (`minicheck_server.py`) unreachable or unresponsive. | `validator._entail` logs warning and falls back to LanceDB cosine similarity threshold. | Verify systemd unit: `systemctl --user status minicheck` or restart `uv run minicheck_server.py`. |
