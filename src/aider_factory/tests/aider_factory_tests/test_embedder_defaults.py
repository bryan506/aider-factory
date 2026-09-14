import sys
import os
import lancedb

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

from rag_manager import embed_texts

def test_template_embed_model_is_not_cloud():
    """The shipped template must never pair a cloud model name with sentence-transformers."""
    template_path = os.path.abspath(os.path.join(
        script_dir, "../../default_configs/sample_yaml_config/complete_env.yml"
    ))
    with open(template_path, "r") as f:
        content = f.read()
    assert 'embed_model: "BAAI/bge-m3"' in content
    assert "gemini/text-embedding-004" not in content
    assert 'embed_backend: "sentence-transformers"' in content


def main():
    print("Testing embed_texts fallback default (BAAI/bge-m3)")
    v = embed_texts(["test text"], "sentence-transformers", "BAAI/bge-m3", None)
    print(f"Dim generated: {len(v[0])}")
    assert len(v[0]) == 1024, f"Expected 1024, got {len(v[0])}"
    print("All correct.")

    test_template_embed_model_is_not_cloud()
    print("Template embed model guard PASS")

if __name__ == "__main__":
    main()
