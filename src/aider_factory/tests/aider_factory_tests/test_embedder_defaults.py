import sys
import os
import lancedb
sys.path.insert(0, ".aider_factory/python")
from rag_manager import embed_texts

def main():
    print("Testing embed_texts fallback default (BAAI/bge-m3)")
    v = embed_texts(["test text"], "sentence-transformers", "BAAI/bge-m3", None)
    print(f"Dim generated: {len(v[0])}")
    assert len(v[0]) == 1024, f"Expected 1024, got {len(v[0])}"
    print("All correct.")

if __name__ == "__main__":
    main()
