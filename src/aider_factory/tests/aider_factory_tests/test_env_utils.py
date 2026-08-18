import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../python")))
from env_utils import is_dummy_key, load_env_files, resolve_api_key


class TestEnvUtils(unittest.TestCase):
    def setUp(self):
        self.old_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)

    def test_is_dummy_key(self):
        self.assertTrue(is_dummy_key(None))
        self.assertTrue(is_dummy_key(""))
        self.assertTrue(is_dummy_key("sk-dummy"))
        self.assertTrue(is_dummy_key("dummy"))
        self.assertTrue(is_dummy_key("none"))
        self.assertTrue(is_dummy_key("null"))
        self.assertTrue(is_dummy_key(" SK-DUMMY "))
        self.assertFalse(is_dummy_key("sk-valid-key-12345"))

    def test_load_env_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = os.path.join(tmpdir, ".env")
            with open(env_file, "w", encoding="utf-8") as f:
                f.write('export TEST_GEMINI_KEY="my-gemini-val"\n')
                f.write("TEST_UNQUOTED_KEY=my-unquoted-val # inline comment\n")
                f.write('# TEST_COMMENTED=ignored\n')

            os.environ.pop("TEST_GEMINI_KEY", None)
            os.environ.pop("TEST_UNQUOTED_KEY", None)

            load_env_files(cwd=tmpdir)

            self.assertEqual(os.environ.get("TEST_GEMINI_KEY"), "my-gemini-val")
            self.assertEqual(os.environ.get("TEST_UNQUOTED_KEY"), "my-unquoted-val")

    def test_resolve_api_key_local_endpoint(self):
        key = resolve_api_key(model="openai/gpt-4o", api_base="http://localhost:8080/v1")
        self.assertEqual(key, "sk-dummy")

        key_explicit = resolve_api_key(
            model="openai/gpt-4o",
            api_base="http://localhost:8080/v1",
            explicit_key="sk-real-local-key",
        )
        self.assertEqual(key_explicit, "sk-real-local-key")

    def test_resolve_api_key_cloud_gemini(self):
        for k in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "AIDER_GEMINI_API_KEY", "OPENAI_API_KEY", "ORACLE_AGENT_API_KEY"]:
            os.environ.pop(k, None)

        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        os.environ["GEMINI_API_KEY"] = "gemini-real-key"

        key = resolve_api_key(model="gemini/gemini-2.5-flash", api_base=None)
        self.assertEqual(key, "gemini-real-key")

    def test_resolve_api_key_cloud_anthropic(self):
        for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]:
            os.environ.pop(k, None)

        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        os.environ["ANTHROPIC_API_KEY"] = "anthropic-real-key"

        key = resolve_api_key(model="anthropic/claude-3-5-sonnet", api_base=None)
        self.assertEqual(key, "anthropic-real-key")

    def test_resolve_api_key_cloud_openai_dummy_filtering(self):
        for k in ["OPENAI_API_KEY", "GEMINI_API_KEY"]:
            os.environ.pop(k, None)

        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        key = resolve_api_key(model="openai/gpt-4o", api_base=None)
        self.assertIsNone(key)


if __name__ == "__main__":
    unittest.main()
