# Local Inference Setup & Bare-Metal Hardware Acceleration Manual

## 1. Executive Overview & Foundational Invariants

### 1.1 Core Architectural Purpose

The AI Factory local inference layer provides sovereign, zero-cloud-leak, bare-metal hardware acceleration for autonomous multi-agent software engineering pipelines. By compiling and orchestrating optimized C/C++ inference engines (`llama.cpp` and `ollama`), the pipeline runs reasoning, surgical code diffing, optical character recognition (OCR), vector embedding, cross-encoder reranking, and natural language inference (NLI) entailment entirely on local GPU and APU silicon.

### 1.2 System Invariants & Non-Negotiable Guarantees

1. **Complete Air-Gapped Sovereignty**: All reasoning, code generation, vision extraction, and embeddings execute against local network interfaces (`127.0.0.1` or controlled LAN subnets). Zero prompt tokens, source files, or vector embeddings leak to third-party cloud APIs.
2. **Daemon Isolation by Workload Class**: Compute workloads are partitioned into specialized daemons to eliminate memory fragmentation and model thrashing:
   - **Primary Reasoning & Pair-Programming Router (Port 8081)**: Serves large Architect reasoning models, multi-turn deliberation agents, and fast speculative draft models using Multi-Token Prediction (MTP).
   - **Vision, Embedding & Reranking Endpoint (Port 8080)**: Serves high-throughput parallel Vision OCR (GLM-OCR), dense vector embeddings (Qwen3-Embedding), and cross-encoder reranking (Qwen3-Reranker) with dynamic model eviction (`--models-max 1`).
   - **Background Editor & Linting Service (Port 11434)**: Serves Ollama for rapid syntax repair, automated commit messaging, and lightweight code modifications.
   - **Grounding Verification Server (Port 8090)**: Serves standalone MiniCheck NLI entailment scoring via `minicheck_server.py`.
3. **Kernel Memory Lock & OOM Protection**: All systemd services configure `LimitMEMLOCK=infinity`, `LimitNOFILE=1048576`, and `OOMScoreAdjust=-1000`. Inference processes are permanently immune to Linux Out-Of-Memory (OOM) killer eviction during heavy compilation or batch test suite passes.
4. **Strict Attention Topology Isolation**: Flash Attention is globally disabled on the Vision/OCR daemon (`llama-vision.service`) to prevent encoder NaN tensor corruption, while explicitly enabled for dense transformer architectures via model-level configuration.

### 1.3 Multi-Daemon Workload & Port Allocation Topology

| Daemon Service | Target Port | Workload Profile | Primary Models | Memory & Acceleration Profile |
| :--- | :--- | :--- | :--- | :--- |
| `llama-pair-router.service` | `8081` | Architect, Oracle, Escalation Debate | Qwen3.5-122B, Qwen3.6-27B | Unified DRAM / VRAM, MTP Draft Speculation, Parallel = 3 |
| `llama-vision.service` | `8080` | Document OCR, Vector Embedding, Reranking | GLM-OCR, Qwen3-Embedding-8B, Qwen3-Reranker-4B | Dynamic Eviction (`--models-max 1`), Parallel OCR = 8, F16 KV Cache |
| `ollama.service` | `11434` | Surgical Edits, Weak Model, Test Iteration | Qwen2.5-Coder-1.5B/7B | VRAM Persistent (`KEEP_ALIVE=-1`), Parallel = 4 |
| `minicheck_server.py` | `8090` | NLI Claim Grounding Entailment | MiniCheck-Flan-T5-Large | CPU/Accelerate, PyTorch NLI Scoring |

---

## 2. System Topology & Lifecycle Flowcharts

### 2.1 Multi-Daemon Pipeline Topology

```
+---------------------------------------------------------------------------------------------------+
|                                      AI Factory Pipeline Clients                                   |
|   run_workflow.py   |   orchestrate.py   |   oracle_agent.py   |   rag_manager.py   |  validator.py   |
+----------+-------------------+--------------------+-------------------+--------------------+------+
           |                   |                    |                   |                    |
           | (Architect/Ask)   | (Editor Edits)     | (RAG Context)     | (OCR & Embed)      | (Entailment)
           v                   v                    v                   v                    v
+--------------------+ +--------------------+ +--------------------+ +--------------------+ +--------------------+
| Port 8081 (Router) | | Port 11434 (Ollama)| | Port 8081 (Oracle) | | Port 8080 (Vision) | | Port 8090 (Verify) |
| llama-server       | | ollama serve       | | llama-server       | | llama-server       | | minicheck_server   |
| MTP Speculative    | | Background Diff    | | Context Inference  | | GLM-OCR / Embed    | | T5-Large NLI       |
+----------+---------+ +---------+----------+ +---------+----------+ +---------+----------+ +---------+----------+
           |                     |                      |                      |                      |
           +---------------------+----------------------+----------------------+----------------------+
                                                        |
                                                        v
+---------------------------------------------------------------------------------------------------+
|                                  Hardware & Kernel Execution Layer                                 |
|      AMD ROCm / HIP (MI300 / Strix Halo APU)             |          NVIDIA CUDA (RTX / A100)      |
|      - Unified Memory Zero-Copy DRAM Interface           |          - Dedicated GDDR6X / HBM VRAM     |
|      - ROCWMMA Matrix Acceleration                       |          - FlashAttention-2 Tensor Cores   |
+---------------------------------------------------------------------------------------------------+
```

### 2.2 Model Lifecycle & Context Slot Eviction State Machine

```
[Request Ingested]
        |
        v
[Inspect Target Model Name]
        |
        +---> Model Loaded in Active Slot?
                    |
          +---------+---------+
          | YES               | NO
          v                   v
   [Acquire Slot Lock]    [Active Model Count >= --models-max?]
          |                   |
          |         +---------+---------+
          |         | YES               | NO
          |         v                   v
          |   [Evict Idle Model]  [Allocate VRAM/DRAM]
          |   [Release GPU Pages]         |
          |         |                     |
          |         +--------->+<---------+
          |                    |
          |                    v
          |           [Load Weights from Disk]
          |           [Initialize KV Cache ($S \times C_{slot}$)]
          |                    |
          +------------------->+
                               |
                               v
                     [Token Ingestion / Prefill]
                               |
                               +---> Workload Class:
                                     |-- Vision: Encode Image Features (MMProj) -> Generate Text
                                     |-- Embed: Pool Hidden States (Last Token) -> Return Vector
                                     |-- Rerank: Score Query-Doc Pairs (Rank Pooling) -> Return Logits
                                     +-- Text: Speculative Draft Verification (MTP) -> Emit Stream
                               |
                               v
                     [Release Slot Lock / Retain KV State]
```

### 2.3 Slot Concurrency & Cross-Session Isolation Mechanics

`llama-server` manages concurrent inference requests by allocating distinct context slots inside the global context window. When initialized with context size $C_{\text{total}}$ and parallel slot count $S$, each slot is allocated:

$$C_{\text{slot}} = \left\lfloor \frac{C_{\text{total}}}{S} \right\rfloor$$

To prevent context contamination across distinct agent turns (e.g. Architect planning vs. Oracle RAG verification), `--slot-prompt-similarity 0.0` is enforced on the Vision and Router daemons. This disables prefix matching slot reclamation, guaranteeing that each request evaluates with pure, deterministic isolation.

---

## 3. Technical Mechanics & Deep-Dive Logic

### 3.1 Kernel Acceleration & Toolchain Compilation

#### 3.1.1 AMD ROCm / HIP Toolchain (Primary Unified Memory Architecture)

AMD Unified Memory architectures (e.g., AMD Strix Halo APU with 128 GB shared LPDDR5X-8533 or Instinct MI300) allow the CPU and GPU to share a unified physical address space. Host-to-device memory copy overhead is eliminated through zero-copy unified memory allocations.

Install the ROCm kernel drivers and development libraries:

```bash
sudo apt update
sudo apt install -y "linux-headers-$(uname -r)" "linux-modules-extra-$(uname -r)"
sudo apt install -y rocm-hip-sdk rocblas-dev rocm-device-libs build-essential cmake git
sudo usermod -aG render,video $USER
```

Verify hardware device visibility and kernel driver nodes:

```bash
rocminfo | grep -E "Name:|Marketing Name:"
ls -l /dev/kfd /dev/dri/renderD*
```

Compile `llama.cpp` using the native ROCm Clang toolchain and hardware-accelerated matrix multiplication (`ROCWMMA`):

```bash
mkdir -p ~/Programs
cd ~/Programs
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp

HIPCXX="$(hipconfig -l)/clang" cmake -B build \
    -DGGML_HIP=ON \
    -DGGML_HIP_ROCWMMA_FATTN=ON \
    -DCMAKE_BUILD_TYPE=Release

cmake --build build --config Release -j $(nproc)
```

#### 3.1.2 NVIDIA CUDA Toolchain (Auxiliary Architecture)

Install proprietary drivers and CUDA development headers:

```bash
sudo apt update
sudo apt install -y build-essential cmake git nvidia-driver-550 nvidia-cuda-toolkit
```

Compile `llama.cpp` with native CUDA support:

```bash
mkdir -p ~/Programs
cd ~/Programs
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp

cmake -B build \
    -DGGML_CUDA=ON \
    -DGGML_CUDA_F16=ON \
    -DCMAKE_BUILD_TYPE=Release

cmake --build build --config Release -j $(nproc)
```

The compiled binaries will reside in `build/bin/` (`llama-server`, `llama-quantize`, `llama-merge-gguf`).

### 3.2 Model Preparation & Conversion Mechanics

All operational weights are stored in `~/Programs/gguf/` organized alongside `models.ini`.

#### 3.2.1 Merging Split GGUF Shards

Large language models distributed in multi-part shards (e.g., `model-00001-of-00003.gguf`) must be reconstituted into a contiguous binary using `llama-merge-gguf`:

```bash
mkdir -p ~/Programs/gguf
cd ~/Programs/gguf

# Merge split shards into a unified GGUF
~/Programs/llama.cpp/build/bin/llama-merge-gguf \
    qwen3.6-27b-90k-00001-of-00002.gguf \
    qwen3.6-27b-90k-00002-of-00002.gguf \
    qwen3.6-27b-90k-merged.gguf

# Remove individual shards to reclaim disk space
rm qwen3.6-27b-90k-00001-of-00002.gguf qwen3.6-27b-90k-00002-of-00002.gguf
```

#### 3.2.2 Converting Cross-Encoder Rerankers (Qwen3-Reranker-4B)

Reranker models require preservation of the sequence classification head (`cls.output.weight`) and explicit registration of `pooling_type = RANK` metadata. Direct conversion from official Hugging Face safetensors ensures full precision:

```bash
# 1. Download official Hugging Face safetensors
uv run --with huggingface_hub python -c \
  "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-Reranker-4B', local_dir='/tmp/Qwen3-Reranker-4B-src')"

# 2. Convert safetensors to F16 GGUF with sequence classification head preserved
uv run --with gguf --with torch --with safetensors --with sentencepiece --with protobuf --with transformers \
  python ~/Programs/llama.cpp/convert_hf_to_gguf.py \
    --outtype f16 \
    --outfile /tmp/Qwen3-Reranker-4B-f16.gguf \
    /tmp/Qwen3-Reranker-4B-src

# 3. Quantize to balanced Q8_0 precision
~/Programs/llama.cpp/build/bin/llama-quantize \
    /tmp/Qwen3-Reranker-4B-f16.gguf \
    ~/Programs/gguf/Qwen3-Reranker-4B_Q8_0.gguf \
    Q8_0

# 4. Clean temporary build artifacts
rm -rf /tmp/Qwen3-Reranker-4B-src /tmp/Qwen3-Reranker-4B-f16.gguf
```

### 3.3 Speculative Decoding & Multi-Token Prediction (MTP) Mechanics

On large parameter architectures (e.g. Qwen 27B / 122B), autoregressive token generation is strictly memory-bandwidth bound. Multi-Token Prediction (MTP) executes lightweight speculative draft passes in parallel with verification forward passes.

#### Mathematical Speedup Formulation

Let $\tau_{\text{draft}}$ represent the forward pass latency of the draft speculation head, $\tau_{\text{verify}}$ represent the forward pass latency of the target verification model, and $\gamma \in [1, K]$ represent the average accepted token length per draft cycle:

$$\text{Latency}_{\text{token}} = \frac{\tau_{\text{draft}} \cdot K + \tau_{\text{verify}}}{\gamma}$$

The theoretical execution speedup $S$ relative to standard autoregressive generation ($\tau_{\text{verify}}$ per token) is:

$$S = \frac{\gamma \cdot \tau_{\text{verify}}}{\tau_{\text{draft}} \cdot K + \tau_{\text{verify}}}$$

In `llama-server`, setting `--spec-type draft-mtp` and `--spec-draft-n-max 3` enables internal MTP heads to emit 3 candidate tokens simultaneously, yielding a $1.8\times - 2.4\times$ real-world decode acceleration on memory-constrained buses.

### 3.4 Parallel OCR Throughput & Memory Bandwidth Saturation

During document RAG ingestion (`rag_manager.py`), multi-page PDF documents are rasterized into high-resolution images and ingested by Vision-Language Models (GLM-OCR).

#### Memory Bandwidth Saturation Model

The aggregate decoding throughput $T(S)$ across $S$ parallel slots is constrained by the physical memory bandwidth $\text{BW}_{\text{DRAM}}$ versus model weights $M_{\text{weights}}$ and KV cache footprint:

$$T(S) = \min\left( S \cdot \frac{F_{\text{compute}}}{D_{\text{model}} \cdot N_{\text{tokens}}}, \frac{\text{BW}_{\text{DRAM}}}{M_{\text{weights}} + S \cdot M_{\text{KV\_slot}}} \right)$$

Total VRAM allocation for $S$ slots with context length $C_{\text{slot}}$, layer count $L$, and head dimension $D_{\text{head}}$ in F16 precision is:

$$M_{\text{total}} = M_{\text{weights}} + S \cdot \left( 2 \cdot L \cdot D_{\text{head}} \cdot C_{\text{slot}} \cdot 2 \text{ bytes} \right)$$

#### Empirical Slot Scaling Benchmark (AMD Strix Halo APU, 128 GB LPDDR5X-8533, 40 CUs)

| Slots (`parallel`) | Per-Slot Speed | Aggregate Speed | Wall-Clock (47-Page PDF) | Memory Saturation Status |
| :--- | :--- | :--- | :--- | :--- |
| `1` | $80.2\text{ tok/s}$ | $80.2\text{ tok/s}$ | $20\text{ min } 15\text{ s}$ | Severely under-utilized compute ($< 15\%$ CU load) |
| `4` | $79.8\text{ tok/s}$ | $319.2\text{ tok/s}$ | $6\text{ min } 45\text{ s}$ | Linear compute scaling |
| `8` (Optimal) | $78.5\text{ tok/s}$ | $628.0\text{ tok/s}$ | $5\text{ min } 02\text{ s}$ | Peak bandwidth utilization ($~230\text{ GB/s}$) |
| `16` | $14.1\text{ tok/s}$ | $225.6\text{ tok/s}$ | $12\text{ min } 30\text{ s}$ | Bus thrashing / memory bandwidth starvation |

**Architectural Rule**: Configure `parallel = 8` for vision models. Flash Attention must be explicitly set to `flash-attn = off` for vision encoders, as cross-attention projection matrices in GLM-OCR are corrupted by fused attention kernels.

### 3.5 Embedding & Reranker Pooling Mechanics

- **Dense Embedding (Qwen3-Embedding-8B)**: Dense retrieval requires mean or final token pooling. Qwen3-Embedding specifically trains the final sequence token (`[EOS]`) to represent the semantic sentence embedding. Configure `pooling = last` and `embeddings = on`.
- **Cross-Encoder Reranking (Qwen3-Reranker-4B)**: Cross-encoders ingest a concatenated string (`Query: {q} Document: {d}`) and output a scalar relevance logit. Configure `pooling = rank` and `reranking = true`.

---

## 4. Exhaustive CLI & Parameter Reference

### 4.1 `llama-server` CLI Flag Reference

| CLI Argument | Type | Default | Operational Impact | Recommended Value |
| :--- | :--- | :--- | :--- | :--- |
| `--host` | `string` | `127.0.0.1` | Network interface to bind HTTP listener. | `0.0.0.0` (Permits LAN access) |
| `--port` | `integer` | `8080` | TCP port for REST and OpenAI-compatible API. | `8081` (Router) / `8080` (Vision) |
| `--models-dir` | `path` | `None` | Directory containing dynamic `models.ini` or GGUF files. | `/home/$USER/.config/llama-server` |
| `--models-preset` | `path` | `None` | Path to explicit INI model preset registry. | `/home/$USER/Programs/gguf/models.ini` |
| `--models-max` | `integer` | `1` | Max model weight instances retained simultaneously in memory. | `3` (Router) / `1` (Vision) |
| `--parallel`, `-np` | `integer` | `1` | Number of simultaneous request slots supported per model. | `3` (Router) / `8` (Vision) |
| `--ctx-size`, `-c` | `integer` | `4096` | Total context memory allocation across all slots. | `32768` (Router) / `65536` (Vision) |
| `--batch-size`, `-b` | `integer` | `2048` | Prompt evaluation (prefill) batch size in tokens. | `2048` (Text) / `16384` (Embedding) |
| `--ubatch-size`, `-ub` | `integer` | `512` | Physical micro-batch size evaluated per kernel dispatch. | `512` (Text) / `8192` (Embedding) |
| `--n-gpu-layers`, `-ngl`| `integer` | `0` | Number of transformer layers offloaded to GPU/VRAM. | `999` (Complete offload) |
| `--spec-type` | `string` | `none` | Speculative decoding execution type (`none`, `draft-mtp`). | `draft-mtp` (Router only) |
| `--spec-draft-n-max` | `integer` | `0` | Max candidate tokens generated per MTP draft step. | `3` (Router only) |
| `--flash-attn`, `-fa` | `flag` | `disabled`| Enable Flash Attention kernel optimization. | Active for Router; OFF for Vision |
| `--no-mmap` | `flag` | `disabled`| Force loading model entirely into RAM/VRAM without disk mmap. | Active for Vision / Embedding |
| `--slot-prompt-similarity` | `float`| `0.5` | Threshold for KV-cache slot prompt prefix matching reuse. | `0.0` (Disables prefix theft) |

### 4.2 REST API Endpoint Matrix

| HTTP Method | Route | Subsystem Consumer | Payload Signature | Response Format |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/v1/chat/completions` | `orchestrate.py`, `oracle_agent.py` | `{"model": str, "messages": list, "temperature": float}` | OpenAI Chat Completion JSON |
| `POST` | `/embeddings` | `rag_manager.py`, `oracle_agent.py` | `{"model": str, "input": list[str]}` | OpenAI Embedding Vector JSON |
| `POST` | `/v1/rerank` | `oracle_agent.py` (`_rerank_chunks`) | `{"model": str, "query": str, "documents": list[str]}` | Ranked documents array with scores |
| `POST` | `/rerank` | Fallback route for `/v1/rerank` | `{"model": str, "query": str, "documents": list[str]}` | Ranked documents array with scores |
| `POST` | `/load` | CLI Model Manager | `{"model": "qwen3.6-27b-90k:latest"}` | `{"status": "ok"}` |
| `GET` | `/slots` | Health Monitor | `None` | Array of slot status and context state |
| `GET` | `/health` | Systemd Watchdog | `None` | `{"status": "ok"}` |

### 4.3 Ollama Runtime Environment Variables

| Variable Name | Type | Value | Architectural Impact |
| :--- | :--- | :--- | :--- |
| `OLLAMA_HOST` | `string` | `0.0.0.0:11434` | Binds Ollama HTTP engine across all available network interfaces. |
| `OLLAMA_KEEP_ALIVE` | `string` | `-1` | Prevents unloading model weights during prolonged pipeline unit test passes. |
| `OLLAMA_FLASH_ATTENTION` | `integer`| `1` | Enables hardware flash attention to minimize KV cache footprint. |
| `OLLAMA_NUM_PARALLEL` | `integer`| `4` | Allocates 4 concurrent worker slots for background surgical edits. |

---

## 5. Configuration Schema & YAML Knobs

### 5.1 The `models.ini` Local Model Registry

Create `/home/$USER/Programs/gguf/models.ini`:

```ini
# /home/$USER/Programs/gguf/models.ini
# Model Registry Specification for Multi-Daemon AI Factory Pipeline

[qwen3.6-27b-90k:latest]
model = /home/$USER/Programs/gguf/qwen3.6-27b-90k-merged.gguf
ctx-size = 32768
n-gpu-layers = 999
parallel = 3
flash-attn = on
temp = 0.7

[qwen3.5-122b-a10b-90k:latest]
model = /home/$USER/Programs/gguf/qwen3.5-122b-a10b-90k-Q4_K_M.gguf
ctx-size = 32768
n-gpu-layers = 999
parallel = 1
flash-attn = on
temp = 0.6

[glm-ocr-f16:LATEST]
model = /home/$USER/Programs/gguf/GLM-OCR-f16.gguf
mmproj = /home/$USER/Programs/gguf/mmproj-GLM-OCR-Q8_0.gguf
ctx-size = 65536
parallel = 8
n-gpu-layers = 999
temp = 0.1
flash-attn = off
cache-type-k = f16
cache-type-v = f16
mmap = false

[qwen3-embedding-8b-8k:LATEST]
model = /home/$USER/Programs/gguf/Qwen3-Embedding-8B.i1-Q6_K.gguf
embeddings = on
pooling = last
ctx-size = 16384
batch-size = 16384
ubatch-size = 16384
n-gpu-layers = 999
parallel = 1
flash-attn = on
cache-type-k = f16
cache-type-v = f16
mmap = false

[qwen3-reranker-4b:latest]
model = /home/$USER/Programs/gguf/Qwen3-Reranker-4B_Q8_0.gguf
reranking = true
embedding = true
pooling = rank
ctx-size = 16384
batch-size = 16384
ubatch-size = 8192
n-gpu-layers = 999
flash-attn = on
cache-type-k = q8_0
cache-type-v = q8_0
slot-prompt-similarity = 0.0
mmap = false
```

When `llama-server` is running, models can be loaded on demand via REST API:

```bash
curl -X POST http://localhost:8081/load \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen3.6-27b-90k:latest"}'
```

### 5.2 Systemd Daemon Service Units

#### Service 1: `llama-pair-router.service` (Port 8081)

Save as `/etc/systemd/system/llama-pair-router.service`:

```ini
[Unit]
Description=Llama.cpp Primary Router — Architect + Oracle Deliberation Engine
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME

# Kernel Resource Limits & Protection
LimitMEMLOCK=infinity
LimitNOFILE=1048576
OOMScoreAdjust=-1000
# Environment="HSA_OVERRIDE_GFX_VERSION=11.0.0" # Enable for AMD RDNA3 / gfx1100 APUs

ExecStart=/home/YOUR_USERNAME/Programs/llama.cpp/build/bin/llama-server \
    --host 0.0.0.0 \
    --port 8081 \
    --models-preset /home/YOUR_USERNAME/Programs/gguf/models.ini \
    --models-max 3 \
    --parallel 3 \
    --ctx-size 32768 \
    --spec-type draft-mtp \
    --spec-draft-n-max 3 \
    --flash-attn

Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

#### Service 2: `llama-vision.service` (Port 8080)

Save as `/etc/systemd/system/llama-vision.service`:

```ini
[Unit]
Description=Llama.cpp Vision OCR, Vector Embedding & Reranker Engine
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME

# Kernel Resource Limits & Protection
LimitMEMLOCK=infinity
LimitNOFILE=1048576
OOMScoreAdjust=-1000
# Environment="HSA_OVERRIDE_GFX_VERSION=11.0.0" # Enable for AMD RDNA3 / gfx1100 APUs

ExecStart=/home/YOUR_USERNAME/Programs/llama.cpp/build/bin/llama-server \
    --host 0.0.0.0 \
    --port 8080 \
    --models-preset /home/YOUR_USERNAME/Programs/gguf/models.ini \
    --models-max 1 \
    --parallel 1 \
    --no-mmap \
    --slot-prompt-similarity 0.0

Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

#### Service 3: `ollama.service` Override (Port 11434)

Configure via `sudo systemctl edit ollama.service`:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_NUM_PARALLEL=4"
```

Activate all systemd services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now llama-pair-router.service
sudo systemctl enable --now llama-vision.service
sudo systemctl restart ollama.service
```

### 5.3 Pipeline YAML Integration (`.env.yml`)

The following YAML schema demonstrates how `.aider_factory/.env_<repo>.yml` targets the local daemons:

```yaml
name: "Local Bare-Metal Pipeline"
working_directory: "/home/user/projects/my_project"

endpoints:
  architect_api_base: "http://localhost:8081/v1"
  editor_api: "http://localhost:11434/v1"
  editor_api_fallback: "http://localhost:8081/v1"
  weak_model_api_base: "http://localhost:11434/v1"
  rag_agent_api: "http://localhost:8081/v1"
  ocr_api_base: "http://localhost:8080/v1"
  embed_api_base: "http://localhost:8080"
  ranking_api_base: "http://localhost:8080"
  grounding_agent_api: "http://localhost:8090/v1"

models:
  architect_agent: "openai/qwen3.6-27b-90k:latest"
  editor_agent: "ollama/qwen2.5-coder:7b"
  editor_agent_test: "ollama/qwen2.5-coder:7b"
  editor_agent_test_fallback: "openai/qwen3.6-27b-90k:latest"
  weak_model: "ollama/qwen2.5-coder:1.5b"
  rag_agent: "openai/qwen3.6-27b-90k:latest"
  ocr_agent: "glm-ocr-f16:LATEST"
  embed_model: "qwen3-embedding-8b-8k:LATEST"
  embed_backend: "openai"
  ranking_agent: "qwen3-reranker-4b:latest"
  grounding_agent: "minicheck-flan-t5-large"
```

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

### 6.1 Diagnostic & Failure Signature Matrix

| Error Signature | Root Cause | Immediate Diagnostic Command | Remediation Procedure |
| :--- | :--- | :--- | :--- |
| `HSA_STATUS_ERROR_INVALID_ISA` | ROCm binary compiled without target gfx ISA architecture. | `journalctl -u llama-pair-router -n 50` | Export `HSA_OVERRIDE_GFX_VERSION=11.0.0` in systemd service environment. |
| `NaN` output / blank OCR markdown | Flash Attention enabled on vision model projection encoder. | Check `models.ini` for `flash-attn = on` under `glm-ocr-f16` | Explicitly enforce `flash-attn = off` in `models.ini` and remove global `-fa` flag from `llama-vision.service`. |
| `Killed` / Exit Code 137 | Linux kernel Out-Of-Memory (OOM) killer terminated daemon. | `dmesg -T \| grep -i oom` | Configure `OOMScoreAdjust=-1000` and `LimitMEMLOCK=infinity` in systemd service definition. |
| `Connection refused: 8080` | Port collision or daemon crashed during dynamic weight loading. | `ss -tulpn \| grep -E "8080\|8081"` | Inspect `journalctl -u llama-vision -e`. Verify GGUF file path in `models.ini`. |
| `404 Not Found` on `/v1/rerank` | Reranker model missing `reranking = true` flag or unparsed route. | `curl -X POST http://localhost:8080/v1/rerank` | Verify `reranking = true` and `pooling = rank` in `models.ini`. Endpoint falls back to `/rerank`. |
| Slot Prompt Theft / Context Bleed | Slot prefix matching corrupted cross-turn KV cache state. | Check `slot-prompt-similarity` flag | Add `--slot-prompt-similarity 0.0` to prevent slot hijacking across unrelated turns. |

### 6.2 Network Security & Firewall Configuration (UFW)

When accessing inference instances over a local subnet (e.g., orchestrator dispatching tasks to dedicated GPU nodes), configure Ubuntu's Uncomplicated Firewall (UFW) to permit traffic across target ports:

```bash
# Allow local subnet access to inference ports
sudo ufw allow from 192.168.1.0/24 to any port 8080 proto tcp comment "Llama Vision/Embed"
sudo ufw allow from 192.168.1.0/24 to any port 8081 proto tcp comment "Llama Router"
sudo ufw allow from 192.168.1.0/24 to any port 11434 proto tcp comment "Ollama Engine"
sudo ufw allow from 192.168.1.0/24 to any port 8090 proto tcp comment "MiniCheck Grounding"
sudo ufw reload
sudo ufw status verbose
```

### 6.3 End-to-End Diagnostic Verification Runbook

Execute this verification sequence after configuring daemons or upgrading model weights:

#### Step 1: Verify Hardware Monitoring & Device Nodes

```bash
# AMD ROCm Status
rocm-smi --showmeminfo vram --showuse

# NVIDIA CUDA Status
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv
```

#### Step 2: Validate Primary Router Chat Completion (Port 8081)

```bash
curl -s http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-27b-90k:latest",
    "messages": [{"role": "user", "content": "Respond with the word: READY"}],
    "max_tokens": 10
  }' | jq '.choices[0].message.content'
```

#### Step 3: Validate Dense Embedding Extraction (Port 8080)

```bash
curl -s http://localhost:8080/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-embedding-8b-8k:LATEST",
    "input": ["Hardware acceleration verification test string."]
  }' | jq '.data[0].embedding | length'
# Output should match vector dimension: 4096
```

#### Step 4: Validate Cross-Encoder Reranking (Port 8080)

```bash
curl -s http://localhost:8080/v1/rerank \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-reranker-4b:latest",
    "query": "What is the capital of France?",
    "documents": ["Paris is the capital of France.", "London is in the UK."]
  }' | jq '.results'
```

#### Step 5: Validate Background Ollama Engine (Port 11434)

```bash
curl -s http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder:1.5b",
    "prompt": "print(1 + 1)",
    "stream": false
  }' | jq '.response'
```
