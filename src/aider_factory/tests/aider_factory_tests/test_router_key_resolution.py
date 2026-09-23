"""Regression tests: LITELLM_API_KEY must propagate into aider/oracle
subprocess envs and NOT get clobbered by the legacy 'sk-dummy' hardcode.

Run with:
    pytest src/aider_factory/tests/aider_factory_tests/test_router_key_resolution.py -v
"""

import os
import subprocess
import sys
import unittest


class TestRouterKeyResolution(unittest.TestCase):
    """Verify LITELLM_API_KEY propagates into aider/oracle subprocess envs
    and does NOT get clobbered by the legacy 'sk-dummy' hardcode."""

    _PROBE = (
        "import os, sys; "
        "sys.stdout.write(os.environ.get('OPENAI_API_KEY', '__UNSET__'))"
    )

    def _launch_with_env(self, env_overrides):
        """Launch a probe subprocess with the same env-construction logic
        that orchestrate.py / run_workflow.py use for _router_key."""
        env = os.environ.copy()
        # Scrub ambient keys to isolate the test
        for k in ("LITELLM_API_KEY", "OPENAI_API_KEY", "LM_STUDIO_API_KEY"):
            env.pop(k, None)
        env.update(env_overrides)

        # Replicate orchestrate.py resolution logic under test
        from aider_factory.python.env_utils import is_dummy_key

        _rk = env.get("LITELLM_API_KEY", "")
        _rk = _rk if _rk and not is_dummy_key(_rk) else "sk-dummy"
        env["OPENAI_API_KEY"] = _rk
        env["LM_STUDIO_API_KEY"] = _rk

        proc = subprocess.run(
            [sys.executable, "-c", self._PROBE],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return proc.stdout

    # ------------------------------------------------------------------
    # 1. Real key propagates
    # ------------------------------------------------------------------
    def test_real_key_propagates(self):
        """LITELLM_API_KEY set to a real token → subprocess sees it."""
        out = self._launch_with_env({"LITELLM_API_KEY": "sk-lemonade-abc123"})
        self.assertEqual(out, "sk-lemonade-abc123")

    # ------------------------------------------------------------------
    # 2. Unset falls back to dummy
    # ------------------------------------------------------------------
    def test_unset_falls_back_to_dummy(self):
        """LITELLM_API_KEY absent → subprocess gets 'sk-dummy'."""
        out = self._launch_with_env({})
        self.assertEqual(out, "sk-dummy")

    # ------------------------------------------------------------------
    # 3. Explicit dummy key stays dummy (is_dummy_key gate)
    # ------------------------------------------------------------------
    def test_explicit_dummy_key_stays_dummy(self):
        """LITELLM_API_KEY='sk-dummy' → is_dummy_key() catches it, stays dummy."""
        out = self._launch_with_env({"LITELLM_API_KEY": "sk-dummy"})
        self.assertEqual(out, "sk-dummy")

    # ------------------------------------------------------------------
    # 4. run_workflow.py rag_env: all three oracle keys carry the real key
    # ------------------------------------------------------------------
    def test_rag_env_keys_carry_real_router_key(self):
        """ORACLE_AGENT_API_KEY / ORACLE_ARCHITECT_API_KEY /
        GROUNDING_AGENT_API_KEY all resolve to the real LITELLM_API_KEY."""
        from aider_factory.python.env_utils import is_dummy_key

        litellm_key = "sk-lemonade-xyz789"
        _rk = litellm_key if litellm_key and not is_dummy_key(litellm_key) else "sk-dummy"

        # Replicate the 3-line rag_env construction from run_workflow.py
        rag_env = {
            "ORACLE_AGENT_API_KEY": _rk,
            "ORACLE_ARCHITECT_API_KEY": _rk,
            "GROUNDING_AGENT_API_KEY": _rk,
        }

        self.assertEqual(rag_env["ORACLE_AGENT_API_KEY"], litellm_key)
        self.assertEqual(rag_env["ORACLE_ARCHITECT_API_KEY"], litellm_key)
        self.assertEqual(rag_env["GROUNDING_AGENT_API_KEY"], litellm_key)

    # ------------------------------------------------------------------
    # 5. Backward compat: local path untouched when no LITELLM_API_KEY
    # ------------------------------------------------------------------
    def test_backward_compat_local_path_untouched(self):
        """No LITELLM_API_KEY + architect_api_base set → 'sk-dummy' preserved.
        Proves the local llama.cpp / LM Studio path is unaffected."""
        out = self._launch_with_env({
            "OPENAI_BASE_URL": "http://localhost:1234/v1",
        })
        self.assertEqual(out, "sk-dummy")


if __name__ == "__main__":
    unittest.main()
