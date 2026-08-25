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

    # Removed deprecated test_probe_and_release_cluster_slots

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

    def test_apply_session_resolution_and_discovery(self):
        import time
        from aider_factory.python.apply_agent import find_active_session_chat_history

        sess_dir1 = os.path.join(self.af_dir, "sessions", "worker_1")
        sess_dir2 = os.path.join(self.af_dir, "sessions", "worker_2")
        os.makedirs(sess_dir1, exist_ok=True)
        os.makedirs(sess_dir2, exist_ok=True)

        h1 = os.path.join(sess_dir1, ".aider.chat.history.md")
        h2 = os.path.join(sess_dir2, ".aider.chat.history.md")

        with open(h1, "w", encoding="utf-8") as f:
            f.write("worker_1 history")
        time.sleep(0.01)
        with open(h2, "w", encoding="utf-8") as f:
            f.write("worker_2 history")

        # Explicit
        path, name = find_active_session_chat_history(self.test_dir, session_name="worker_1")
        self.assertEqual(path, h1)
        self.assertEqual(name, "worker_1")

        # Auto-discovery by mtime
        path, name = find_active_session_chat_history(self.test_dir)
        self.assertEqual(path, h2)
        self.assertEqual(name, "worker_2")

    def test_backup_workspace_cache_isolated(self):
        cache_dir = os.path.join(self.test_dir, "cache")
        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}):
            proj_name = os.path.basename(self.test_dir)
            test_file = os.path.join(self.af_dir, "test_file.txt")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("sample backup data")

            cli._backup_workspace_cache(self.test_dir)

            dest_file = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", "test_file.txt")
            self.assertTrue(os.path.exists(dest_file))
            with open(dest_file, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "sample backup data")

    def test_backup_workspace_cache_rsync_fallback(self):
        cache_dir = os.path.join(self.test_dir, "cache_fallback")
        proj_name = os.path.basename(self.test_dir)
        test_file = os.path.join(self.af_dir, "fallback_test.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("copytree fallback content")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), patch("shutil.which", return_value=None):
            cli._backup_workspace_cache(self.test_dir)

            dest_file = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", "fallback_test.txt")
            self.assertTrue(os.path.exists(dest_file))
            with open(dest_file, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "copytree fallback content")

    def test_backup_workspace_cache_missing_dir(self):
        cache_dir = os.path.join(self.test_dir, "cache_missing")
        empty_proj = os.path.join(self.test_dir, "empty_proj")
        os.makedirs(empty_proj, exist_ok=True)

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}):
            cli._backup_workspace_cache(empty_proj)
            self.assertFalse(os.path.exists(os.path.join(cache_dir, "aider_factory_cache")))

    def test_clear_session_backup_vs_forever(self):
        cache_dir = os.path.join(self.test_dir, "cache")
        proj_name = os.path.basename(self.test_dir)
        sess_dir1 = os.path.join(self.af_dir, "sessions", "sess_backup")
        os.makedirs(sess_dir1, exist_ok=True)
        with open(os.path.join(sess_dir1, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: sess_backup\n")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), patch("sys.stdout", new=io.StringIO()):
            # 1. Clear session with default forever=False -> backs up to cache
            cli._clear_session(self.test_dir, "sess_backup", forever=False)
            self.assertFalse(os.path.exists(sess_dir1))
            cached_yml = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", "sessions", "sess_backup", "session.yml")
            self.assertTrue(os.path.exists(cached_yml))

            # 2. Clear session with forever=True -> does not write to cache
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)
            sess_dir2 = os.path.join(self.af_dir, "sessions", "sess_forever")
            os.makedirs(sess_dir2, exist_ok=True)
            with open(os.path.join(sess_dir2, "session.yml"), "w", encoding="utf-8") as f:
                f.write("name: sess_forever\n")

            cli._clear_session(self.test_dir, "sess_forever", forever=True)
            self.assertFalse(os.path.exists(sess_dir2))
            cached_forever = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", "sessions", "sess_forever")
            self.assertFalse(os.path.exists(cached_forever))

    def test_clear_all_sessions_backup_vs_forever(self):
        cache_dir = os.path.join(self.test_dir, "cache")
        proj_name = os.path.basename(self.test_dir)
        sess_dir = os.path.join(self.af_dir, "sessions", "work_sess")
        os.makedirs(sess_dir, exist_ok=True)
        with open(os.path.join(sess_dir, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: work_sess\n")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), patch("sys.stdout", new=io.StringIO()):
            cli._clear_all_sessions(self.test_dir, forever=False)
            self.assertFalse(os.path.exists(sess_dir))
            cached_sess = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", "sessions", "work_sess", "session.yml")
            self.assertTrue(os.path.exists(cached_sess))

    def test_clear_side_sessions_backup_vs_forever(self):
        cache_dir = os.path.join(self.test_dir, "cache")
        proj_name = os.path.basename(self.test_dir)
        helper_file = os.path.join(self.af_dir, ".helper_session.json")
        with open(helper_file, "w", encoding="utf-8") as f:
            f.write("[{\"role\": \"user\", \"content\": \"test\"}]")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), patch("sys.stdout", new=io.StringIO()):
            # 1. Default (forever=False) -> backs up
            cli._clear_side_sessions(self.test_dir, forever=False)
            self.assertFalse(os.path.exists(helper_file))
            cached_helper = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", ".helper_session.json")
            self.assertTrue(os.path.exists(cached_helper))

            # 2. With forever=True -> does not write to cache
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)
            oracle_file = os.path.join(self.af_dir, ".oracle_session.json")
            with open(oracle_file, "w", encoding="utf-8") as f:
                f.write("{}")

            cli._clear_side_sessions(self.test_dir, forever=True)
            self.assertFalse(os.path.exists(oracle_file))
            self.assertFalse(os.path.exists(os.path.join(cache_dir, "aider_factory_cache")))

    def test_clear_side_session_by_name_backup_vs_forever(self):
        cache_dir = os.path.join(self.test_dir, "cache_side_name")
        proj_name = os.path.basename(self.test_dir)
        oracle_file = os.path.join(self.af_dir, ".oracle_session.json")
        with open(oracle_file, "w", encoding="utf-8") as f:
            f.write("{\"messages\": []}")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), patch("sys.stdout", new=io.StringIO()):
            # 1. Clear oracle with default forever=False -> backs up
            cli._clear_side_session_by_name(self.test_dir, "oracle", forever=False)
            self.assertFalse(os.path.exists(oracle_file))
            cached_oracle = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", ".oracle_session.json")
            self.assertTrue(os.path.exists(cached_oracle))

            # 2. Clear helper with forever=True -> skips backup
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)
            helper_file = os.path.join(self.af_dir, ".helper_session.json")
            with open(helper_file, "w", encoding="utf-8") as f:
                f.write("[]")

            cli._clear_side_session_by_name(self.test_dir, "helper", forever=True)
            self.assertFalse(os.path.exists(helper_file))
            self.assertFalse(os.path.exists(os.path.join(cache_dir, "aider_factory_cache")))

    def test_clear_all_sessions_global_backup(self):
        cache_dir = os.path.join(self.test_dir, "cache_global_all")
        reg_file = os.path.join(self.test_dir, "fake_reg.json")
        proj1 = os.path.join(self.test_dir, "proj1")
        proj2 = os.path.join(self.test_dir, "proj2")
        sess1 = os.path.join(proj1, ".aider_factory", "sessions", "s1")
        sess2 = os.path.join(proj2, ".aider_factory", "sessions", "s2")
        os.makedirs(sess1, exist_ok=True)
        os.makedirs(sess2, exist_ok=True)
        with open(os.path.join(sess1, "session.yml"), "w", encoding="utf-8") as f:
            f.write("proj1")
        with open(os.path.join(sess2, "session.yml"), "w", encoding="utf-8") as f:
            f.write("proj2")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), \
             patch("aider_factory.cli._get_registry_path", return_value=reg_file), \
             patch("sys.stdout", new=io.StringIO()):
            cli._register_project(proj1)
            cli._register_project(proj2)

            cli._clear_all_sessions(self.test_dir, is_global=True, forever=False)

            self.assertFalse(os.path.exists(sess1))
            self.assertFalse(os.path.exists(sess2))
            self.assertTrue(os.path.exists(os.path.join(cache_dir, "aider_factory_cache", "proj1", ".aider_factory", "sessions", "s1", "session.yml")))
            self.assertTrue(os.path.exists(os.path.join(cache_dir, "aider_factory_cache", "proj2", ".aider_factory", "sessions", "s2", "session.yml")))

    def test_clear_side_sessions_global_backup(self):
        cache_dir = os.path.join(self.test_dir, "cache_global_side")
        reg_file = os.path.join(self.test_dir, "fake_reg.json")
        proj1 = os.path.join(self.test_dir, "proj1")
        proj2 = os.path.join(self.test_dir, "proj2")
        af1 = os.path.join(proj1, ".aider_factory")
        af2 = os.path.join(proj2, ".aider_factory")
        os.makedirs(af1, exist_ok=True)
        os.makedirs(af2, exist_ok=True)
        h1 = os.path.join(af1, ".helper_session.json")
        h2 = os.path.join(af2, ".helper_session.json")
        with open(h1, "w", encoding="utf-8") as f:
            f.write("[]")
        with open(h2, "w", encoding="utf-8") as f:
            f.write("[]")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), \
             patch("aider_factory.cli._get_registry_path", return_value=reg_file), \
             patch("sys.stdout", new=io.StringIO()):
            cli._register_project(proj1)
            cli._register_project(proj2)

            cli._clear_side_sessions(self.test_dir, is_global=True, forever=False)

            self.assertFalse(os.path.exists(h1))
            self.assertFalse(os.path.exists(h2))
            self.assertTrue(os.path.exists(os.path.join(cache_dir, "aider_factory_cache", "proj1", ".aider_factory", ".helper_session.json")))
            self.assertTrue(os.path.exists(os.path.join(cache_dir, "aider_factory_cache", "proj2", ".aider_factory", ".helper_session.json")))

    def test_main_cli_clear_all_default_vs_forever(self):
        cache_dir = os.path.join(self.test_dir, "cache_cli_all")
        proj_name = os.path.basename(self.test_dir)
        sess_dir = os.path.join(self.af_dir, "sessions", "cli_all_sess")
        os.makedirs(sess_dir, exist_ok=True)
        with open(os.path.join(sess_dir, "session.yml"), "w", encoding="utf-8") as f:
            f.write("cli_all_sess")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), \
             patch("os.getcwd", return_value=self.test_dir), \
             patch("sys.stdout", new=io.StringIO()):
            # 1. CLI --clear-all (default: backup)
            with patch.object(sys, "argv", ["aider-factory", "--clear-all"]):
                with self.assertRaises(SystemExit) as cm:
                    cli.main()
                self.assertEqual(cm.exception.code, 0)
            self.assertFalse(os.path.exists(sess_dir))
            cached_yml = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", "sessions", "cli_all_sess", "session.yml")
            self.assertTrue(os.path.exists(cached_yml))

            # 2. CLI --clear-all --forever (no backup)
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)
            sess_dir2 = os.path.join(self.af_dir, "sessions", "cli_all_sess2")
            os.makedirs(sess_dir2, exist_ok=True)
            with open(os.path.join(sess_dir2, "session.yml"), "w", encoding="utf-8") as f:
                f.write("cli_all_sess2")

            with patch.object(sys, "argv", ["aider-factory", "--clear-all", "--forever"]):
                with self.assertRaises(SystemExit) as cm:
                    cli.main()
                self.assertEqual(cm.exception.code, 0)
            self.assertFalse(os.path.exists(sess_dir2))
            self.assertFalse(os.path.exists(os.path.join(cache_dir, "aider_factory_cache")))

    def test_main_cli_clear_session_default_vs_forever(self):
        cache_dir = os.path.join(self.test_dir, "cache_cli_sess")
        proj_name = os.path.basename(self.test_dir)
        sess_dir = os.path.join(self.af_dir, "sessions", "target_sess")
        os.makedirs(sess_dir, exist_ok=True)
        with open(os.path.join(sess_dir, "session.yml"), "w", encoding="utf-8") as f:
            f.write("target_sess")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), \
             patch("os.getcwd", return_value=self.test_dir), \
             patch("sys.stdout", new=io.StringIO()):
            # 1. Clear session default -> backup
            with patch.object(sys, "argv", ["aider-factory", "--clear-session", "target_sess"]):
                with self.assertRaises(SystemExit) as cm:
                    cli.main()
                self.assertEqual(cm.exception.code, 0)
            self.assertFalse(os.path.exists(sess_dir))
            cached_yml = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", "sessions", "target_sess", "session.yml")
            self.assertTrue(os.path.exists(cached_yml))

            # 2. Clear session --forever -> no backup
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)
            sess_dir2 = os.path.join(self.af_dir, "sessions", "target_sess2")
            os.makedirs(sess_dir2, exist_ok=True)
            with open(os.path.join(sess_dir2, "session.yml"), "w", encoding="utf-8") as f:
                f.write("target_sess2")

            with patch.object(sys, "argv", ["aider-factory", "--clear-session", "target_sess2", "--forever"]):
                with self.assertRaises(SystemExit) as cm:
                    cli.main()
                self.assertEqual(cm.exception.code, 0)
            self.assertFalse(os.path.exists(sess_dir2))
            self.assertFalse(os.path.exists(os.path.join(cache_dir, "aider_factory_cache")))

    def test_main_cli_clear_side_sessions_default_vs_forever(self):
        cache_dir = os.path.join(self.test_dir, "cache_cli_sides")
        proj_name = os.path.basename(self.test_dir)
        helper_file = os.path.join(self.af_dir, ".helper_session.json")
        with open(helper_file, "w", encoding="utf-8") as f:
            f.write("[]")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), \
             patch("os.getcwd", return_value=self.test_dir), \
             patch("sys.stdout", new=io.StringIO()):
            # 1. Clear side sessions -> backup
            with patch.object(sys, "argv", ["aider-factory", "--clear-side-sessions"]):
                with self.assertRaises(SystemExit) as cm:
                    cli.main()
                self.assertEqual(cm.exception.code, 0)
            self.assertFalse(os.path.exists(helper_file))
            cached_helper = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", ".helper_session.json")
            self.assertTrue(os.path.exists(cached_helper))

            # 2. Clear side sessions --forever -> no backup
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)
            oracle_file = os.path.join(self.af_dir, ".oracle_session.json")
            with open(oracle_file, "w", encoding="utf-8") as f:
                f.write("{}")

            with patch.object(sys, "argv", ["aider-factory", "--clear-side-sessions", "--forever"]):
                with self.assertRaises(SystemExit) as cm:
                    cli.main()
                self.assertEqual(cm.exception.code, 0)
            self.assertFalse(os.path.exists(oracle_file))
            self.assertFalse(os.path.exists(os.path.join(cache_dir, "aider_factory_cache")))

    def test_main_cli_clear_side_session_default_vs_forever(self):
        cache_dir = os.path.join(self.test_dir, "cache_cli_side_name")
        proj_name = os.path.basename(self.test_dir)
        oracle_file = os.path.join(self.af_dir, ".oracle_session.json")
        with open(oracle_file, "w", encoding="utf-8") as f:
            f.write("{}")

        with patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), \
             patch("os.getcwd", return_value=self.test_dir), \
             patch("sys.stdout", new=io.StringIO()):
            # 1. Clear single side session -> backup
            with patch.object(sys, "argv", ["aider-factory", "--clear-side-session", "oracle"]):
                with self.assertRaises(SystemExit) as cm:
                    cli.main()
                self.assertEqual(cm.exception.code, 0)
            self.assertFalse(os.path.exists(oracle_file))
            cached_oracle = os.path.join(cache_dir, "aider_factory_cache", proj_name, ".aider_factory", ".oracle_session.json")
            self.assertTrue(os.path.exists(cached_oracle))

            # 2. Clear single side session --forever -> no backup
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)
            helper_file = os.path.join(self.af_dir, ".helper_session.json")
            with open(helper_file, "w", encoding="utf-8") as f:
                f.write("[]")

            with patch.object(sys, "argv", ["aider-factory", "--clear-side-session", "helper", "--forever"]):
                with self.assertRaises(SystemExit) as cm:
                    cli.main()
                self.assertEqual(cm.exception.code, 0)
            self.assertFalse(os.path.exists(helper_file))
            self.assertFalse(os.path.exists(os.path.join(cache_dir, "aider_factory_cache")))

    def test_apply_paired_session_config_override(self):
        import yaml
        from aider_factory.python.apply_agent import resolve_editor_config

        sess_dir = os.path.join(self.af_dir, "sessions", "custom_sess")
        os.makedirs(sess_dir, exist_ok=True)
        sess_yaml = os.path.join(sess_dir, "session.yml")

        with open(sess_yaml, "w", encoding="utf-8") as f:
            yaml.dump({"models": {"editor_agent": "model_from_session_yml"}}, f)

        cfg = resolve_editor_config(self.test_dir, session_name="custom_sess")
        self.assertEqual(cfg["editor_model"], "model_from_session_yml")


if __name__ == "__main__":
    unittest.main()
