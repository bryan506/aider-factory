# Local Inference Setup Guide

This guide covers the bare-metal installation, compilation, and systemd daemonization of local inference servers (`llama.cpp` and `ollama`) optimized for the AI Factory pipeline.

## 1. GPU Acceleration Layer

### Primary: AMD ROCm Setup

For AMD GPUs (especially Unified Memory setups like MI300 or consumer APUs/GPUs), install the ROCm SDK and add your user to the required hardware groups.

```bash
sudo apt install -y rocm-hip-sdk
sudo usermod -aG render,video $USER
# Log out and log back in for group changes to take effect
```

### Auxiliary: NVIDIA CUDA Setup

If deploying on an NVIDIA host, install the proprietary drivers and CUDA toolkit:

```bash
sudo apt install -y nvidia-driver-550 nvidia-cuda-toolkit
```

### Model Acquisition and Organization

GGUF model files can be downloaded from HuggingFace and stored in a central directory. All models are registered in `models.ini` using aliases, which you then reference in your pipeline YAML.

#### Downloading Models from HuggingFace

```bash
mkdir -p ~/Programs/gguf
cd ~/Programs/gguf

# Download split model files from HuggingFace (example pattern)
wget https://huggingface.co/USER/MODEL/resolve/main/model-00001-of-00002.gguf
wget https://huggingface.co/USER/MODEL/resolve/main/model-00002-of-00002.gguf
```

#### Merging Split GGUF Files

If the model was downloaded as multiple parts, use `llama-merge-gguf` to combine them:

```bash
# Clone and build llama-merge-gguf
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp/gguf-py
pip install -e .

# Merge split files into one GGUF
llama-merge-gguf \
    model-00001-of-00002.gguf \
    model-00002-of-00002.gguf \
    qwen3.6-27b-merged.gguf

# Remove split files, keep only the merged file
rm model-00001-of-00002.gguf model-00002-of-00002.gguf
```

#### Organizing Models

All merged GGUF files live in `~/Programs/gguf/` alongside `models.ini`:

```
~/Programs/gguf/
  models.ini
  qwen3.6-27b-merged.gguf
  glm-ocr-f16.gguf
  glm-ocr-mmproj.gguf
```

## 2. Compiling `llama.cpp`

#### Dependencies

```bash
sudo apt update
sudo apt install -y build-essential cmake git
```

#### Clone the Repository

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
```

#### AMD (HIP/ROCm) — Primary Build

```bash
HIPCXX="$(hipconfig -l)/clang" cmake -B build \
    -DGGML_HIP=ON \
    -DGGML_HIP_ROCWMMA_FATTN=ON \
    -DCMAKE_BUILD_TYPE=Release

cmake --build build --config Release -j $(nproc)
```

#### NVIDIA (CUDA) — Auxiliary Build

```bash
cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j $(nproc)
```

The compiled `llama-server` binary will be at:

```bash
./build/bin/llama-server
```

---

## 3. The `models.ini` Configuration File

llama.cpp supports a local model registry via `models.ini`. This file defines available models and their GGUF file paths, allowing `llama-server` to switch models on the fly via an API call.

Create `~/.config/llama-server/models.ini`:

```ini
# ~/.config/llama-server/models.ini
# Format: [model-name] -> /path/to/model.gguf
# The name after the slash in your pipeline YAML (e.g., "glm-ocr-f16:latest") maps to these entries.

[qwen3.5-122b-a10b-90k:latest]
path = /opt/models/qwen3.5-122b-a10b-90k-Q4_K_M.gguf
ctx_size = 32768
n_gpu_layers = 999

[qwen3.6-27b-90k:latest]
path = /opt/models/qwen3.6-27b-90k-udq4kxl.gguf
ctx_size = 32768
n_gpu_layers = 999

[glm-ocr-f16:LATEST]
model = /opt/models/GLM-OCR-f16.gguf
mmproj = /opt/models/mmproj-GLM-OCR-Q8_0.gguf
ctx-size = 65536          # divided by parallel slots (65536/8 = 8192 per slot)
parallel = 8              # 8 concurrent OCR requests; sweet spot for AMD APUs
n-gpu-layers = 999
temp = 0.1
flash-attn = off          # vision models: do NOT enable flash attention
cache-type-k = f16        # vision models: use f16 KV cache (not quantized)
cache-type-v = f16
mmap = false

[qwen3-embedding-8b-8k:LATEST]
model = /opt/models/Qwen3-Embedding-8B.i1-Q6_K.gguf
embeddings = on            # expose /v1/embeddings (CRITICAL for embedding models)
pooling = last             # Qwen3-Embedding pools the final [EOS] token (CRITICAL)
ctx-size = 16384           # safety margin for long queries (model trains to 40960)
batch-size = 16384
ubatch-size = 16384
n-gpu-layers = 999
parallel = 1               # embedding requests are serial; 1 slot is sufficient
flash-attn = on
cache-type-k = f16
cache-type-v = f16
mmap = false
```

When `llama-server` is running, you can switch models via API:

```bash
curl http://localhost:8081/load -d '{"model": "qwen3.6-27b-90k:latest"}'
```

---

## 4. Systemd Services for llama-server Instances

#### Systemd Service 1: Primary Router (Port 8081)

This instance serves the Architect and RAG Oracle models. It runs with MTP enabled for speed and parallel execution for hot-swapping.

Create `/etc/systemd/system/llama-pair-router.service`:

```ini
[Unit]
Description=Llama.cpp Primary Router — Architect + Oracle + Fallback Models
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME

# Ubuntu Performance & Stability Tuning
LimitMEMLOCK=infinity
LimitNOFILE=1048576
OOMScoreAdjust=-1000
# Environment="HSA_OVERRIDE_GFX_VERSION=11.0.0" # Uncomment if using consumer AMD RDNA3 GPUs/APUs

ExecStart=/opt/llama.cpp/build/bin/llama-server \
    --host 0.0.0.0 \
    --port 8081 \
    --models-dir /home/YOUR_USERNAME/.config/llama-server \
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

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable llama-pair-router.service
sudo systemctl start llama-pair-router.service
# Verify status:
sudo systemctl status llama-pair-router.service
```

#### Systemd Service 2: Vision/OCR + Embedding Endpoint (Port 8080)

This instance serves the GLM-OCR vision model and the embedding model. The router loads models on demand (`--models-max 1` means one model at a time; the router evicts the idle model when a different model is requested). **Critical:** Do NOT enable MTP or Flash Attention as global flags on this instance — vision model encoders break with both. Per-model overrides in `models.ini` (e.g. `flash-attn = on` for the embedding model) are safe.

Create `/etc/systemd/system/llama-vision.service`:

```ini
[Unit]
Description=Llama.cpp Vision/OCR + Embedding Endpoint
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME

# Ubuntu Performance & Stability Tuning
LimitMEMLOCK=infinity
LimitNOFILE=1048576
OOMScoreAdjust=-1000
# Environment="HSA_OVERRIDE_GFX_VERSION=11.0.0" # Uncomment if using consumer AMD RDNA3 GPUs/APUs

ExecStart=/opt/llama.cpp/build/bin/llama-server \
    --host 0.0.0.0 \
    --port 8080 \
    --models-preset /path/to/models.ini \
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

Note: `--parallel 1` is the global default; the per-model `parallel = 8` in `models.ini` for `glm-ocr-f16:LATEST` overrides it when that model is loaded.

#### Parallel OCR Tuning (Vision Model Slot Count)

The optimal number of parallel OCR slots depends on your GPU's memory bandwidth. On an AMD Strix Halo APU (128 GB unified memory, ~250 GB/s bandwidth, 40 CUs at 2800 MHz), benchmarks show:

| `parallel` | Per-slot decode speed | Aggregate throughput | Wall-clock (47-page PDF) | Verdict                          |
| ---------- | --------------------- | -------------------- | ------------------------ | -------------------------------- |
| 1          | ~80 t/s               | ~80 t/s              | ~20 min (sequential)     | Baseline                         |
| 8          | ~80 t/s               | ~640 t/s             | ~5 min                   | Sweet spot                       |
| 16         | ~14 t/s               | ~224 t/s             | ~12 min                  | Regression (bandwidth saturated) |

**Recommendation:** Start at `parallel = 8` for vision models. Memory cost is minimal (~5 GB total for GLM-OCR at 8 slots with 8192 context per slot). Monitor GPU clocks — if they drop below ~2200 MHz sustained, reduce slots.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable llama-vision.service
sudo systemctl start llama-vision.service
# Verify status:
sudo systemctl status llama-vision.service
```

---

## 5. Remote llama-server Instances & Ubuntu Firewall (UFW)

If you are accessing these servers from other machines on your LAN (or running remote instances), ensure Ubuntu's Uncomplicated Firewall (UFW) allows the traffic:

```bash
sudo ufw allow 8080/tcp
sudo ufw allow 8081/tcp
sudo ufw allow 11434/tcp
```

If your primary inference machine is a separate device (e.g., a tablet with an AMD GPU), you can run an additional `llama-server` instance on that remote host and configure the pipeline to target it via the `architect_api_base` endpoint.

On the remote host, create a similar systemd service pointing to the same `models.ini`:

```ini
[Service]
ExecStart=/opt/llama.cpp/build/bin/llama-server \
    --host 0.0.0.0 \
    --port 8081 \
    --models-dir /home/YOUR_USERNAME/.config/llama-server \
    --models-max 3 \
    --parallel 3 \
    --ctx-size 32768
```

## 6. Ollama Configuration (Port 11434)

Ollama is primarily used for fast, background coding tasks (the Editor model). It runs on its default port (11434) and is referenced by the `editor_ollama_api` endpoint.

#### Installation

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

#### Systemd Performance Tuning & Remote Access

To optimize Ollama for the AI Factory pipeline, we need to allow remote access, prevent models from unloading during long test-suite runs, and enable Flash Attention to save VRAM.

Edit the systemd override:

```bash
sudo systemctl edit ollama.service
```

Add the following environment variables:

```ini
[Service]
# Allow remote access from other machines on the LAN
Environment="OLLAMA_HOST=0.0.0.0"
# Keep models loaded in VRAM indefinitely (prevents slow reloads during long pipeline pauses)
Environment="OLLAMA_KEEP_ALIVE=-1"
# Enable Flash Attention to save VRAM on large context windows
Environment="OLLAMA_FLASH_ATTENTION=1"
# Allow multiple concurrent requests (useful if running multiple pipelines)
Environment="OLLAMA_NUM_PARALLEL=4"
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

#### Pulling Models

```bash
ollama pull qwen3.6-27B-90k:latest
ollama pull qwen2.5-coder:1.5b
```

The Ollama API is automatically OpenAI-compatible, so the `ollama/` prefix in your pipeline YAML will route correctly.
