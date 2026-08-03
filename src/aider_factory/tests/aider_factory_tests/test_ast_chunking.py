import sys
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

from rag_manager import _ast_chunk

def test_ast_fallback():
    print("Testing missing grammar fallback...")
    # Passing an invalid language should trigger the fallback and return []
    chunks = _ast_chunk("def foo():\n    print('test')", "invalid_lang_that_does_not_exist")
    assert len(chunks) == 0, f"Expected 0 chunks for missing grammar, got {len(chunks)}"
    print("  ✅ Missing grammar safely returns [] and skips code file.")

def test_ast_python():
    print("Testing Python grammar via tree_sitter_language_pack...")
    code = """
def my_func():
    print("hello")

class MyClass:
    def method1(self):
        pass
"""
    chunks = _ast_chunk(code, "python", max_chars=2000)
    # The language pack is installed in the aider venv, so this should return > 0 chunks
    assert len(chunks) > 0, "AST parser returned 0 chunks. The grammar failed to parse."
    assert chunks[0][1] > 0, "Line numbers missing."
    print(f"  ✅ Python grammar parsed successfully. Produced {len(chunks)} chunks.")

if __name__ == "__main__":
    test_ast_fallback()
    test_ast_python()
