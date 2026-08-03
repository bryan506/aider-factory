#!/usr/bin/env python3
# check_services.py — Verify reachability and responsiveness of local model endpoints

import json
import sys
import urllib.request

print("==================================================")
print("Checking Local Service Endpoints...")
print("==================================================")

# 1. Check Qwen3 Embedding Model
embed_url = "http://192.168.100.1:8080/v1/embeddings"
embed_payload = {"model": "qwen3-embedding-8b-8k:LATEST", "input": ["dimension probe"]}
print(f"Sending probe to Embedding Server: {embed_url} ...")
try:
    req = urllib.request.Request(
        embed_url,
        data=json.dumps(embed_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        if "data" in res_data and len(res_data["data"]) > 0:
            dim = len(res_data["data"][0]["embedding"])
            print(f"  ✅ Embedding Server is ONLINE. Embedding dimension: {dim}")
        else:
            print(
                f"  ❌ Embedding Server returned unexpected response: {res_data}",
                file=sys.stderr,
            )
            sys.exit(1)
except Exception as e:
    print(f"  ❌ Embedding Server is OFFLINE or unreachable: {e}", file=sys.stderr)
    sys.exit(1)

# 1b. Check Local Editor Server (192.168.100.1:8080)
editor_url = "http://192.168.100.1:8080/v1/chat/completions"
editor_payload = {
    "model": "qwen3.6-27B-90k-udq4kxl:LATEST",
    "messages": [{"role": "user", "content": "ping"}],
    "max_tokens": 5
}
print(f"Sending probe to Editor Server: {editor_url} ...")
try:
    req = urllib.request.Request(
        editor_url,
        data=json.dumps(editor_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        if "choices" in res_data:
            print("  ✅ Editor Server is ONLINE and responding.")
        else:
            print(f"  ❌ Editor Server returned unexpected response: {res_data}", file=sys.stderr)
            sys.exit(1)
except Exception as e:
    print(f"  ❌ Editor Server is OFFLINE or unreachable: {e}", file=sys.stderr)
    sys.exit(1)

# 1c. Check Primary Router & OCR Server (192.168.100.2:8081)
router_url = "http://192.168.100.2:8081/v1/chat/completions"
router_payload = {
    "model": "qwen3.6-27b-90k:LATEST",
    "messages": [{"role": "user", "content": "ping"}],
    "max_tokens": 5
}
print(f"Sending probe to Primary Router: {router_url} ...")
try:
    req = urllib.request.Request(
        router_url,
        data=json.dumps(router_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        if "choices" in res_data:
            print("  ✅ Primary Router Server is ONLINE and responding.")
        else:
            print(f"  ❌ Primary Router Server returned unexpected response: {res_data}", file=sys.stderr)
            sys.exit(1)
except Exception as e:
    print(f"  ❌ Primary Router Server is OFFLINE or unreachable: {e}", file=sys.stderr)
    sys.exit(1)

# 2. Check SearXNG Meta-Search Engine
searxng_url = "http://localhost:8088/search?q=Nighthawk+SmartNIC&format=json"
print(f"\nSending probe to SearXNG Server: {searxng_url} ...")
try:
    req = urllib.request.Request(
        searxng_url,
        headers={"User-Agent": "Mozilla/5.0 (AI-Factory/1.0)"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        if "results" in res_data:
            results_count = len(res_data["results"])
            print(f"  ✅ SearXNG Server is ONLINE. Returned {results_count} search results.")
        else:
            print(
                f"  ❌ SearXNG Server returned unexpected response (missing 'results'): {res_data}",
                file=sys.stderr,
            )
            sys.exit(1)
except Exception as e:
    print(f"  ❌ SearXNG Server is OFFLINE or unreachable on port 8088: {e}", file=sys.stderr)
    sys.exit(1)

# 3. Check MiniCheck Entailment Verifier
minicheck_url = "http://192.168.100.1:8090/v1/chat/completions"
minicheck_payload = {
    "model": "openai/minicheck-flan-t5-large",
    "messages": [
        {
            "role": "user",
            "content": "Document: Nighthawk is a SmartNIC. Claim: Nighthawk is a SmartNIC. Is the claim supported? Reply 1 for yes, 0 for no:",
        }
    ],
}
print(f"\nSending probe to MiniCheck Server: {minicheck_url} ...")
try:
    req = urllib.request.Request(
        minicheck_url,
        data=json.dumps(minicheck_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        if "choices" in res_data and len(res_data["choices"]) > 0:
            reply = res_data["choices"][0]["message"]["content"]
            print(f"  ✅ MiniCheck Server is ONLINE. Reply: '{reply.strip()}'")
        else:
            print(
                f"  ❌ MiniCheck Server returned unexpected response: {res_data}",
                file=sys.stderr,
            )
            sys.exit(1)
except Exception as e:
    print(f"  ❌ MiniCheck Server is OFFLINE or unreachable: {e}", file=sys.stderr)
    sys.exit(1)

print("\n🎉 All local endpoints are ONLINE and fully responsive!")
sys.exit(0)
