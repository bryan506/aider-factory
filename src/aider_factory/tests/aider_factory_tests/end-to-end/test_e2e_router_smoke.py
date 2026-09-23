"""E2E smoke test: LITELLM_API_KEY must propagate through orchestrate.py's
env-construction path and be accepted by a live LiteLLM router.

Zero-Mock Mandate (CONVENTIONS §2):
  - No patch(), no MagicMock, no stub server.
  - Real `aider` binary in a temp git sandbox.
  - Assert on real OS exit code 0.
  - Assert stderr/stdout does NOT contain AuthenticationError.

Prerequisites (must be exported before running):
    export LITELLM_API_KEY="sk-..."
    export LITELLM_BASE_URL="http://host:port/v1"
    # optional: export LEMONADE_MODEL="openai/glm-5.3"

Run:
    pytest -s src/aider_factory/tests/aider_factory_tests/end-to-end/test_e2e_router_smoke.py -v
"""

import os
import subprocess
import sys
import tempfile
import unittest

from aider_factory.python.env_utils import is_dummy_key

_ROUTER_KEY = os.environ.get("LITELLM_API_KEY", "")
_ROUTER_BASE = os.environ.get("LITELLM_BASE_URL", "")
_ROUTER_MODEL = os.environ.get(
    "LEMONADE_MODEL", os.environ.get("AIDER_HELPER_MODEL", "")
)

_SKIP_MSG = (
    "LITELLM_API_KEY and LITELLM_BASE_URL must be exported for live router E2E. "
    "Skipping."
)


def _resolve_router_key(env: dict) -> str:
    """Replicate the exact resolution from orchestrate.py / run_workflow.py."""
    rk = env.get("LITELLM_API_KEY", "")
    return rk if rk and not is_dummy_key(rk) else "sk-dummy"


def _discover_models() -> list[str]:
    """Query the live router's GET /v1/models. Returns sorted model IDs
    or empty list on failure. Uses the same auth path as production."""
    from aider_factory.python.env_utils import probe_router
    return probe_router(_ROUTER_BASE, _ROUTER_KEY) or []


@unittest.skipUnless(
    _ROUTER_KEY and not is_dummy_key(_ROUTER_KEY) and _ROUTER_BASE,
    _SKIP_MSG,
)
class TestE2ERouterSmoke(unittest.TestCase):
    """Real aider subprocess against a live LiteLLM router."""

    def setUp(self):
        # Discover available models ONCE per test (proves the router is alive
        # and the token is valid before we even spawn aider).
        self._available_models = _discover_models()
        _masked_base = _ROUTER_BASE.rsplit("/", 2)[0] + "/***" if _ROUTER_BASE else "(unset)"
        print(f"\n🔍 Router reachable at {_masked_base} — {len(self._available_models)} model(s): {self._available_models}")
        if not self._available_models:
            self.skipTest(
                f"Router at {_ROUTER_BASE} returned 0 models or was unreachable. "
                f"Token may be invalid or router is down."
            )
        # Resolve the model to use: explicit env > first available > skip
        self._model = _ROUTER_MODEL
        if not self._model:
            self._model = self._available_models[0]
        elif self._model not in self._available_models:
            self.skipTest(
                f"Configured model '{self._model}' not found on router. "
                f"Available: {self._available_models[:10]}"
            )
        print(f"🎯 Selected model: {self._model}")
        print(f"🔑 Token: {'set' if _ROUTER_KEY else 'unset'} ({len(_ROUTER_KEY)} chars)")

        self.tmp = tempfile.TemporaryDirectory()
        self.project_dir = self.tmp.name
        subprocess.run(
            ["git", "init"],
            cwd=self.project_dir,
            capture_output=True,
            check=True,
        )
        # Trivial file so aider has something in the repo map
        target = os.path.join(self.project_dir, "hello.py")
        with open(target, "w") as f:
            f.write("print('hello')\n")
        subprocess.run(
            ["git", "add", "hello.py"],
            cwd=self.project_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=self.project_dir,
            capture_output=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _build_env(self):
        """Construct the subprocess env exactly as orchestrate.py does."""
        env = os.environ.copy()
        # Scrub ambient provider keys to prove LITELLM_API_KEY is the sole source
        for k in ("OPENAI_API_KEY", "LM_STUDIO_API_KEY", "GEMINI_API_KEY"):
            env.pop(k, None)

        _rk = _resolve_router_key(env)
        env["OPENAI_API_BASE"] = _ROUTER_BASE
        env["OPENAI_API_KEY"] = _rk
        env["LM_STUDIO_API_BASE"] = _ROUTER_BASE
        env["LM_STUDIO_API_KEY"] = _rk
        return env

    # ------------------------------------------------------------------
    # 1. aider architect turn: real model call through the router
    # ------------------------------------------------------------------
    def test_aider_ask_turn_router_auth(self):
        """Spawn aider in ask-mode against the live router. Must exit 0,
        produce real inference text, and NOT surface an AuthenticationError."""
        env = self._build_env()
        cmd = [
            "aider",
            "--model", self._model,
            "--edit-format", "ask",
            "--message", "Reply with exactly the word: ROUTER_OK",
            "--exit",
            "--yes-always",
            "--no-auto-commits",
            "--no-check-update",
            "--no-show-release-notes",
            "--no-notifications",
            "--no-analytics",
            "--no-pretty",
            "--map-tokens", "0",
        ]
        proc = subprocess.run(
            cmd,
            cwd=self.project_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")

        # Print evidence so -s shows what actually happened
        print(f"\n📝 aider stdout ({len(proc.stdout or '')} chars):")
        print(proc.stdout[-1500:] if proc.stdout else "(empty)")
        print(f"\n📝 aider stderr ({len(proc.stderr or '')} chars):")
        print(proc.stderr[-500:] if proc.stderr else "(empty)")
        print(f"🚪 exit code: {proc.returncode}")

        # Hard: exit code
        self.assertEqual(
            proc.returncode, 0,
            msg=f"aider exited {proc.returncode}:\n{combined[-2000:]}",
        )
        # Hard: no auth failure
        self.assertNotIn(
            "AuthenticationError", combined,
            msg=f"Router rejected the propagated key:\n{combined[-2000:]}",
        )
        self.assertNotIn(
            "invalid proxy server token", combined,
            msg=f"Router token validation failed:\n{combined[-2000:]}",
        )
        # Hard: model produced real inference (not empty, not a connection error)
        self.assertTrue(
            len(proc.stdout.strip()) > 5,
            msg=f"Model returned no real inference. stdout={proc.stdout!r}\n"
                f"Model used: {self._model}\n"
                f"Router: {_ROUTER_BASE}\n"
                f"Available models: {self._available_models[:5]}",
        )
        # Soft: the model actually responded with something (may include ROUTER_OK
        # but LLMs don't always obey verbatim; we just need non-empty inference)
        # Check aider's LLM history for proof of a real API round-trip
        llm_hist = os.path.join(self.project_dir, ".aider.llm.history")
        if not os.path.isfile(llm_hist):
            llm_hist = os.path.join(
                self.project_dir, ".aider_factory", ".aider.llm.history"
            )
        if os.path.isfile(llm_hist):
            with open(llm_hist, "r") as f:
                hist = f.read()
            # aider records the model name and token counts on every real call
            self.assertIn(self._model, hist,
                          msg=f"LLM history does not reference model '{self._model}'")
            self.assertIn("completion_tokens", hist,
                          msg="No token usage recorded — no real API call was made")

    # ------------------------------------------------------------------
    # 2. aider edit turn: verify the editor model also authenticates
    # ------------------------------------------------------------------
    def test_aider_edit_turn_router_auth(self):
        """Spawn aider in edit-mode. The editor model call must also
        pass router auth (same env, different code path in aider)."""
        env = self._build_env()
        target = os.path.join(self.project_dir, "hello.py")
        cmd = [
            "aider",
            "--model", self._model,
            "--editor-model", self._model,
            "--message", "Add a comment '# router-smoke-test' as the first line of the file",
            "--yes-always",
            "--no-auto-commits",
            "--no-check-update",
            "--no-show-release-notes",
            "--no-notifications",
            "--no-analytics",
            "--no-pretty",
            "--map-tokens", "0",
            "--exit",
            target,
        ]
        proc = subprocess.run(
            cmd,
            cwd=self.project_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")

        self.assertEqual(
            proc.returncode, 0,
            msg=f"aider edit exited {proc.returncode}:\n{combined[-2000:]}",
        )
        self.assertNotIn("AuthenticationError", combined)

        # Assert physical disk modification (Zero-Mock: real file change)
        with open(target, "r") as f:
            content = f.read()
        self.assertIn("router-smoke-test", content,
                      msg=f"File was not edited:\n{content}")

    # ------------------------------------------------------------------
    # 3. Oracle subprocess: ORACLE_AGENT_API_KEY must carry the real token
    # ------------------------------------------------------------------
    def test_oracle_cli_router_auth(self):
        """Spawn aider-oracle with the rag_env-style ORACLE_* keys.
        Must exit 0 against the live router."""
        env = self._build_env()
        _rk = env["OPENAI_API_KEY"]
        env["ORACLE_AGENT_API_BASE"] = _ROUTER_BASE
        env["ORACLE_AGENT_API_KEY"] = _rk
        env["ORACLE_AGENT_MODEL"] = self._model
        env["ORACLE_RETRIEVE_MODE"] = "no_retrieve"

        cmd = [
            "aider-oracle",
            "--mode", "no_retrieve",
            "Say exactly: ORACLE_OK",
        ]
        proc = subprocess.run(
            cmd,
            cwd=self.project_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")

        self.assertEqual(
            proc.returncode, 0,
            msg=f"aider-oracle exited {proc.returncode}:\n{combined[-2000:]}",
        )
        self.assertNotIn("AuthenticationError", combined)


if __name__ == "__main__":
    unittest.main()
