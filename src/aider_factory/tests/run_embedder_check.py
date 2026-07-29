#!/usr/bin/env python3
import os
import sys
import requests

api_base = "http://192.168.100.1:8080/v1"
model = "qwen3-embedding-8b-8k:LATEST"

print("Testing direct requests.post()...")
try:
    r = requests.post(f"{api_base}/embeddings", json={
        "input": ["dimension probe"],
        "model": model
    }, headers={"Authorization": "Bearer sk-dummy"}, timeout=30)
    r.raise_for_status()
    vecs = [d["embedding"] for d in r.json()["data"]]
    print(f"✅ Success! Vector dimension: {len(vecs[0])}")
except Exception as e:
    print(f"❌ Failed: {e}")
    if hasattr(e, "response") and e.response is not None:
        print(f"Response: {e.response.text}")
