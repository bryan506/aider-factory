#!/usr/bin/env python3
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../../../python")))
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../../..")))

import cli

print("==================================================")
print("Starting E2E Factory Quickstart Smoke Test...")
print("==================================================")

@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
@patch("requests.get")
def run_e2e_test(mock_get, mock_sub, mock_bash, mock_searxng):
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        
        # Mock cluster response to simulate the Lemonade server
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "qwen-e2e-model"}]}
        mock_get.return_value = mock_resp
        
        try:
            with patch.dict("os.environ", {"LITELLM_BASE_URL": "http://e2e-cluster:8080/v1", "LITELLM_API_KEY": "dummy"}):
                cli.init_user_project(tmp_dir)
                
                env_yaml = os.path.join(".aider_factory", ".env.yml")
                assert os.path.exists(env_yaml), "YAML must be created"
                
                with open(env_yaml, "r") as f:
                    content = f.read()
                
                assert 'architect_api_base: "http://e2e-cluster:8080/v1"' in content, "Cluster API must be injected"
                assert 'architect_agent: "qwen-e2e-model"' in content, "Cluster model must be injected"
                assert 'target_files:\n        - "scratchpad.py"' in content, "Scratchpad must be injected"
                
                print("  ✅ E2E Factory Quickstart Cluster Discovery PASS")
        finally:
            os.chdir(original_cwd)

if __name__ == "__main__":
    run_e2e_test()
    print("\n🎉 E2E Factory Quickstart Test Completed Successfully!")
