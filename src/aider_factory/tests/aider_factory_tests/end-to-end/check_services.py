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
node2_chat_model = "qwen3.6-27b-90k:latest"
embed_model = "qwen3-embedding-8b-8k:LATEST"
router_model = "qwen3.6-27b-90k:LATEST"
minicheck_model = "openai/minicheck-flan-t5-large"

# 1. Node 1 (192.168.100.1:8080)
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

# 2. Node 2 (192.168.100.2:8080)
probe_post(
    "Node 2 (Embedding)", 
    "http://192.168.100.2:8080/v1/embeddings", 
    {"model": embed_model, "input": ["dimension probe"]}, 
    "data"
)
probe_post(
    "Node 2 (Chat)", 
    "http://192.168.100.2:8080/v1/chat/completions", 
    {"model": node2_chat_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}, 
    "choices"
)

# 3. Node 2 Router/OCR (192.168.100.2:8081)
probe_post(
    "Node 2 Router/OCR", 
    "http://192.168.100.2:8081/v1/chat/completions", 
    {"model": router_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}, 
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
