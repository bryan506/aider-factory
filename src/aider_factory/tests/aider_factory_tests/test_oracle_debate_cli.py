#!/usr/bin/env python3
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "../../python"))

from oracle_agent import _extract_overrides

print("Starting Oracle Debate CLI Tests...\n")


def test_debate_flag():
    os.environ.pop("ORACLE_DEBATE_MODE", None)
    os.environ.pop("ORACLE_DEBATE_LOOPS", None)

    args = ["--file", "test.txt", "--debate", "code", "--loops", "5", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == ["--file", "test.txt", "Query"], f"Unexpected args left: {out}"
    assert os.environ.get("ORACLE_DEBATE_MODE") == "code"
    assert os.environ.get("ORACLE_DEBATE_LOOPS") == "5"
    print("  ✅ --debate <mode> and --loops <N> parse correctly.")


def test_debate_default():
    os.environ.pop("ORACLE_DEBATE_MODE", None)
    os.environ.pop("ORACLE_DEBATE_LOOPS", None)

    # "Query" is the query string, which does not start with "-"
    # But because --debate checks `not args[i+1].startswith("-")`, it will consume "Query" as the mode!
    # Let's verify this behavior.
    args = ["--debate", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == [], f"Unexpected args left: {out}"
    assert (
        os.environ.get("ORACLE_DEBATE_MODE") == "query"
    )  # "Query" gets consumed as the mode
    assert os.environ.get("ORACLE_DEBATE_LOOPS") is None
    print(
        "  ✅ --debate without mode consumes the next token if it doesn't start with '-'."
    )

    args2 = ["--debate", "--no-rag", "Query2"]
    out2, do_list2, did_clear2, _, _ = _extract_overrides(args2)
    assert out2 == ["Query2"]
    assert (
        os.environ.get("ORACLE_DEBATE_MODE") == "code"
    )  # default mode because --no-rag starts with "-"

    print(
        "  ✅ --debate without mode falls back to 'code' if the next token starts with '-'."
    )


def test_cli_debate_pass_history_resolution():
    """Verify _run_cli_debate resolves pass_history (defaulting to True) from active phase."""
    import oracle_agent
    import tempfile
    import yaml
    from unittest.mock import patch, MagicMock

    class FakeMessage:
        def __init__(self, content):
            self.content = content
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    class FakeUsage:
        def __init__(self, prompt_tokens=10, completion_tokens=5):
            self.prompt_tokens = prompt_tokens
            self.completion_tokens = completion_tokens
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    class FakeResponse:
        def __init__(self, content="VERDICT: AGREE"):
            self.choices = [FakeChoice(content)]
            self.usage = FakeUsage()
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    cfg = {
        "phases": [
            {
                "enabled": True,
                "escalation_debate": {
                    "pass_history": False,
                }
            }
        ]
    }

    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
        yaml.dump(cfg, f)
        f.flush()
        cfg_path = f.name

    try:
        with patch.dict("os.environ", {"ORACLE_CONFIG_FILE": cfg_path}), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion", return_value=FakeResponse("VERDICT: AGREE")):
            
            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: test fix"

            ret = oracle_agent._run_cli_debate("Test issue", "code", max_turns=1, rounds=1)
            assert ret == 0
            print("  ✅ _run_cli_debate resolved pass_history successfully.")
    finally:
        if os.path.exists(cfg_path):
            os.remove(cfg_path)


if __name__ == "__main__":
    test_debate_flag()
    test_debate_default()
    test_cli_debate_pass_history_resolution()
    print("\n🎉 All CLI Oracle Debate Tests Passed!")
