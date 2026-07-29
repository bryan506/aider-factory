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

# 2. Check MiniCheck Entailment Verifier
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
