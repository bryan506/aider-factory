# AI Factory Engineering Backlog & Future Tasks

## 1. Instruction-Aware Reranker Prompt Customization (`ranking_prompt`)

### Status: Backlog / Future Enhancement
### Target Components: `oracle_agent.py`, `validator.py`, `.env.yml` schema

---

### Technical Context & Background
Instruction-tuned generative rerankers (such as `Qwen/Qwen3-Reranker-4B` and `Qwen/Qwen3-Reranker-8B`) support domain-specific task framing using the official prompt template:
```text
<Instruct>: {instruction}
<Query>: {query}
```

While standard plain queries achieve high discrimination (>0.99 relevance score) on properly converted GGUF files with `cls.output.weight`, specialized domains (e.g. biomedical citation matching, statutory legal analysis, complex financial covenants) can benefit from configurable instruction prefixes.

---

### Proposed YAML Schema Extension

```yaml
phases:
  - name: "Domain Analysis Phase"
    models:
      ranking_agent: "qwen3-reranker-4b-gpu:LATEST"
    rag:
      ranking_prompt: "Given a financial research query, retrieve relevant quantitative models and formulas that answer the question"
```

---

### Proposed Environment Variable & Execution Path
* `ORACLE_RANKING_INSTRUCT`: Default string prefix applied to queries when using instruction-aware rerankers.
* In `oracle_agent.py` and `validator.py`: If `ranking_prompt` is provided in the configuration or via `ORACLE_RANKING_INSTRUCT`, format the query string before sending the payload to `/v1/rerank` or the local CrossEncoder backend.

---

## 2. Temporal Reasoning, Point-in-Time Gating & Chronological RAG Ranking

### Status: Backlog / Future Architecture
### Target Components: `rag_manager.py`, `oracle_agent.py`, `validator.py`, `.env.yml` schema

---

### Technical Context & Background
Standard vector retrieval operates as a "bag-of-chunks" where passages are ordered purely by semantic similarity, discarding chronology. In high-stakes domains (quantitative finance, clinical records, and legal contracts), this causes **temporal scrambling** (e.g., lookahead bias in backtests, inverted pre-op vs. post-op causality, or citing superseded contract clauses).

Adding temporal awareness allows the Oracle to filter by historical horizons, apply time-decay weighting, and project retrieved context in causal order ($T_1 \to T_2 \to T_3$).

---

### Proposed Schema Extension (`RAGChunk` in `rag_manager.py`)

Extend `RAGChunk` to store extracted timestamps in LanceDB:

```python
class RAGChunk(LanceModel):
    text: str
    vector: Vector(_dim)
    source_file: str
    source_type: str
    language: str = ""
    symbol: str = ""
    line_start: int = 0
    line_end: int = 0
    timestamp: float = 0.0     # Unix epoch timestamp
    date_str: str = ""         # ISO-8601 string (e.g., "2024-05-12T14:30:00Z")
```

**Timestamp Extraction Waterfall:**
1. **Docling / Markdown Frontmatter:** Document publication date or ISO metadata header.
2. **Git Commit History:** `git log -1 --format="%ct" -- <file>`.
3. **Filesystem `mtime`:** `os.path.getmtime(file_path)` fallback.

---

### Proposed YAML Configuration Extension

```yaml
phases:
  - name: "Temporal Analysis Phase"
    rag:
      temporal:
        mode: "chronological"          # "none" | "chronological" | "time_decay" | "point_in_time"
        as_of_date: "2024-01-01"       # Point-in-Time (PIT) hard filter for quant backtests
        time_decay_half_life_days: 180 # Exponential decay half-life
```

---

### Proposed CLI Flags (`aider-oracle`)
* `--sort-time`: Re-orders final top-$K$ reranked chunks in ascending chronological order before prompt assembly.
* `--as-of <YYYY-MM-DD>`: Pushes a LanceDB Arrow filter (`where("timestamp <= ...")`) to eliminate lookahead bias.
* `--time-decay <half_life_days>`: Modulates relevance scores via $S_{final} = S_{semantic} \cdot e^{-\lambda \Delta t}$.

---

### Execution Pipeline in `oracle_agent.py`
1. **Stage 1 (Filter):** If `--as-of` is defined, apply native Arrow predicate to LanceDB KNN query.
2. **Stage 2 (Retrieve & Rerank):** Retrieve `recall_k` candidates and rerank using Jina v3.5 Listwise Cross-Encoder.
3. **Stage 3 (Decay, Optional):** Re-score candidates if `time_decay` is configured.
4. **Stage 4 (Chronological Context Projection):** Re-sort the final top-$K$ chunks by `timestamp` ascending ($T_1 \le T_2 \le \dots \le T_K$) and inject ISO timestamps into the `<chunk>` XML tags so LLM attention naturally follows temporal causality.
