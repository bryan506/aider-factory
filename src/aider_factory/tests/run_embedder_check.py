#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../python")))
from rag_manager import embed_texts

print("==================================================")
print("Diagnostic: Testing Remote OpenAI Embedder Endpoints")
print("==================================================")

# 1. Test Node 1
node1_url = "http://192.168.100.1:8080/v1"
node1_model = "qwen3-embedding-8b-8k-gpu:LATEST"
print(f"\n[1/2] Probing Node 1 Embedder ({node1_url}) with model '{node1_model}'...")
try:
    vecs = embed_texts(
        texts=["What is the leverage ratio formula?"],
        backend="openai",
        model=node1_model,
        api_base=node1_url,
    )
    dim = len(vecs[0])
    print(f"  ✅ Node 1 ONLINE & RESPONDING! Generated embedding dim: {dim}")
except Exception as e:
    print(f"  ❌ Node 1 Failed: {e}")

# 2. Test Router
router_url = "http://192.168.100.2:8081/v1"
router_model = "qwen3-embedding-8b-8k:LATEST"
print(f"\n[2/2] Probing Router Embedder ({router_url}) with model '{router_model}'...")
try:
    vecs = embed_texts(
        texts=["What is the leverage ratio formula?"],
        backend="openai",
        model=router_model,
        api_base=router_url,
    )
    dim = len(vecs[0])
    print(f"  ✅ Router ONLINE & RESPONDING! Generated embedding dim: {dim}")
except Exception as e:
    print(f"  ❌ Router Failed: {e}")

print("\n==================================================")
