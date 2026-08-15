#!/usr/bin/env python3
# check_services.py — Verify reachability and responsiveness of local model endpoints

import json
import sys
import urllib.request

print("==================================================")
print("Checking Local Service Endpoints...")
print("==================================================")

all_passed = True

def probe_post(name, url, payload, expected_key, timeout=10):
    global all_passed
    print(f"\nSending probe to {name}: {url} ...")
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if expected_key in res_data:
                if expected_key == "data" and len(res_data["data"]) > 0 and "embedding" in res_data["data"][0]:
                    dim = len(res_data["data"][0]["embedding"])
                    print(f"  ✅ {name} is ONLINE. Embedding dimension: {dim}")
                elif expected_key == "choices" and len(res_data["choices"]) > 0:
                    reply = res_data["choices"][0]["message"]["content"].strip()
                    reply_display = reply if len(reply) < 30 else reply[:27] + "..."
                    print(f"  ✅ {name} is ONLINE. Reply: '{reply_display}'")
                else:
                    print(f"  ✅ {name} is ONLINE.")
            else:
                print(f"  ❌ {name} returned unexpected response: {res_data}", file=sys.stderr)
                all_passed = False
    except Exception as e:
        print(f"  ❌ {name} is OFFLINE or unreachable: {e}", file=sys.stderr)
        all_passed = False

def probe_get(name, url, expected_key, timeout=10):
    global all_passed
    print(f"\nSending probe to {name}: {url} ...")
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (AI-Factory/1.0)"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if expected_key in res_data:
                count = len(res_data[expected_key])
                print(f"  ✅ {name} is ONLINE. Returned {count} items.")
            else:
                print(f"  ❌ {name} returned unexpected response: {res_data}", file=sys.stderr)
                all_passed = False
    except Exception as e:
        print(f"  ❌ {name} is OFFLINE or unreachable: {e}", file=sys.stderr)
        all_passed = False

# Models
chat_model = "qwen3.6-27B-90k-udq4kxl:LATEST"
node2_chat_model = "qwen3.6-27b-90k:LATEST"
embed_model = "qwen3-embedding-8b-8k:LATEST"
ocr_model = "glm-ocr-f16:LATEST"
minicheck_model = "openai/minicheck-flan-t5-large"

# Tiny 1x1 transparent PNG in base64 to test vision capabilities efficiently
tiny_image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
def get_vision_payload(model_name):
    return {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "ping"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{tiny_image_b64}"}}
                ]
            }
        ],
        "max_tokens": 5
    }

# 1. Node 1 (192.168.100.1:8080) - All Models
probe_post(
    "Node 1 (Embedding)", 
    "http://192.168.100.1:8080/v1/embeddings", 
    {"model": embed_model, "input": ["dimension probe"]}, 
    "data"
)
probe_post(
    "Node 1 (Chat)", 
    "http://192.168.100.1:8080/v1/chat/completions", 
    {"model": chat_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}, 
    "choices"
)
probe_post(
    "Node 1 (OCR)", 
    "http://192.168.100.1:8080/v1/chat/completions", 
    get_vision_payload(ocr_model), 
    "choices"
)

# 2. Node 2 (192.168.100.2:8080) - Chat Only
probe_post(
    "Node 2 (Chat)", 
    "http://192.168.100.2:8080/v1/chat/completions", 
    {"model": node2_chat_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}, 
    "choices"
)

# 3. Router (192.168.100.2:8081) - Embed & OCR Only
probe_post(
    "Router (Embedding)", 
    "http://192.168.100.2:8081/v1/embeddings", 
    {"model": embed_model, "input": ["dimension probe"]}, 
    "data"
)
probe_post(
    "Router (OCR)", 
    "http://192.168.100.2:8081/v1/chat/completions", 
    get_vision_payload(ocr_model), 
    "choices"
)

# 4. SearXNG
probe_get(
    "SearXNG Server",
    "http://localhost:8088/search?q=Nighthawk+SmartNIC&format=json",
    "results"
)

# 5. MiniCheck
probe_post(
    "MiniCheck Server", 
    "http://192.168.100.1:8090/v1/chat/completions", 
    {
        "model": minicheck_model,
        "messages": [
            {
                "role": "user",
                "content": "Document: Nighthawk is a SmartNIC. Claim: Nighthawk is a SmartNIC. Is the claim supported? Reply 1 for yes, 0 for no:",
            }
        ],
        "max_tokens": 5
    }, 
    "choices"
)

if all_passed:
    print("\n🎉 All local endpoints are ONLINE and fully responsive!")
    sys.exit(0)
else:
    print("\n⚠️ Some endpoints failed the health check. See details above.", file=sys.stderr)
    sys.exit(1)
