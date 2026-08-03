import sys
import os
import lancedb

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

from rag_manager import embed_texts

def main():
    print("Testing embed_texts fallback default (BAAI/bge-m3)")
    v = embed_texts(["test text"], "sentence-transformers", "BAAI/bge-m3", None)
    print(f"Dim generated: {len(v[0])}")
    assert len(v[0]) == 1024, f"Expected 1024, got {len(v[0])}"
    print("All correct.")

if __name__ == "__main__":
    main()
