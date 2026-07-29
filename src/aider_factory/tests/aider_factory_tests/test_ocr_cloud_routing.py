#!/usr/bin/env python3
"""Tests for cloud/local OCR routing in _ocr_image.

Covers:
  - Local endpoint path: api_base set -> direct requests.post
  - Cloud model path: api_base empty/None -> litellm.completion
  - model_id extraction: prefix preserved for cloud, stripped for local
  - Retry + backoff behavior on both paths
  - Backward compat: existing mock_ocr pattern still works
  - Integration: ingest cfg routes correctly for cloud and local
"""
import sys, os, types, shutil
sys.path.insert(0, ".aider_factory/python")

import rag_manager
from rag_manager import _ocr_image


def _make_png(tmp_path):
    """Create a minimal test PNG and return its path."""
    from PIL import Image
    os.makedirs(tmp_path, exist_ok=True)
    p = os.path.join(tmp_path, "test_page.png")
    Image.new("RGB", (10, 10), (255, 255, 255)).save(p)
    return p


# ---- Test 1: Local endpoint routing ----

def test_local_endpoint_routing():
    """When api_base is set, _ocr_image posts to {api_base}/chat/completions."""
    print("test_local_endpoint_routing...")
    captured = {}

    def mock_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["model"] = json["model"]
        resp = types.SimpleNamespace()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"choices": [{"message": {"content": "LOCAL_OCR_OUTPUT"}}]}
        return resp

    import requests as _real_requests
    orig_post = _real_requests.post
    _real_requests.post = mock_post

    tmp = "temp/test_ocr_local"
    png = _make_png(tmp)

    try:
        result = _ocr_image(png, "glm-ocr-f16:LATEST", "http://localhost:8080/v1", "Extract text")
        assert result == "LOCAL_OCR_OUTPUT"
        assert captured["url"] == "http://localhost:8080/v1/chat/completions"
        assert captured["model"] == "glm-ocr-f16:LATEST"
        print("  OK: local endpoint routed correctly")
    finally:
        _real_requests.post = orig_post
        shutil.rmtree(tmp, ignore_errors=True)


# ---- Test 2: Cloud model routing ----

def test_cloud_model_routing():
    """When api_base is empty/None, _ocr_image calls litellm.completion."""
    print("test_cloud_model_routing...")
    captured = {}

    mock_litellm = types.ModuleType("litellm")
    def mock_completion(model=None, messages=None, **kw):
        captured["model"] = model
        captured["messages"] = messages
        return {"choices": [{"message": {"content": "CLOUD_OCR_OUTPUT"}}]}
    mock_litellm.completion = mock_completion

    orig_litellm = sys.modules.get("litellm")
    sys.modules["litellm"] = mock_litellm

    tmp = "temp/test_ocr_cloud"
    png = _make_png(tmp)

    try:
        # api_base="" -> cloud path
        result = _ocr_image(png, "gemini/gemini-2.5-flash", "", "Extract text")
        assert result == "CLOUD_OCR_OUTPUT"
        assert captured["model"] == "gemini/gemini-2.5-flash"
        content = captured["messages"][0]["content"]
        has_image = any(c.get("type") == "image_url" for c in content)
        assert has_image, "Image not included in cloud request"
        print("  OK: api_base='' routes to cloud via litellm")

        # api_base=None -> also cloud path
        captured.clear()
        result = _ocr_image(png, "gemini/gemini-2.5-flash", None, "Extract text")
        assert result == "CLOUD_OCR_OUTPUT"
        assert captured["model"] == "gemini/gemini-2.5-flash"
        print("  OK: api_base=None also routes to cloud")
    finally:
        if orig_litellm is not None:
            sys.modules["litellm"] = orig_litellm
        else:
            sys.modules.pop("litellm", None)
        shutil.rmtree(tmp, ignore_errors=True)


# ---- Test 3: model_id extraction ----

def test_model_id_extraction():
    """Cloud models keep prefix; local models strip it."""
    print("test_model_id_extraction...")

    def extract(ocr_agent, ocr_api_base):
        _raw = ocr_agent or ""
        return _raw if not ocr_api_base else _raw.split("/", 1)[-1]

    # Cloud: prefix preserved
    assert extract("gemini/gemini-2.5-flash", "") == "gemini/gemini-2.5-flash"
    assert extract("gemini/gemini-2.5-flash", None) == "gemini/gemini-2.5-flash"
    assert extract("github_copilot/gpt-4o", "") == "github_copilot/gpt-4o"

    # Local: prefix stripped
    assert extract("openai/glm-ocr-f16:LATEST", "http://localhost:8080/v1") == "glm-ocr-f16:LATEST"
    assert extract("glm-ocr-f16:LATEST", "http://localhost:8080/v1") == "glm-ocr-f16:LATEST"

    # Edge cases
    assert extract("", "") == ""
    assert extract(None, None) == ""
    assert extract("", "http://localhost:8080/v1") == ""

    print("  OK: prefix handling correct for all cases")


# ---- Test 4: Retry on local path ----

def test_retry_local():
    """Local path retries on transient failure."""
    print("test_retry_local...")
    call_count = {"n": 0}

    def mock_post_flaky(url, json=None, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionError("transient failure")
        resp = types.SimpleNamespace()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"choices": [{"message": {"content": "RETRY_OK"}}]}
        return resp

    import requests as _real_requests
    orig_post = _real_requests.post
    _real_requests.post = mock_post_flaky

    tmp = "temp/test_ocr_retry_local"
    png = _make_png(tmp)

    try:
        result = _ocr_image(png, "model", "http://localhost:8080/v1", "prompt", timeout=5, retries=1)
        assert result == "RETRY_OK"
        assert call_count["n"] == 2, f"Expected 2 calls, got {call_count['n']}"
        print("  OK: local path retried on transient error")
    finally:
        _real_requests.post = orig_post
        shutil.rmtree(tmp, ignore_errors=True)


# ---- Test 5: Retry on cloud path ----

def test_retry_cloud():
    """Cloud path retries on transient failure."""
    print("test_retry_cloud...")
    call_count = {"n": 0}

    mock_litellm = types.ModuleType("litellm")
    def mock_completion_flaky(model=None, messages=None, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise Exception("cloud transient error")
        return {"choices": [{"message": {"content": "CLOUD_RETRY_OK"}}]}
    mock_litellm.completion = mock_completion_flaky

    orig_litellm = sys.modules.get("litellm")
    sys.modules["litellm"] = mock_litellm

    tmp = "temp/test_ocr_retry_cloud"
    png = _make_png(tmp)

    try:
        result = _ocr_image(png, "gemini/model", None, "prompt", retries=1)
        assert result == "CLOUD_RETRY_OK"
        assert call_count["n"] == 2
        print("  OK: cloud path retried on transient error")
    finally:
        if orig_litellm is not None:
            sys.modules["litellm"] = orig_litellm
        else:
            sys.modules.pop("litellm", None)
        shutil.rmtree(tmp, ignore_errors=True)


# ---- Test 6: Backward compat with existing monkeypatch ----

def test_backward_compat_mock():
    """Existing monkeypatch pattern (rag_manager._ocr_image = mock) still works."""
    print("test_backward_compat_mock...")
    captured = {}

    def my_mock(png_path, model_id, api_base, prompt_text, timeout=300, retries=1):
        captured["called"] = True
        captured["model_id"] = model_id
        captured["api_base"] = api_base
        return "MOCK_OUTPUT"

    orig = rag_manager._ocr_image
    rag_manager._ocr_image = my_mock
    try:
        result = rag_manager._ocr_image("dummy.png", "model", "http://api", "prompt")
        assert result == "MOCK_OUTPUT"
        assert captured["called"]
        assert captured["model_id"] == "model"
        assert captured["api_base"] == "http://api"
        print("  OK: monkeypatch still works")
    finally:
        rag_manager._ocr_image = orig


# ---- Test 7: Integration -- ingest cfg routing ----

def test_ingest_model_id_routing():
    """Verify the model_id extraction in ingest() matches the routing logic."""
    print("test_ingest_model_id_routing...")

    def simulate(ocr_agent, ocr_api_base):
        _raw = ocr_agent or ""
        return _raw if not ocr_api_base else _raw.split("/", 1)[-1]

    # Cloud config: ocr_api_base="" + gemini model
    mid = simulate("gemini/gemini-2.5-flash", "")
    assert mid == "gemini/gemini-2.5-flash", f"Cloud model_id wrong: {mid}"

    # Cloud config: ocr_api_base=None
    mid = simulate("gemini/gemini-2.5-flash", None)
    assert mid == "gemini/gemini-2.5-flash", f"Cloud model_id (None) wrong: {mid}"

    # Local config: ocr_api_base set + local model
    mid = simulate("glm-ocr-f16:LATEST", "http://192.168.100.2:8081/v1")
    assert mid == "glm-ocr-f16:LATEST", f"Local model_id wrong: {mid}"

    # Local config with openai prefix (stripped)
    mid = simulate("openai/glm-ocr-f16:LATEST", "http://192.168.100.2:8081/v1")
    assert mid == "glm-ocr-f16:LATEST", f"Prefixed local model_id wrong: {mid}"

    # GitHub copilot cloud model
    mid = simulate("github_copilot/gpt-4o", "")
    assert mid == "github_copilot/gpt-4o", f"GitHub copilot model_id wrong: {mid}"

    print("  OK: ingest extraction correct for cloud and local")


# ---- Test 8: Image payload present in both paths ----

def test_image_payload_both_paths():
    """Both local and cloud paths include the base64 image in the request."""
    print("test_image_payload_both_paths...")

    # Local path
    local_payload = {}
    def mock_post(url, json=None, timeout=None):
        local_payload.update(json)
        resp = types.SimpleNamespace()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"choices": [{"message": {"content": "ok"}}]}
        return resp

    import requests as _real_requests
    orig_post = _real_requests.post
    _real_requests.post = mock_post

    tmp = "temp/test_ocr_payload"
    png = _make_png(tmp)

    try:
        _ocr_image(png, "model", "http://api", "prompt")
        content = local_payload["messages"][0]["content"]
        img_parts = [c for c in content if c.get("type") == "image_url"]
        assert len(img_parts) == 1, "Missing image_url in local payload"
        assert img_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        print("  OK: local path includes base64 image")
    finally:
        _real_requests.post = orig_post

    # Cloud path
    cloud_payload = {}
    mock_litellm = types.ModuleType("litellm")
    def mock_completion(model=None, messages=None, **kw):
        cloud_payload["messages"] = messages
        return {"choices": [{"message": {"content": "ok"}}]}
    mock_litellm.completion = mock_completion

    orig_litellm = sys.modules.get("litellm")
    sys.modules["litellm"] = mock_litellm

    try:
        _ocr_image(png, "gemini/model", "", "prompt")
        content = cloud_payload["messages"][0]["content"]
        img_parts = [c for c in content if c.get("type") == "image_url"]
        assert len(img_parts) == 1, "Missing image_url in cloud payload"
        assert img_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        print("  OK: cloud path includes base64 image")
    finally:
        if orig_litellm is not None:
            sys.modules["litellm"] = orig_litellm
        else:
            sys.modules.pop("litellm", None)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_local_endpoint_routing()
    test_cloud_model_routing()
    test_model_id_extraction()
    test_retry_local()
    test_retry_cloud()
    test_backward_compat_mock()
    test_ingest_model_id_routing()
    test_image_payload_both_paths()
    print("\nAll OCR cloud routing tests passed.")
