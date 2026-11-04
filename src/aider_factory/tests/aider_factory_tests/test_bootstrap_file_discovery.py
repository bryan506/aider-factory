"""Unit tests for _discover_target_files and _discover_context_files
extracted from run_bootstrap().

These run against real temp directories — zero mocks on filesystem.
"""
import os
import tempfile
import textwrap

import pytest

import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", ".."))
_PYTHON_DIR = os.path.join(_PKG_DIR, "python")
for _p in (_PYTHON_DIR, _PKG_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bootstrap import (
    _ROUTER_ENDPOINTS,
    _discover_context_files,
    _discover_target_files,
    _render_workflow_yaml_template,
)
from cli import _is_test_path
from env_utils import atomic_write_text, is_test_path


def _make_project(tmp_path: str) -> str:
    """Create a realistic project skeleton."""
    # Source files (should be discovered)
    os.makedirs(os.path.join(tmp_path, "src", "mypkg"), exist_ok=True)
    open(os.path.join(tmp_path, "src", "mypkg", "core.py"), "w").close()
    open(os.path.join(tmp_path, "src", "mypkg", "utils.py"), "w").close()
    open(os.path.join(tmp_path, "src", "main.py"), "w").close()

    # Excluded: tests
    os.makedirs(os.path.join(tmp_path, "tests"), exist_ok=True)
    open(os.path.join(tmp_path, "tests", "test_core.py"), "w").close()

    # Excluded: conftest, setup, __init__
    open(os.path.join(tmp_path, "conftest.py"), "w").close()
    open(os.path.join(tmp_path, "setup.py"), "w").close()
    open(os.path.join(tmp_path, "src", "mypkg", "__init__.py"), "w").close()

    # Excluded dirs
    os.makedirs(os.path.join(tmp_path, ".venv", "lib"), exist_ok=True)
    open(os.path.join(tmp_path, ".venv", "lib", "hidden.py"), "w").close()
    os.makedirs(os.path.join(tmp_path, "__pycache__"), exist_ok=True)
    open(os.path.join(tmp_path, "__pycache__", "cached.py"), "w").close()

    # Context files
    open(os.path.join(tmp_path, "README.md"), "w").write("# Hello\n")
    os.makedirs(os.path.join(tmp_path, "docs"), exist_ok=True)
    open(os.path.join(tmp_path, "docs", "guide.md"), "w").write("guide\n")
    open(os.path.join(tmp_path, "docs", "api.md"), "w").write("api\n")

    return tmp_path


# Discovery helpers are imported directly from production bootstrap module.


class TestTargetFileDiscovery:
    def test_finds_source_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            targets = _discover_target_files(tmp)
            assert "src/main.py" in targets
            assert "src/mypkg/core.py" in targets
            assert "src/mypkg/utils.py" in targets

    def test_excludes_test_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            targets = _discover_target_files(tmp)
            assert not any("tests/" in t or "test_" in t for t in targets)

    def test_excludes_conftest_setup_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            targets = _discover_target_files(tmp)
            assert "conftest.py" not in targets
            assert "setup.py" not in targets
            assert not any("__init__.py" in t for t in targets)

    def test_excludes_venv_pycache(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            targets = _discover_target_files(tmp)
            assert not any(".venv" in t for t in targets)
            assert not any("__pycache__" in t for t in targets)

    def test_sorted_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            targets = _discover_target_files(tmp)
            assert targets == sorted(targets)

    def test_empty_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            targets = _discover_target_files(tmp)
            assert targets == []

    def test_finds_R_source_files(self):
        """Regression: .R files must be discovered (case-insensitive ext check)."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "R"), exist_ok=True)
            open(os.path.join(tmp, "R", "aac_fut_b.R"), "w").close()
            open(os.path.join(tmp, "R", "period_subset.R"), "w").close()
            # Excluded test file
            os.makedirs(os.path.join(tmp, "tests", "testthat"), exist_ok=True)
            open(os.path.join(tmp, "tests", "testthat", "test-aac.R"), "w").close()
            targets = _discover_target_files(tmp)
            assert "R/aac_fut_b.R" in targets
            assert "R/period_subset.R" in targets
            assert not any("test" in t for t in targets)


class TestContextFileDiscovery:
    def test_finds_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            ctx = _discover_context_files(tmp)
            assert "README.md" in ctx

    def test_finds_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            ctx = _discover_context_files(tmp)
            assert "docs/guide.md" in ctx
            assert "docs/api.md" in ctx

    def test_no_docs_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "README.md"), "w").close()
            ctx = _discover_context_files(tmp)
            assert ctx == ["README.md"]

    def test_empty_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _discover_context_files(tmp)
            assert ctx == []

    def test_finds_changelog_and_ignores_non_md_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            with open(os.path.join(tmp, "CHANGELOG.md"), "w", encoding="utf-8") as f:
                f.write("# Changelog\n")
            with open(os.path.join(tmp, "docs", "notes.txt"), "w", encoding="utf-8") as f:
                f.write("ignore me\n")
            ctx = _discover_context_files(tmp)
            assert ctx == ["README.md", "CHANGELOG.md", "docs/api.md", "docs/guide.md"]

    def test_target_discovery_excludes_egg_info_and_test_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "mypkg.egg-info"), exist_ok=True)
            open(os.path.join(tmp, "mypkg.egg-info", "leaked.py"), "w").close()
            os.makedirs(os.path.join(tmp, "src"), exist_ok=True)
            open(os.path.join(tmp, "src", "test.py"), "w").close()
            open(os.path.join(tmp, "src", "test.rs"), "w").close()
            open(os.path.join(tmp, "src", "setupTests.ts"), "w").close()
            open(os.path.join(tmp, "src", "Button.test.tsx"), "w").close()
            os.makedirs(os.path.join(tmp, "app", "domain"), exist_ok=True)
            open(os.path.join(tmp, "app", "domain", "contest.py"), "w").close()
            os.makedirs(os.path.join(tmp, "frontend", "lib"), exist_ok=True)
            open(os.path.join(tmp, "frontend", "lib", "latest.ts"), "w").close()

            targets = _discover_target_files(tmp)
            assert targets == ["app/domain/contest.py", "frontend/lib/latest.ts"]


class TestRenderWorkflowYamlTemplate:
    _SAMPLE_TEMPLATE = textwrap.dedent("""\
        name: "Default Template"
        working_directory: "/placeholder/dir"
        test_command_prefix: ""
        test_runner: "pytest {file}"
        test_naming_and_path: "tests/test_{stem}.py"
        endpoints:
            architect_api_base: "http://<your-router-host>:4000/v1"
            editor_api: "http://<your-router-host>:4000/v1"
            editor_api_fallback: "http://<your-router-host>:4000/v1"
            weak_model_api_base: "http://<your-router-host>:4000/v1"
            rag_agent_api: "http://<your-router-host>:4000/v1"
            grounding_agent_api: "http://<your-router-host>:4000/v1"
            ranking_api_base: null
            ocr_api_base: "http://<your-router-host>:4000/v1"
            embed_api_base: "http://<your-router-host>:4000/v1"
        models:
            architect_agent: "default-arch"
            editor_agent: "default-ed"
            editor_agent_test: "default-ed-test"
            editor_agent_test_fallback: "default-ed-fb"
            weak_model: "default-weak"
            embed_model: "default-embed"
            embed_backend: "sentence-transformers"
            ranking_agent: "default-rank"
        phases:
          - name: "Phase 1: Implementation"
            template: "../markdown/internal/analyze_bugs.md"
            target_files: []
            context_files_job: []
    """)

    def test_router_base_rewrites_only_router_endpoints(self):
        router_url = "http://10.0.0.42:4000/v1"
        assert _ROUTER_ENDPOINTS == (
            "architect_api_base",
            "editor_api",
            "editor_api_fallback",
            "weak_model_api_base",
        )
        rendered = _render_workflow_yaml_template(
            self._SAMPLE_TEMPLATE,
            name="My Repo Pipeline",
            working_directory="C:\\Users\\dev\\my_repo",
            router_base=router_url,
        )
        assert 'name: "My Repo Pipeline"' in rendered
        assert '- name: "Phase 1: Implementation"' in rendered
        assert 'working_directory: "C:/Users/dev/my_repo"' in rendered

        for ep in _ROUTER_ENDPOINTS:
            assert f'{ep}: "{router_url}"' in rendered

        for local_ep in (
            "rag_agent_api",
            "grounding_agent_api",
            "ranking_api_base",
            "ocr_api_base",
            "embed_api_base",
        ):
            assert f'{local_ep}: "{router_url}"' not in rendered

    def test_multi_phase_template_substitution(self):
        multi_phase_yaml = textwrap.dedent("""\
            name: "Plan Do Default"
            working_directory: "/placeholder"
            test_command_prefix: ""
            test_runner: "pytest {file}"
            test_naming_and_path: "tests/unit/test_{stem}.py"
            endpoints:
                architect_api_base: "http://localhost:8080/v1"
                editor_api: "http://localhost:8080/v1"
                editor_api_fallback: "http://localhost:8080/v1"
                weak_model_api_base: "http://localhost:8080/v1"
                rag_agent_api: "http://localhost:8080/v1"
            phases:
              - name: "Architect Planning Phase"
                models:
                    architect_agent: "old-arch"
                    editor_agent: "old-ed"
                    editor_agent_test: "old-ed"
                    editor_agent_test_fallback: "old-ed"
                    weak_model: "old-weak"
                    ranking_agent: "old-rank"
                    embed_model: "old-embed"
                rag:
                    embed_backend: "sentence-transformers"
              - name: "Code Implementation Phase"
                test_naming_and_path: "tests/unit/test_{stem}.py"
                models:
                    architect_agent: "old-arch"
                    editor_agent: "old-ed"
                    editor_agent_test: "old-ed"
                    editor_agent_test_fallback: "old-ed"
                    weak_model: "old-weak"
                    ranking_agent: "old-rank"
                    embed_model: "old-embed"
                rag:
                    embed_backend: "sentence-transformers"
        """)
        router_url = "http://192.168.1.100:4000/v1"
        models = {
            "architect": "openai/qwen-27b",
            "editor": "openai/qwen-coder",
            "weak": "openai/qwen-7b",
            "embed": "openai/text-embedding-3-small",
            "reranker": "openai/bge-reranker",
        }
        rendered = _render_workflow_yaml_template(
            multi_phase_yaml,
            name="Custom Plan-Do Pipeline",
            working_directory="/workspace/demo",
            test_command_prefix="ENV=test",
            test_runner="cargo test --test {stem}",
            test_naming_and_path="tests/{stem}.rs",
            router_base=router_url,
            model_choices=models,
        )
        assert rendered.count('name: "Custom Plan-Do Pipeline"') == 1
        assert '- name: "Architect Planning Phase"' in rendered
        assert '- name: "Code Implementation Phase"' in rendered
        assert rendered.count('test_naming_and_path: "tests/{stem}.rs"') == 2
        assert rendered.count('architect_agent: "openai/qwen-27b"') == 2
        assert rendered.count('editor_agent: "openai/qwen-coder"') == 2
        assert rendered.count('embed_backend: "openai"') == 2
        assert f'weak_model_api_base: "{router_url}"' in rendered
        assert f'rag_agent_api: "{router_url}"' not in rendered

    def test_cluster_config_updates_endpoints_and_fallback_to_architect(self):
        cluster_cfg = {
            "architect_api_base": "http://cluster:4000/v1",
            "editor_api": "http://cluster:4000/v1",
            "rag_agent_api": "http://cluster:4000/v1",
            "architect_agent": "openai/deepseek-r1",
            "editor_agent": "openai/qwen-coder-32b",
        }
        rendered = _render_workflow_yaml_template(
            self._SAMPLE_TEMPLATE,
            name="Cluster Pipeline",
            working_directory="/tmp/proj",
            cluster_config=cluster_cfg,
        )
        assert 'architect_api_base: "http://cluster:4000/v1"' in rendered
        assert 'editor_api: "http://cluster:4000/v1"' in rendered
        assert 'rag_agent_api: "http://cluster:4000/v1"' in rendered
        assert 'architect_agent: "openai/deepseek-r1"' in rendered
        assert 'editor_agent: "openai/qwen-coder-32b"' in rendered
        assert 'editor_agent_test: "openai/qwen-coder-32b"' in rendered
        assert 'editor_agent_test_fallback: "openai/deepseek-r1"' in rendered
        assert '- name: "Phase 1: Implementation"' in rendered

    def test_embed_backend_sentence_transformers_for_local_embed_model(self):
        rendered = _render_workflow_yaml_template(
            self._SAMPLE_TEMPLATE,
            name="Local Embed",
            working_directory="/tmp/proj",
            model_choices={
                "architect": "openai/local-27b",
                "embed": "BAAI/bge-large-en-v1.5",
            },
        )
        assert 'embed_model: "BAAI/bge-large-en-v1.5"' in rendered
        assert 'embed_backend: "sentence-transformers"' in rendered
        assert 'editor_agent_test_fallback: "openai/local-27b"' in rendered

    def test_standardize_analyze_bugs_and_file_list_formatting(self):
        ctx_list = [f"docs/doc_{i}.md" for i in range(20)]
        rendered = _render_workflow_yaml_template(
            self._SAMPLE_TEMPLATE,
            name="Formatting Pipeline",
            working_directory="/tmp/proj",
            target_file="src/main.py",
            context_files=ctx_list,
            standardize_analyze_bugs=True,
        )
        assert "/markdown/internal/analyze_bugs.md" in rendered
        assert "../markdown/internal/analyze_bugs.md" not in rendered
        assert '    target_files:\n    - "src/main.py"' in rendered
        assert '    context_files_job:\n    - "docs/doc_0.md"' in rendered
        assert "docs/doc_14.md" in rendered
        assert "docs/doc_15.md" not in rendered

        unindented = 'name: "X"\nworking_directory: "/tmp"\ntarget_files: []\ncontext_files_job: []\n'
        rendered_unindented = _render_workflow_yaml_template(
            unindented,
            name="Unindented",
            working_directory="/tmp",
            target_file="scratchpad.py",
            context_files=["README.md"],
        )
        assert 'target_files:\n        - "scratchpad.py"' in rendered_unindented
        assert 'context_files_job:\n        - "README.md"' in rendered_unindented


class TestTestPathParityAndAtomicWrite:
    @pytest.mark.parametrize(
        "rel_path,expected",
        [
            ("test.py", True),
            ("tests.py", True),
            ("src/test.rs", True),
            ("src/tests.rs", True),
            ("src/setupTests.ts", True),
            ("src/setuptests.js", True),
            ("conftest.py", True),
            ("app/domain/contest.py", False),
            ("frontend/lib/latest.ts", False),
            ("README.md", False),
            ("", False),
            (".", False),
            (None, False),
        ],
    )
    def test_cli_and_env_utils_is_test_path_parity(self, rel_path, expected):
        assert is_test_path(rel_path) is expected
        assert _is_test_path(rel_path) is expected

    def test_atomic_write_text_leaves_no_tmp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "nested", "config.yml")
            atomic_write_text(target, 'name: "Atomic Test"\n')
            with open(target, "r", encoding="utf-8") as f:
                assert f.read() == 'name: "Atomic Test"\n'
            leftover_tmp = [
                fn for fn in os.listdir(os.path.join(tmp, "nested"))
                if fn.endswith(".tmp")
            ]
            assert leftover_tmp == []
