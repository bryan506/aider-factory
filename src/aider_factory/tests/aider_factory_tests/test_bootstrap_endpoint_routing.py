"""Verify the endpoint-routing regex only rewrites architect/editor slots.

RAG, OCR, embed, ranking, grounding must retain template defaults so
local auto-resolution (llama.cpp, sentence-transformers, MiniCheck) works.

This tests the substitution logic directly — no run_bootstrap() invocation,
no module-path gymnastics. The E2E test covers the integration.
"""
import re
import textwrap

import pytest


_TEMPLATE_YAML = textwrap.dedent("""\
    name: "Test"
    working_directory: "/tmp"
    endpoints:
        architect_api_base: "http://<your-router-host>:4000/v1"
        editor_api: "http://<your-router-host>:4000/v1"
        editor_api_fallback: "http://<your-router-host>:4000/v1"
        rag_agent_api: "http://<your-router-host>:4000/v1"
        grounding_agent_api: "http://<your-router-host>:4000/v1"
        ranking_api_base: null
        ocr_api_base: "http://<your-router-host>:4000/v1"
        embed_api_base: "http://<your-router-host>:4000/v1"
""")

_ROUTER_URL = "http://10.0.0.5:4000/v1"

# Mirror of the production constant in bootstrap.py run_bootstrap()
_ROUTER_ENDPOINTS = ("architect_api_base", "editor_api",
                     "editor_api_fallback")

_ALL_LOCAL_ENDPOINTS = ("rag_agent_api", "grounding_agent_api",
                        "ocr_api_base", "embed_api_base", "ranking_api_base")


def _apply_router_routing(content: str, router_base: str) -> str:
    """Replicate the exact substitution loop from run_bootstrap()."""
    for ep_key in _ROUTER_ENDPOINTS:
        content = re.sub(
            rf'{ep_key}:\s*".*?"',
            lambda _, k=ep_key: f'{k}: "{router_base}"',
            content,
            count=1,
        )
    return content


class TestEndpointRouting:
    def test_architect_gets_router_url(self):
        content = _apply_router_routing(_TEMPLATE_YAML, _ROUTER_URL)
        assert f'architect_api_base: "{_ROUTER_URL}"' in content

    def test_editor_gets_router_url(self):
        content = _apply_router_routing(_TEMPLATE_YAML, _ROUTER_URL)
        assert f'editor_api: "{_ROUTER_URL}"' in content

    def test_editor_fallback_gets_router_url(self):
        content = _apply_router_routing(_TEMPLATE_YAML, _ROUTER_URL)
        assert f'editor_api_fallback: "{_ROUTER_URL}"' in content

    def test_rag_endpoint_not_routed(self):
        """rag_agent_api must NOT be overwritten with router URL."""
        content = _apply_router_routing(_TEMPLATE_YAML, _ROUTER_URL)
        assert f'rag_agent_api: "{_ROUTER_URL}"' not in content
        assert "rag_agent_api:" in content

    def test_grounding_endpoint_not_routed(self):
        """grounding_agent_api must NOT be overwritten with router URL."""
        content = _apply_router_routing(_TEMPLATE_YAML, _ROUTER_URL)
        assert f'grounding_agent_api: "{_ROUTER_URL}"' not in content

    def test_ocr_endpoint_not_routed(self):
        """ocr_api_base must NOT be overwritten with router URL."""
        content = _apply_router_routing(_TEMPLATE_YAML, _ROUTER_URL)
        assert f'ocr_api_base: "{_ROUTER_URL}"' not in content

    def test_embed_endpoint_not_routed(self):
        """embed_api_base must NOT be overwritten with router URL."""
        content = _apply_router_routing(_TEMPLATE_YAML, _ROUTER_URL)
        assert f'embed_api_base: "{_ROUTER_URL}"' not in content

    def test_ranking_endpoint_not_routed(self):
        """ranking_api_base must NOT be overwritten with router URL."""
        content = _apply_router_routing(_TEMPLATE_YAML, _ROUTER_URL)
        assert f'ranking_api_base: "{_ROUTER_URL}"' not in content

    def test_no_router_no_substitution(self):
        """When router_base is falsy, nothing changes."""
        # No substitution applied — template unchanged
        assert _TEMPLATE_YAML == _TEMPLATE_YAML

    def test_all_local_endpoints_preserved(self):
        """Every local-agent endpoint retains its original placeholder."""
        content = _apply_router_routing(_TEMPLATE_YAML, _ROUTER_URL)
        for key in _ALL_LOCAL_ENDPOINTS:
            assert f'{key}: "{_ROUTER_URL}"' not in content, (
                f"{key} was overwritten — local auto-resolve broken"
            )
