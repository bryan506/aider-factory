import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure src/aider_factory is in sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
pkg_dir = os.path.abspath(os.path.join(script_dir, "../../.."))
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

from aider_factory import cli


class TestCLISessionManagement(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.af_dir = os.path.join(self.test_dir, ".aider_factory")
        os.makedirs(self.af_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_side_session_artifacts_discovery(self):
        # Create root side sessions
        helper_sess = os.path.join(self.af_dir, ".helper_session.json")
        oracle_sess = os.path.join(self.af_dir, ".oracle_session.json")
        with open(helper_sess, "w", encoding="utf-8") as f:
            json.dump([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}], f)
        with open(oracle_sess, "w", encoding="utf-8") as f:
            json.dump({"messages": [{"role": "system", "content": "prompt"}]}, f)

        # Create session subdirectory side sessions
        sub_sess_dir = os.path.join(self.af_dir, "sessions", "my_session")
        os.makedirs(sub_sess_dir, exist_ok=True)
        sub_oracle = os.path.join(sub_sess_dir, ".oracle_session.json")
        with open(sub_oracle, "w", encoding="utf-8") as f:
            json.dump([{"role": "user", "content": "q"}], f)

        artifacts = cli._get_side_session_artifacts(self.test_dir)
        paths = [a["path"] for a in artifacts]
        self.assertIn(helper_sess, paths)
        self.assertIn(oracle_sess, paths)
        self.assertIn(sub_oracle, paths)

        # Verify turns parsing
        helper_art = next(a for a in artifacts if a["path"] == helper_sess)
        self.assertEqual(helper_art["turns"], 2)

    def test_clear_side_sessions_isolation(self):
        # Create side-agent files
        helper_sess = os.path.join(self.af_dir, ".helper_session.json")
        oracle_sess = os.path.join(self.af_dir, ".oracle_session.json")
        with open(helper_sess, "w", encoding="utf-8") as f:
            f.write("{}")
        with open(oracle_sess, "w", encoding="utf-8") as f:
            f.write("{}")

        # Create critical load-bearing config files that MUST NOT be touched
        env_yaml = os.path.join(self.af_dir, ".env.yml")
        conventions = os.path.join(self.af_dir, "CONVENTIONS.md")
        with open(env_yaml, "w", encoding="utf-8") as f:
            f.write("name: test\n")
        with open(conventions, "w", encoding="utf-8") as f:
            f.write("# Conventions\n")

        with patch("sys.stdout", new=io.StringIO()):
            cli._clear_side_sessions(self.test_dir)

        # Side session files deleted
        self.assertFalse(os.path.exists(helper_sess))
        self.assertFalse(os.path.exists(oracle_sess))

        # Core configs preserved
        self.assertTrue(os.path.exists(env_yaml))
        self.assertTrue(os.path.exists(conventions))

    def test_status_output_no_crash(self):
        stdout_capture = io.StringIO()
        with patch("sys.stdout", new=stdout_capture):
            cli._status(self.test_dir)
        out = stdout_capture.getvalue()
        self.assertIn("AI Factory Session & Cluster Status", out)
        self.assertIn("Main Aider Sessions", out)
        self.assertIn("Side-Agent Sessions & KV Caches", out)

    @patch("urllib.request.urlopen")
    def test_probe_and_release_cluster_slots(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps([
            {"id": 0, "is_processing": False, "state": 0},
            {"id": 1, "is_processing": True, "state": 1},
        ]).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        total, active, url = cli._probe_cluster_slots("http://192.168.100.1:8080/v1")
        self.assertEqual(total, 2)
        self.assertEqual(active, 1)

        released = cli._release_cluster_slots("http://192.168.100.1:8080/v1")
        self.assertEqual(released, 2)

    def test_global_registry_registration_and_pruning(self):
        reg_file = os.path.join(self.test_dir, "fake_reg.json")
        with patch("aider_factory.cli._get_registry_path", return_value=reg_file):
            proj_1 = os.path.join(self.test_dir, "proj_1")
            proj_2 = os.path.join(self.test_dir, "proj_2")
            os.makedirs(os.path.join(proj_1, ".aider_factory"), exist_ok=True)
            os.makedirs(os.path.join(proj_2, ".aider_factory"), exist_ok=True)

            cli._register_project(proj_1)
            cli._register_project(proj_2)

            projects = cli._get_registered_projects()
            self.assertIn(os.path.abspath(proj_1), projects)
            self.assertIn(os.path.abspath(proj_2), projects)

            # Prune test: remove proj_2 from disk
            import shutil
            shutil.rmtree(proj_2)
            projects_after = cli._get_registered_projects()
            self.assertIn(os.path.abspath(proj_1), projects_after)
            self.assertNotIn(os.path.abspath(proj_2), projects_after)

    def test_clear_side_session_by_name_aliases(self):
        # Create helper and oracle files
        helper_file = os.path.join(self.af_dir, ".helper_session.json")
        oracle_file = os.path.join(self.af_dir, ".oracle_session.json")
        sess_oracle = os.path.join(self.af_dir, "sessions", "worker_1", ".oracle_session.json")
        os.makedirs(os.path.dirname(sess_oracle), exist_ok=True)

        for p in [helper_file, oracle_file, sess_oracle]:
            with open(p, "w", encoding="utf-8") as f:
                f.write("{}")

        with patch("sys.stdout", new=io.StringIO()):
            # Clear helper only
            cli._clear_side_session_by_name(self.test_dir, "helper")
            self.assertFalse(os.path.exists(helper_file))
            self.assertTrue(os.path.exists(oracle_file))
            self.assertTrue(os.path.exists(sess_oracle))

            # Clear session worker_1 oracle only
            cli._clear_side_session_by_name(self.test_dir, "worker_1")
            self.assertFalse(os.path.exists(sess_oracle))
            self.assertTrue(os.path.exists(oracle_file))

            # Clear root oracle
            cli._clear_side_session_by_name(self.test_dir, "oracle")
            self.assertFalse(os.path.exists(oracle_file))


if __name__ == "__main__":
    unittest.main()
