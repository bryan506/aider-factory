#!/usr/bin/env python3
# test_workspace_precedence.py — Unit tests verifying workspace-first asset precedence.

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

script_dir = os.path.dirname(os.path.abspath(__file__))
python_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_dir)
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../..")))

from run_workflow import resolve_template_path
import bootstrap


class TestWorkspacePrecedence(unittest.TestCase):
    def test_template_workspace_overrides_package(self):
        """Workspace-specific template in .aider_factory/markdown/templates/ takes precedence over package."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            custom_dir = os.path.join(tmp_dir, ".aider_factory", "markdown", "templates")
            os.makedirs(custom_dir, exist_ok=True)
            custom_file = os.path.join(custom_dir, "implement.md")
            with open(custom_file, "w", encoding="utf-8") as f:
                f.write("# CUSTOM WORKSPACE IMPLEMENT PLAN")

            resolved = resolve_template_path("markdown/templates/implement.md", project_directory=tmp_dir)
            self.assertEqual(os.path.abspath(resolved), os.path.abspath(custom_file))
            with open(resolved, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "# CUSTOM WORKSPACE IMPLEMENT PLAN")

    def test_template_relative_stripped_prefix(self):
        """Passing 'src/aider_factory/markdown/internal/analyze_bugs.md' resolves to local workspace first."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            custom_dir = os.path.join(tmp_dir, ".aider_factory", "markdown", "internal")
            os.makedirs(custom_dir, exist_ok=True)
            custom_file = os.path.join(custom_dir, "analyze_bugs.md")
            with open(custom_file, "w", encoding="utf-8") as f:
                f.write("# CUSTOM BUGS ANALYZER")

            resolved = resolve_template_path("src/aider_factory/markdown/internal/analyze_bugs.md", project_directory=tmp_dir)
            self.assertEqual(os.path.abspath(resolved), os.path.abspath(custom_file))
            with open(resolved, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "# CUSTOM BUGS ANALYZER")

    def test_template_flat_filename_fallback_in_workspace(self):
        """Passing bare filename 'testing.md' finds '.aider_factory/markdown/templates/testing.md' or '.aider_factory/markdown/testing.md'."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            custom_dir = os.path.join(tmp_dir, ".aider_factory", "markdown")
            os.makedirs(custom_dir, exist_ok=True)
            custom_file = os.path.join(custom_dir, "testing.md")
            with open(custom_file, "w", encoding="utf-8") as f:
                f.write("# CUSTOM FLAT TESTING TEMPLATE")

            resolved = resolve_template_path("testing.md", project_directory=tmp_dir)
            self.assertEqual(os.path.abspath(resolved), os.path.abspath(custom_file))

    def test_template_package_fallback_when_missing_locally(self):
        """When a template does not exist in workspace, falls back to package bundled resources."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Completely empty workspace
            resolved = resolve_template_path("markdown/templates/implement.md", project_directory=tmp_dir)
            self.assertIsNotNone(resolved)
            self.assertTrue(os.path.isfile(resolved))
            self.assertTrue(resolved.endswith("implement.md"))

    def test_conventions_workspace_precedence(self):
        """CONVENTIONS.md at root of workspace is chosen before package default."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            custom_conv = os.path.join(tmp_dir, "CONVENTIONS.md")
            with open(custom_conv, "w", encoding="utf-8") as f:
                f.write("# ROOT CONVENTIONS")

            resolved = resolve_template_path("CONVENTIONS.md", project_directory=tmp_dir)
            self.assertEqual(os.path.abspath(resolved), os.path.abspath(custom_conv))

    def test_strategy_template_workspace_precedence(self):
        """Strategy template in .aider_factory/markdown/oracle_pre_plan/ is resolved with workspace priority."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            strat_dir = os.path.join(tmp_dir, ".aider_factory", "markdown", "oracle_pre_plan")
            os.makedirs(strat_dir, exist_ok=True)
            strat_file = os.path.join(strat_dir, "strategy_template.md")
            with open(strat_file, "w", encoding="utf-8") as f:
                f.write("# CUSTOM STRATEGY TEMPLATE")

            resolved = resolve_template_path("markdown/oracle_pre_plan/strategy_template.md", project_directory=tmp_dir)
            self.assertEqual(os.path.abspath(resolved), os.path.abspath(strat_file))

    @patch("litellm.completion")
    def test_helper_workspace_docs_precedence(self, mock_completion):
        """Helper loads local .aider_factory/markdown/docs/yaml_docs_sample.md and skills before package defaults."""
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(delta=MagicMock(content="Reply"))]
        mock_completion.return_value = [mock_resp]

        with tempfile.TemporaryDirectory() as tmp_dir:
            orig_cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                docs_dir = os.path.join(".aider_factory", "markdown", "docs")
                skills_dir = os.path.join(".aider_factory", "markdown", "skills")
                os.makedirs(docs_dir, exist_ok=True)
                os.makedirs(skills_dir, exist_ok=True)

                with open(os.path.join(docs_dir, "yaml_docs_sample.md"), "w", encoding="utf-8") as f:
                    f.write("# WORKSPACE OVERRIDE YAML SAMPLE")
                with open(os.path.join(docs_dir, "factory_service_manual.md"), "w", encoding="utf-8") as f:
                    f.write("# WORKSPACE OVERRIDE SERVICE MANUAL")
                with open(os.path.join(skills_dir, "custom_skill.md"), "w", encoding="utf-8") as f:
                    f.write("# WORKSPACE CUSTOM SKILL")

                with patch("os.environ", {"GEMINI_API_KEY": "sk-test"}):
                    bootstrap.run_query("Explain config", None, "", ask_mode=True, expert_mode=True)

                call_msgs = mock_completion.call_args_list[-1][1]["messages"]
                user_content = call_msgs[1]["content"]
                self.assertIn("WORKSPACE OVERRIDE YAML SAMPLE", user_content)
                self.assertIn("WORKSPACE OVERRIDE SERVICE MANUAL", user_content)
                self.assertIn("File: custom_skill.md", user_content)
                self.assertIn("WORKSPACE CUSTOM SKILL", user_content)
            finally:
                os.chdir(orig_cwd)


if __name__ == "__main__":
    unittest.main()
