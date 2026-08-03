#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../python"))
from rag_manager import embed_texts

print("Starting Embedder Routing Tests...\n")

from unittest.mock import patch

def test_embed_texts_st():
    # Test sentence-transformers fallback directly
    try:
        vecs = embed_texts(["hello world"], "sentence-transformers", "BAAI/bge-m3", None)
        assert len(vecs) == 1
        assert len(vecs[0]) == 1024
        print("  ✅ sentence-transformers backend works (loaded BAAI/bge-m3).")
    except Exception as e:
        print(f"  ❌ Failed sentence-transformers test: {e}")

def test_embed_texts_unknown():
    try:
        embed_texts(["test"], "invalid-backend", "model", None)
        print("  ❌ Failed: should have raised ValueError for invalid backend.")
    except ValueError:
        print("  ✅ invalid backend correctly raises ValueError.")

if __name__ == "__main__":
    test_embed_texts_st()
    test_embed_texts_unknown()
    print("\n🎉 Embedder Tests Complete!")
