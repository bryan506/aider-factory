#!/usr/bin/env python3
"""Tests for rsync-rag transport filtering, rag_manager walk guards, and oracle --add-table sync."""

import contextlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from unittest.mock import patch

script_dir = os.path.dirname(os.path.abspath(__file__))
pkg_root = os.path.abspath(os.path.join(script_dir, "../.."))
src_root = os.path.abspath(os.path.join(pkg_root, ".."))
python_dir = os.path.join(pkg_root, "python")
repo_root = os.path.abspath(os.path.join(src_root, ".."))
bash_script_path = os.path.join(repo_root, "bash", "rag_rsync.sh")

for p in (python_dir, src_root):
    if p not in sys.path:
        sys.path.insert(0, p)

from aider_factory import cli
import lancedb
import oracle_maintenance
import rag_manager


INCLUDED_REL_PATHS = {
    "R/lq_leverage.R",
    "src/main.py",
    "docs/adr/001.md",
    "vignettes/analysis.rmd",
    "helpers/setup.sh",
}

GITIGNORE_ONLY_EXCLUDED_REL_PATHS = {
    "BaseFeaturesNonGit/aac_copy.r",
    "sub/nested_ignored/secret.R",
    "custom_aider_ignored/foo.py",
}

EXCLUDED_REL_PATHS = GITIGNORE_ONLY_EXCLUDED_REL_PATHS | {
    ".git/config",
    ".aider_factory/.env.yml",
    ".aider.chat.history.md",
    ".env",
    ".Rprofile",
    "tempFiles/positions.rds",
    "node_modules/pkg/index.js",
    "ai-agent-config/cursor-skills/skill.md",
    "skeleton/AGENTS.md",
    "secrets/deltixhub_password",
    "AGENTS.md",
    "AGENTS.md.example",
    "CLAUDE.md",
    "GEMINI.md",
    "CONVENTIONS.md",
    "README.skeleton.md",
    "data.rds",
    "archive.zip",
    "trace.log",
}


def _write_file(base_dir: str, rel_path: str, content: str = "sample content\n") -> str:
    full_path = os.path.join(base_dir, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return full_path


def _populate_filter_matrix_repo(src_dir: str) -> None:
    _write_file(src_dir, ".gitignore", "BaseFeaturesNonGit/\n")
    _write_file(src_dir, "sub/.gitignore", "nested_ignored/\n")
    _write_file(src_dir, ".aiderignore", "custom_aider_ignored/\n")

    for rel in EXCLUDED_REL_PATHS:
        _write_file(src_dir, rel, f"excluded: {rel}\n")

    os.makedirs(os.path.join(src_dir, "empty_dir"), exist_ok=True)

    for rel in INCLUDED_REL_PATHS:
        _write_file(src_dir, rel, f"# valid: {rel}\nx <- 1\n")


def _collect_dest_files_and_dirs(dest_dir: str):
    files = set()
    dirs = set()
    for root, dirnames, filenames in os.walk(dest_dir):
        for d in dirnames:
            rel_d = os.path.relpath(os.path.join(root, d), dest_dir).replace("\\", "/")
            dirs.add(rel_d)
        for f in filenames:
            rel_f = os.path.relpath(os.path.join(root, f), dest_dir).replace("\\", "/")
            files.add(rel_f)
    return files, dirs


def _has_gnu_rsync() -> bool:
    if sys.platform == "win32":
        return False
    rsync_bin = shutil.which("rsync")
    if not rsync_bin:
        return False
    try:
        ver_res = subprocess.run(
            [rsync_bin, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        out = (ver_res.stdout + ver_res.stderr).lower()
        return ver_res.returncode == 0 and "openrsync" not in out
    except Exception:
        return False


def test_local_filter_matrix_python_and_bash():
    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = os.path.join(tmpdir, "src_repo")
        os.makedirs(src_dir, exist_ok=True)
        _populate_filter_matrix_repo(src_dir)

        has_rsync = _has_gnu_rsync()

        # 1. Verify cli.run_rsync_rag
        dest_py = os.path.join(tmpdir, "dest_py")
        rc_py = cli.run_rsync_rag([src_dir + "/", dest_py + "/"])
        assert rc_py == 0, f"Expected exit code 0, got {rc_py}"

        py_files, py_dirs = _collect_dest_files_and_dirs(dest_py)
        assert py_files == INCLUDED_REL_PATHS, f"Unexpected files in dest_py: {py_files}"
        assert py_files.isdisjoint(EXCLUDED_REL_PATHS)
        assert "empty_dir" not in py_dirs

        # 2. Verify bash/rag_rsync.sh when bash and rsync are available on POSIX
        if sys.platform != "win32" and shutil.which("bash") and has_rsync and os.path.isfile(bash_script_path):
            dest_sh = os.path.join(tmpdir, "dest_sh")
            res = subprocess.run(
                ["bash", bash_script_path, src_dir + "/", dest_sh + "/"],
                capture_output=True,
                text=True,
                check=False,
            )
            assert res.returncode == 0, f"bash/rag_rsync.sh failed: {res.stderr}"
            sh_files, sh_dirs = _collect_dest_files_and_dirs(dest_sh)
            assert sh_files == INCLUDED_REL_PATHS, f"Unexpected files in dest_sh: {sh_files}"
            assert sh_files.isdisjoint(EXCLUDED_REL_PATHS)
            assert "empty_dir" not in sh_dirs


def test_cli_help_and_missing_args():
    for help_args in ([], ["-h"], ["--help"]):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.run_rsync_rag(help_args)
        assert rc == 0
        assert "Usage:" in buf.getvalue()

    with contextlib.redirect_stdout(io.StringIO()):
        try:
            cli.rsync_rag_cli(["--help"])
            assert False, "Expected SystemExit"
        except SystemExit as exc:
            assert exc.code == 0

    for bad_args in (["only_one_arg"], ["-avn", "only_one_arg"], ["-e", "ssh -p 22", "only_one_arg"]):
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = cli.run_rsync_rag(bad_args)
        assert rc == 1
        assert "Requires at least a source and destination" in err_buf.getvalue()

    if sys.platform != "win32" and shutil.which("bash") and os.path.isfile(bash_script_path):
        for help_flag in ([], ["-h"], ["--help"]):
            res = subprocess.run(
                ["bash", bash_script_path, *help_flag],
                capture_output=True,
                text=True,
                check=False,
            )
            assert res.returncode == 0
            assert "Usage:" in res.stdout

        for bad_args in (["only_one_arg"], ["-avn", "only_one_arg"], ["-e", "ssh -p 22", "only_one_arg"]):
            res = subprocess.run(
                ["bash", bash_script_path, *bad_args],
                capture_output=True,
                text=True,
                check=False,
            )
            assert res.returncode == 1


def test_dry_run_and_ssh_safeguards():
    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = os.path.join(tmpdir, "src_repo")
        _write_file(src_dir, "src/main.py", "print(1)\n")

        # 1. Dry-run (-avn and --dry-run) must not create dest_dry
        dest_dry_1 = os.path.join(tmpdir, "dest_dry_1")
        assert cli.run_rsync_rag(["-avn", src_dir + "/", dest_dry_1]) == 0
        assert not os.path.exists(dest_dry_1)

        dest_dry_2 = os.path.join(tmpdir, "dest_dry_2")
        assert cli.run_rsync_rag(["--dry-run", src_dir + "/", dest_dry_2]) == 0
        assert not os.path.exists(dest_dry_2)

        # 2. Existing file destination with directory source returns 1
        existing_file = _write_file(tmpdir, "existing_file.txt", "hi\n")
        with contextlib.redirect_stderr(io.StringIO()):
            assert cli.run_rsync_rag([src_dir, existing_file]) == 1

        # 3. Double-dash (--) positional parsing
        dest_dd = os.path.join(tmpdir, "dest_dd")
        assert cli.run_rsync_rag(["--", src_dir + "/", dest_dd + "/"]) == 0
        assert os.path.isfile(os.path.join(dest_dd, "src", "main.py"))

        # 4. SSH option (-e) and remote destination safeguard via fake rsync on PATH (zero network calls)
        if sys.platform != "win32":
            fake_bin_dir = os.path.join(tmpdir, "fake_bin")
            os.makedirs(fake_bin_dir, exist_ok=True)
            captured_args_file = os.path.join(tmpdir, "captured_rsync_args.txt")
            fake_rsync = os.path.join(fake_bin_dir, "rsync")
            with open(fake_rsync, "w", encoding="utf-8") as fh:
                fh.write(
                    "#!/usr/bin/env bash\n"
                    f'printf "%s\\n" "$@" > "{captured_args_file}"\n'
                    "exit 0\n"
                )
            os.chmod(fake_rsync, stat.S_IRWXU)

            orig_cwd = os.getcwd()
            orig_path = os.environ.get("PATH", "")
            remote_target = "user@192.168.11.111:/remote/path/lanceDB/col/"
            try:
                os.chdir(tmpdir)
                with patch.dict("os.environ", {"PATH": f"{fake_bin_dir}{os.pathsep}{orig_path}"}):
                    rc = cli.run_rsync_rag(
                        [
                            "-rav",
                            "-e",
                            "ssh -p 22 -i ~/.ssh/id_key",
                            "--progress",
                            src_dir + "/",
                            remote_target,
                        ]
                    )
                    assert rc == 0
                    assert not os.path.exists(os.path.join(tmpdir, remote_target))
                    assert not os.path.exists(os.path.join(tmpdir, "user@192.168.11.111:"))
                    with open(captured_args_file, "r", encoding="utf-8") as fh:
                        recorded = fh.read().splitlines()
                    assert "-e" in recorded
                    assert "ssh -p 22 -i ~/.ssh/id_key" in recorded
                    assert "--progress" in recorded
                    assert remote_target in recorded

                    if shutil.which("bash") and os.path.isfile(bash_script_path):
                        dest_dry_sh = os.path.join(tmpdir, "dest_dry_sh")
                        res_dry = subprocess.run(
                            ["bash", bash_script_path, "-avn", src_dir + "/", dest_dry_sh],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        assert res_dry.returncode == 0
                        assert not os.path.exists(dest_dry_sh)

                        os.remove(captured_args_file)
                        res_ssh = subprocess.run(
                            [
                                "bash",
                                bash_script_path,
                                "-rav",
                                "-e",
                                "ssh -p 22 -i ~/.ssh/id_key",
                                "--progress",
                                src_dir + "/",
                                remote_target,
                            ],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        assert res_ssh.returncode == 0
                        assert not os.path.exists(os.path.join(tmpdir, remote_target))
                        with open(captured_args_file, "r", encoding="utf-8") as fh:
                            recorded_sh = fh.read().splitlines()
                        assert "ssh -p 22 -i ~/.ssh/id_key" in recorded_sh
                        assert remote_target in recorded_sh
            finally:
                os.chdir(orig_cwd)


def test_python_fallback_when_rsync_absent():
    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = os.path.join(tmpdir, "my_repo")
        _write_file(src_dir, "R/lq_leverage.R", "x <- 1\n")
        _write_file(src_dir, "src/main.py", "y = 2\n")
        _write_file(src_dir, ".env", "SECRET=1\n")
        _write_file(src_dir, "AGENTS.md", "harness\n")
        _write_file(src_dir, "node_modules/pkg/index.js", "ignored\n")

        with patch("shutil.which", return_value=None):
            # 1. Trailing slash: copies directly into dest_direct
            dest_direct = os.path.join(tmpdir, "dest_direct")
            assert cli.run_rsync_rag([src_dir + "/", dest_direct]) == 0
            assert os.path.isfile(os.path.join(dest_direct, "R", "lq_leverage.R"))
            assert os.path.isfile(os.path.join(dest_direct, "src", "main.py"))
            assert not os.path.exists(os.path.join(dest_direct, ".env"))
            assert not os.path.exists(os.path.join(dest_direct, "AGENTS.md"))
            assert not os.path.exists(os.path.join(dest_direct, "node_modules"))

            # 2. No trailing slash: copies into dest_nested/my_repo/
            dest_nested = os.path.join(tmpdir, "dest_nested")
            assert cli.run_rsync_rag([src_dir, dest_nested]) == 0
            assert os.path.isfile(os.path.join(dest_nested, "my_repo", "R", "lq_leverage.R"))

            # 3. Single file copy
            single_file = os.path.join(src_dir, "src", "main.py")
            dest_single = os.path.join(tmpdir, "dest_single")
            assert cli.run_rsync_rag([single_file, dest_single]) == 0
            assert os.path.isfile(os.path.join(dest_single, "main.py"))

            # 4. Dry-run in fallback mode does not create destination
            dest_fb_dry = os.path.join(tmpdir, "dest_fb_dry")
            assert cli.run_rsync_rag(["-n", src_dir + "/", dest_fb_dry]) == 0
            assert not os.path.exists(dest_fb_dry)

            # 5. Missing source returns 1
            assert cli.run_rsync_rag([os.path.join(tmpdir, "nonexistent"), dest_direct]) == 1

            # 6. Remote destination or remote source without rsync returns 1
            with contextlib.redirect_stderr(io.StringIO()):
                assert cli.run_rsync_rag([src_dir, "user@host:/remote/dest"]) == 1
                assert cli.run_rsync_rag(["user@host:/remote/src", dest_direct]) == 1


def test_walk_repo_defensive_guards_and_dedup():
    for expected_ign in (".aider_factory", "ai-agent-config", "skeleton", "tempfiles", "secrets"):
        assert expected_ign in rag_manager.IGNORE_DEFAULT, f"Missing {expected_ign} in IGNORE_DEFAULT"

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = os.path.join(tmpdir, "sample_repo")
        # Dotfiles and harness files
        for hidden_or_harness in (
            ".aider.chat.history.md",
            ".env",
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            "CONVENTIONS.md",
            "README.skeleton.md",
        ):
            _write_file(repo_dir, hidden_or_harness, "skip me\n")

        # Default ignored dirs + custom ignored dir (tested with uppercase CUSTOM_DIR)
        for ign_dir in (
            "node_modules",
            "__pycache__",
            "ai-agent-config",
            "skeleton",
            "tempfiles",
            "secrets",
            "vendor",
            ".aider_factory",
            "custom_dir",
        ):
            _write_file(repo_dir, f"{ign_dir}/inside.py", "x = 1\n")

        # Coexisting HTML vs Rmd and PDF vs MD vs Rmd
        _write_file(repo_dir, "vignettes/timebase_init_docs.rmd", "# Vignette\n")
        _write_file(repo_dir, "vignettes/timebase_init_docs.html", "<html></html>\n")
        _write_file(repo_dir, "vignettes/standalone.html", "<html>standalone</html>\n")
        _write_file(repo_dir, "papers/paper.pdf", "%PDF-1.4\n")
        _write_file(repo_dir, "papers/paper.md", "# OCR sidecar\n")
        _write_file(repo_dir, "papers/paper.rmd", "# Author Rmd\n")
        _write_file(repo_dir, "R/core.R", "core <- function() 1\n")

        results = list(
            rag_manager._walk_repo(
                repo_dir,
                ignore={"CUSTOM_DIR"},
                code_exts=rag_manager.CODE_EXTS_DEFAULT,
                text_doc_exts=rag_manager.TEXT_DOC_EXTS_DEFAULT,
            )
        )
        by_sf = {sf: kind for _, kind, sf in results}

        assert by_sf == {
            "sample_repo/R/core.R": "code",
            "sample_repo/papers/paper.pdf": "ocr_doc",
            "sample_repo/papers/paper.rmd": "text_doc",
            "sample_repo/vignettes/standalone.html": "ocr_doc",
            "sample_repo/vignettes/timebase_init_docs.rmd": "text_doc",
        }


def test_collection_sources_ingest_dedup_and_from_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        context_root = os.path.join(tmpdir, ".aider_factory", "markdown", "lanceDB")
        job_dir = os.path.join(context_root, "test_col")
        os.makedirs(job_dir, exist_ok=True)

        # Subdirectories: default-ignored vs custom-ignored
        os.makedirs(os.path.join(job_dir, "node_modules"), exist_ok=True)
        os.makedirs(os.path.join(job_dir, "custom_ignored"), exist_ok=True)
        os.makedirs(os.path.join(job_dir, "lancedb"), exist_ok=True)
        os.makedirs(os.path.join(job_dir, "images"), exist_ok=True)

        # Top-level files: harness, OCR + cached .md sidecar, text_doc + shadowed .html
        _write_file(job_dir, "AGENTS.md", "harness\n")
        _write_file(job_dir, "doc1.pdf", "%PDF-1.4\n")
        _write_file(job_dir, "doc1.md", "# Cached OCR markdown for doc1\n")
        _write_file(job_dir, "doc2.rmd", "# Rmd source for doc2\n")
        _write_file(job_dir, "doc2.html", "<html>shadowed html</html>\n")

        subdirs, top_files = rag_manager._collection_sources(
            job_dir,
            rag_manager.CODE_EXTS_DEFAULT,
            rag_manager.TEXT_DOC_EXTS_DEFAULT,
            ignore={"CUSTOM_IGNORED"},
        )
        assert subdirs == []
        top_names = {os.path.basename(f) for f in top_files}
        assert "AGENTS.md" not in top_names
        assert {"doc1.pdf", "doc1.md", "doc2.rmd", "doc2.html"} == top_names

        # Verify rag_manager.ingest() top_files deduplication in batch=True and batch=False modes
        def _stub_embed(texts, *args, **kwargs):
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

        with patch.object(rag_manager, "embed_texts", side_effect=_stub_embed):
            ok_batch = rag_manager.ingest(
                context_root=context_root,
                collection_name="test_col",
                embed_model="stub-model",
                overwrite=False,
                ignore=["CUSTOM_IGNORED"],
                batch=True,
                use_docling=False,
            )
            assert ok_batch is True

            db = lancedb.connect(os.path.join(job_dir, "lancedb"))
            tbl_batch = db.open_table("test_col_docs")
            batch_sources = {r["source_file"] for r in tbl_batch.to_arrow().to_pylist()}
            assert batch_sources == {"doc1.pdf", "doc2.rmd"}

            # Now test batch=False mode
            ok_nobatch = rag_manager.ingest(
                context_root=context_root,
                collection_name="test_col",
                embed_model="stub-model",
                overwrite=False,
                ignore=["CUSTOM_IGNORED"],
                batch=False,
                use_docling=False,
            )
            assert ok_nobatch is True
            _names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
            table_names = set(getattr(_names, "tables", _names))
            assert {"doc1", "doc2"}.issubset(table_names)
            tbl_doc1 = db.open_table("doc1")
            tbl_doc2 = db.open_table("doc2")
            doc1_sources = {r["source_file"] for r in tbl_doc1.to_arrow().to_pylist()}
            doc2_sources = {r["source_file"] for r in tbl_doc2.to_arrow().to_pylist()}
            assert doc1_sources == {"doc1.pdf"}
            assert doc2_sources == {"doc2.rmd"}
            del tbl_batch, tbl_doc1, tbl_doc2, db
            import gc
            gc.collect()

        # Verify _from_config forwards working_repo, code_exts, text_doc_exts, ignore
        norm_tmpdir = tmpdir.replace("\\", "/")
        yaml_path = _write_file(
            tmpdir,
            ".env.yml",
            f"working_directory: '{norm_tmpdir}'\n"
            "phases:\n"
            "  - enabled: true\n"
            "    rag:\n"
            "      collection_name: test_col\n"
            "      working_repo: custom_working_repo\n"
            "      code_exts: ['.py', '.r']\n"
            "      text_doc_exts: ['.md', '.rmd']\n"
            "      ignore: ['custom_ignored']\n",
        )
        captured_kwargs = {}

        def _fake_ingest(**kwargs):
            captured_kwargs.update(kwargs)
            return True

        with patch.object(rag_manager, "ingest", side_effect=_fake_ingest):
            assert rag_manager._from_config(yaml_path) is True

        assert captured_kwargs["working_repo"] == "custom_working_repo"
        assert captured_kwargs["code_exts"] == [".py", ".r"]
        assert captured_kwargs["text_doc_exts"] == [".md", ".rmd"]
        assert captured_kwargs["ignore"] == ["custom_ignored"]
        assert captured_kwargs["code_chunk_size"] == 6000

        # Verify explicit code_chunk_size override in _from_config
        yaml_override_path = _write_file(
            tmpdir,
            ".env_override.yml",
            f"working_directory: '{norm_tmpdir}'\n"
            "rag:\n"
            "  code_chunk_size: 4096\n",
        )
        captured_override = {}
        with patch.object(
            rag_manager,
            "ingest",
            side_effect=lambda **kw: captured_override.update(kw) or True,
        ):
            assert rag_manager._from_config(yaml_override_path) is True
        assert captured_override["code_chunk_size"] == 4096


def test_oracle_add_table_rsync_integration():
    # Unit-verify _get_active_phase and _resolve_active_collection branches
    multi_cfg = {
        "rag": {"collection_name": "global_col"},
        "phases": [
            {"enabled": False, "rag": {"collection_name": "phase0_col"}},
            {"enabled": True, "rag": {"collection_name": "phase1_col"}},
        ],
    }
    with patch.dict("os.environ", {}, clear=True):
        assert oracle_maintenance._resolve_active_collection(multi_cfg) == "phase1_col"
        assert oracle_maintenance._resolve_active_collection({"rag": {"collection_name": "global_only"}}) == "global_only"

    with patch.dict("os.environ", {"ORACLE_PHASE_INDEX": "0"}, clear=True):
        assert oracle_maintenance._resolve_active_collection(multi_cfg) == "phase0_col"

    with patch.dict("os.environ", {"ORACLE_PHASE_INDEX": "99"}, clear=True):
        assert oracle_maintenance._resolve_active_collection(multi_cfg) == "phase1_col"

    with patch.dict("os.environ", {"ORACLE_PHASE_INDEX": "invalid"}, clear=True):
        assert oracle_maintenance._resolve_active_collection(multi_cfg) == "phase1_col"

    # Verify cross-platform working_repo derivation (.rstrip("/\\"))
    win_cfg = {
        "working_directory": "C:\\path\\to\\working_repo\\",
        "phases": [
            {
                "enabled": True,
                "files": {"target_files": ["working_repo\\R\\foo.R"]},
            }
        ],
    }
    wr, ce, _, _, _ = oracle_maintenance._resolve_phase_repo_filters(win_cfg)
    assert wr == "working_repo"
    assert ce == {"R/foo.R"}

    with tempfile.TemporaryDirectory() as tmpdir:
        ext_repo = os.path.join(tmpdir, "ext_repo")
        _populate_filter_matrix_repo(ext_repo)

        context_root = os.path.join(tmpdir, "lanceDB")
        norm_tmpdir = tmpdir.replace("\\", "/")
        cfg_path = _write_file(
            tmpdir,
            ".env.yml",
            f"working_directory: '{norm_tmpdir}/ext_repo'\n"
            "phases:\n"
            "  - enabled: true\n"
            "    files:\n"
            "      target_files:\n"
            "        - R/lq_leverage.R\n"
            "      extra_editable_files:\n"
            "        - ext_repo/src/main.py\n"
            "    rag:\n"
            "      collection_name: maint_col\n"
            "      code_exts: ['.r', '.py', '.sh']\n"
            "      text_doc_exts: ['.md', '.rmd']\n"
            "      ignore: ['custom_ign']\n",
        )

        ingest_calls = []

        def _spy_ingest(**kwargs):
            ingest_calls.append(kwargs)
            return True

        oa_mod = sys.modules.get("oracle_agent") or sys.modules.get(
            "aider_factory.python.oracle_agent"
        )
        orig_om_root = oracle_maintenance.rag_context_root
        orig_oa_root = getattr(oa_mod, "rag_context_root", None) if oa_mod else None
        try:
            oracle_maintenance.rag_context_root = context_root
            if oa_mod is not None:
                oa_mod.rag_context_root = context_root
            with patch.dict(
                "os.environ",
                {"ORACLE_CONFIG_FILE": cfg_path, "ORACLE_COLLECTION": "maint_col"},
                clear=False,
            ), patch.object(rag_manager, "ingest", side_effect=_spy_ingest):
                rc = oracle_maintenance._add_maintenance("table", [ext_repo])

            assert rc == 0
            synced_repo = os.path.join(context_root, "maint_col", "ext_repo")
            synced_files, synced_dirs = _collect_dest_files_and_dirs(synced_repo)
            assert synced_files == INCLUDED_REL_PATHS
            assert synced_files.isdisjoint(EXCLUDED_REL_PATHS)
            assert "empty_dir" not in synced_dirs

            assert len(ingest_calls) == 1
            kw = ingest_calls[0]
            assert kw["working_repo"] == "ext_repo"
            assert kw["code_exclude"] == {"R/lq_leverage.R", "src/main.py"}
            assert kw["code_exts"] == [".r", ".py", ".sh"]
            assert kw["text_doc_exts"] == [".md", ".rmd"]
            assert kw["ignore"] == ["custom_ign"]
            assert kw["code_chunk_size"] == 6000
        finally:
            oracle_maintenance.rag_context_root = orig_om_root
            if oa_mod is not None:
                oa_mod.rag_context_root = orig_oa_root

        # Verify ensure_bash_wrappers provisions rsync-rag and rag_rsync.sh on POSIX
        if sys.platform != "win32":
            af_dir = os.path.join(tmpdir, ".aider_factory")
            cli.ensure_bash_wrappers(af_dir)
            for script_name in ("rsync-rag", "rag_rsync.sh"):
                script_p = os.path.join(af_dir, "bash", script_name)
                assert os.path.isfile(script_p)
                assert os.access(script_p, os.X_OK)


def test_dependency_floor_and_pyarrow_numpy_bridge():
    import importlib.metadata as _meta
    import tomllib

    # 1. Verify pyproject.toml split-specifier contract
    pyproject_path = os.path.join(repo_root, "pyproject.toml")
    with open(pyproject_path, "rb") as fh:
        pdata = tomllib.load(fh)
    overrides = pdata.get("tool", {}).get("uv", {}).get("override-dependencies", [])
    assert any(x.startswith("litellm>=1.106.2") for x in overrides)
    assert any(x.startswith("numpy>=2.0.0") for x in overrides)
    assert any(x.startswith("scipy>=1.14.1") for x in overrides)

    # 2. Verify ensure_aider_installed() auto-upgrades when numpy < 2.0.0
    recorded_cmds = []

    def _fake_run(cmd, *args, **kwargs):
        recorded_cmds.append(list(cmd))

        class _Res:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Res()

    def _fake_version(pkg):
        if pkg == "numpy":
            return "1.26.4"
        if pkg == "litellm":
            return "1.106.2"
        return _meta.version(pkg)

    with patch("shutil.which", side_effect=lambda b: f"/usr/bin/{b}"), patch.object(
        _meta, "version", side_effect=_fake_version
    ), patch("subprocess.run", side_effect=_fake_run):
        cli.ensure_aider_installed()

    pip_cmds = [c for c in recorded_cmds if len(c) >= 3 and c[:3] == ["uv", "pip", "install"]]
    assert any("numpy>=2.0.0" in c and "scipy>=1.14.1" in c for c in pip_cmds), (
        f"Expected numpy/scipy auto-upgrade command, got: {pip_cmds}"
    )


def test_ast_chunk_size_cap_and_nan_batch_recovery():
    import inspect
    import math
    import requests

    # 1. Verify _ast_chunk default max_chars=6000 and sibling flush before exceeding max_chars=2000
    sig = inspect.signature(rag_manager._ast_chunk)
    assert sig.parameters["max_chars"].default == 6000

    fn_a = "def alpha():\n" + ("    x = 1234567890\n" * 80)
    fn_b = "def beta():\n" + ("    y = 9876543210\n" * 80)
    src = f"{fn_a}\n{fn_b}\n"
    assert len(fn_a) < 2000 and len(fn_b) < 2000 and (len(fn_a) + len(fn_b)) > 2000

    chunks_default = rag_manager._ast_chunk(src, "python")
    assert len(chunks_default) == 1
    assert len(chunks_default[0][0]) <= 6000
    assert chunks_default[0][1] == 1 and chunks_default[0][2] > 160

    chunks = rag_manager._ast_chunk(src, "python", max_chars=2000)
    assert len(chunks) == 2
    assert [sym for _t, _ls, _le, sym in chunks] == ["alpha", "beta"]
    for text, ls, le, _sym in chunks:
        assert len(text) <= 2000, f"AST chunk exceeded max_chars=2000: len={len(text)}"
        assert ls < le

    # 2A. Verify Tier 1 recovery: slot-flush ([flush_pad, "ok"]) + 2-sequence halves L2 mean pool
    post_calls = []

    def _fake_post_tier1(url, json=None, headers=None, timeout=None):
        inputs = json["input"]
        post_calls.append(inputs)

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                if len(post_calls) == 1:
                    # Initial batch: first item valid, second item (len=800) returns NaN/None
                    return {
                        "data": [
                            {"embedding": [0.1, 0.2, 0.3]},
                            {"embedding": [None, float("nan"), 0.0]},
                        ]
                    }
                if len(inputs) == 2 and inputs[0].startswith("item_0 item_1") and inputs[1] == "ok":
                    # Slot-flush call
                    return {"data": [{"embedding": [1.0, 0.0, 0.0]}, {"embedding": [1.0, 0.0, 0.0]}]}
                if len(inputs) == 2 and len(inputs[0]) == 400 and len(inputs[1]) == 400:
                    # Tier 1 2-sequence halves call: [3, 0, 0] and [0, 4, 0] -> L2 mean pool = [0.6, 0.8, 0.0]
                    return {
                        "data": [
                            {"embedding": [3.0, 0.0, 0.0]},
                            {"embedding": [0.0, 4.0, 0.0]},
                        ]
                    }
                return {"data": [{"embedding": [None, None, None]} for _ in inputs]}

        return _FakeResp()

    with patch.object(requests, "post", side_effect=_fake_post_tier1):
        vecs = rag_manager.embed_texts(
            ["short valid chunk", "x" * 800],
            backend="openai",
            model="qwen3-embedding",
            api_base="http://127.0.0.1:8080/v1",
            batch_size=8,
        )

    assert len(post_calls) == 3  # 1 initial batch + 1 slot flush + 1 2-seq halves pool
    assert vecs[0] == [0.1, 0.2, 0.3]
    assert vecs[1] is not None and len(vecs[1]) == 3
    assert math.isclose(vecs[1][0], 0.6, rel_tol=1e-6)
    assert math.isclose(vecs[1][1], 0.8, rel_tol=1e-6)
    assert math.isclose(vecs[1][2], 0.0, abs_tol=1e-9)

    # 2B. Verify Tier 2 fallback: when Tier 1 halves still return NaN, distills deduplicated identifiers
    tier2_calls = []

    def _fake_post_tier2(url, json=None, headers=None, timeout=None):
        inputs = json["input"]
        tier2_calls.append(inputs)

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                if len(tier2_calls) == 1:
                    return {"data": [{"embedding": [float("nan"), 0.0, 0.0]}]}
                if len(inputs) == 2 and inputs[0].startswith("item_0 item_1") and inputs[1] == "ok":
                    return {"data": [{"embedding": [1.0, 0.0, 0.0]}, {"embedding": [1.0, 0.0, 0.0]}]}
                if len(inputs) == 2 and inputs[0].startswith("code symbols:") and inputs[1] == "ok":
                    return {"data": [{"embedding": [0.4, 0.5, 0.6]}, {"embedding": [1.0, 0.0, 0.0]}]}
                # Tier 1 halves fail with NaN to force Tier 2 fallback
                return {
                    "data": [
                        {"embedding": [float("nan"), 0.0, 0.0]},
                        {"embedding": [0.0, 1.0, 0.0]},
                    ]
                }

        return _FakeResp()

    noisy_code = ("alpha_sym = '!@#$%^&*()' + beta_sym\n" * 12)  # >= 256 chars with repeated identifiers
    with patch.object(requests, "post", side_effect=_fake_post_tier2):
        vecs_t2 = rag_manager.embed_texts(
            [noisy_code],
            backend="openai",
            model="qwen3-embedding",
            api_base="http://127.0.0.1:8080/v1",
            batch_size=8,
        )

    assert vecs_t2 == [[0.4, 0.5, 0.6]]
    assert len(tier2_calls) == 5  # 1 batch + (flush + halves) + (flush + distilled identifiers)
    assert tier2_calls[-1] == ["code symbols: alpha_sym beta_sym", "ok"]

    # 2C. Verify Tier 2 3-attempt exhaustion returns [None] cleanly when all attempts return NaN
    exhaust_calls = []

    def _fake_post_exhaust(url, json=None, headers=None, timeout=None):
        inputs = json["input"]
        exhaust_calls.append(inputs)

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": [{"embedding": [float("nan"), 0.0, 0.0]} for _ in inputs]}

        return _FakeResp()

    with patch.object(requests, "post", side_effect=_fake_post_exhaust):
        vecs_ex = rag_manager.embed_texts(
            [noisy_code],
            backend="openai",
            model="qwen3-embedding",
            api_base="http://127.0.0.1:8080/v1",
            batch_size=8,
        )

    assert vecs_ex == [None]
    assert len(exhaust_calls) == 9  # 1 batch + 2 Tier 1 (flush+halves) + 3*2 Tier 2 attempts


def test_ast_chunk_and_embed_edge_contracts():
    import gc
    import requests

    # 1. Decorated Python class + oversized decorated method + nested closure -> scoped symbols
    py_edge = (
        "@outer_dec\n"
        "class TradingEngine:\n"
        "    @inner_dec(mode='fast')\n"
        "    def execute_orders(self, orders: list) -> dict:\n"
        "        def _validate(o):\n"
        "            return o is not None\n"
        + "".join(
            f"        step_{i} = _validate(orders[{i} % len(orders)]) and ({i} * 3.14159)\n"
            for i in range(60)
        )
        + "        return {'ok': True}\n"
    )
    c_py = rag_manager._ast_chunk(py_edge, "python", max_chars=1500)
    assert len(c_py) >= 2
    assert "class TradingEngine:" in c_py[0][0] and "def execute_orders" in c_py[0][0]
    assert all(len(t) <= 1500 and ls < le and "TradingEngine" in sym for t, ls, le, sym in c_py)

    # 2. Header followed by near-max child + Stage 3 1-line orphan borrowing + _text_split_fallback buffer pop
    filler = "x" * 45
    near_max_child = (
        "def tricky_boundary(x: int) -> str:\n"
        "    big_doc = (\n"
        + "".join(f"        'line_{i:04d}_{filler}\\n'\n" for i in range(88))
        + "    )\n"
        "    return big_doc\n"
    )
    c_tricky = rag_manager._ast_chunk(near_max_child, "python", max_chars=6000)
    assert "def tricky_boundary" in c_tricky[0][0]
    assert all(len(t) <= 6000 and ls < le for t, ls, le, _ in c_tricky)

    orphan_tail_src = (
        "def main_work():\n"
        + "".join(f"    v_{i} = {i} + 1000000\n" for i in range(42))
        + "\nFINAL_FLAG = True\n"
    )
    c_orphan = rag_manager._ast_chunk(orphan_tail_src, "python", max_chars=900)
    assert len(c_orphan) >= 2
    assert all(len(t) <= 900 and ls < le and len(t.splitlines()) > 1 for t, ls, le, _ in c_orphan)

    # Verify _text_split_fallback pops retained overlap_lines when next line is near max_chars
    overlap_pop_src = ("a" * 30 + "\n") * 3 + ("b" * 92 + "\n")
    pop_chunks = rag_manager._text_split_fallback(overlap_pop_src, max_chars=100, overlap_lines=3)
    assert len(pop_chunks) == 2
    assert all(len(c) <= 100 for c in pop_chunks)

    # 3. Multi-language AST chunking: R (fut_aac.R + oversized R) and Bash (guarded for grammar availability)
    fut_aac_path = os.path.join(script_dir, "end-to-end", "fut_aac.R")
    if os.path.isfile(fut_aac_path):
        with open(fut_aac_path, "r", encoding="utf-8") as fh:
            r_real = fh.read()
        c_fut = rag_manager._ast_chunk(r_real, "r", max_chars=6000)
        if c_fut:
            assert len(c_fut) == 1
            assert len(c_fut[0][0]) <= 6000 and c_fut[0][1] < c_fut[0][2]
            assert c_fut[0][3] in ("period_subset", "locf_list", "aac_fut_b")
        else:
            assert c_fut == []

    r_oversized = (
        "calc_liquidity_leverage <- function(positions, depth, alpha = 0.05) {\n"
        + "".join(f"  val_{i} <- positions * depth / ({i} + alpha)\n" for i in range(40))
        + "  return(val_0)\n}\n"
    )
    c_r = rag_manager._ast_chunk(r_oversized, "r", max_chars=1000)
    if c_r:
        assert all(len(t) <= 1000 and ls < le and sym == "calc_liquidity_leverage" for t, ls, le, sym in c_r)
    else:
        assert c_r == []

    bash_src = (
        "run_pipeline_step() {\n"
        + "".join(f'    echo "Step {i}: processing item"\n' for i in range(40))
        + "    return 0\n}\n"
    )
    c_sh = rag_manager._ast_chunk(bash_src, "bash", max_chars=1000)
    if c_sh:
        assert all(len(t) <= 1000 and ls < le and sym == "run_pipeline_step" for t, ls, le, sym in c_sh)
    else:
        assert c_sh == []

    # 4. Sanitization, vector validity, and zero-norm mean-pool guards
    dirty = "def tok():\n    return '<|endoftext|>' + '<|im_start|>' + '\x00\x07\x1f' + '\ud800'"
    cleaned = rag_manager._sanitize_for_embed(dirty)
    assert "<|" not in cleaned and "|>" not in cleaned
    assert "\x00" not in cleaned and "\ud800" not in cleaned
    assert cleaned.encode("utf-8")
    assert rag_manager._sanitize_for_embed("") == "."
    assert rag_manager._sanitize_for_embed("   \n\t  ") == "."

    assert rag_manager._is_valid_vec([0.1, -0.2, 0.3]) is True
    assert rag_manager._is_valid_vec([]) is False
    assert rag_manager._is_valid_vec(None) is False
    assert rag_manager._is_valid_vec([True, 1.0]) is False
    assert rag_manager._is_valid_vec([0.1, float("nan")]) is False
    assert rag_manager._is_valid_vec([0.1, float("inf")]) is False
    assert rag_manager._mean_pool_vecs([[0.0, 0.0], [0.0, 0.0]]) == [0.0, 0.0]

    # 5. Dynamic max_batch_chars=7000 batching + oversized (>7000) single item
    batch_payloads = []

    def _fake_batch_post(url, json=None, headers=None, timeout=None):
        inputs = json["input"]
        batch_payloads.append(inputs)

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": [{"embedding": [0.5, 0.5]} for _ in inputs]}

        return _FakeResp()

    item_5100 = "a" * 5100
    item_1500 = "b" * 1500
    item_8500 = "c" * 8500
    with patch.object(requests, "post", side_effect=_fake_batch_post):
        b_vecs = rag_manager.embed_texts(
            [item_5100, item_1500, item_8500],
            backend="openai",
            model="qwen3-embedding",
            api_base="http://127.0.0.1:8080/v1",
            batch_size=8,
            max_batch_chars=7000,
        )
    assert len(b_vecs) == 3 and all(v == [0.5, 0.5] for v in b_vecs)
    assert len(batch_payloads) == 2
    assert [len(x) for x in batch_payloads[0]] == [5100, 1500]
    assert [len(x) for x in batch_payloads[1]] == [8500]

    # 6. Short chunk (<256 chars) skips Tier 1 -> Tier 2; HTTP 500 batch error cascades; ConnectionError aborts
    short_calls = []

    def _fake_short_nan(url, json=None, headers=None, timeout=None):
        inputs = json["input"]
        short_calls.append(inputs)

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                if len(short_calls) == 1:
                    return {"data": [{"embedding": [None, None]}]}
                return {"data": [{"embedding": [0.7, 0.3]} for _ in inputs]}

        return _FakeResp()

    with patch.object(requests, "post", side_effect=_fake_short_nan):
        s_vecs = rag_manager.embed_texts(
            ["short_ident = 42"],
            backend="openai",
            model="qwen3-embedding",
            api_base="http://127.0.0.1:8080/v1",
        )
    assert s_vecs == [[0.7, 0.3]]
    assert len(short_calls) == 3  # 1 batch + 1 flush + 1 Tier 2 distilled identifiers
    assert short_calls[2] == ["code symbols: short_ident", "ok"]

    http500_calls = []

    def _fake_batch_http500(url, json=None, headers=None, timeout=None):
        inputs = json["input"]
        http500_calls.append(inputs)

        class _FakeResp:
            def raise_for_status(self):
                if len(http500_calls) == 1:
                    raise requests.exceptions.HTTPError("500 Internal Server Error")

            def json(self):
                return {"data": [{"embedding": [0.8, 0.2]} for _ in inputs]}

        return _FakeResp()

    with patch.object(requests, "post", side_effect=_fake_batch_http500):
        h_vecs = rag_manager.embed_texts(
            ["first_item = 1", "second_item = 2"],
            backend="openai",
            model="qwen3-embedding",
            api_base="http://127.0.0.1:8080/v1",
        )
    assert h_vecs == [[0.8, 0.2], [0.8, 0.2]]
    assert len(http500_calls) == 5  # 1 failed batch + 2*(flush + Tier 2 distilled)

    with patch.object(requests, "post", side_effect=requests.exceptions.ConnectionError("offline")):
        conn_vecs = rag_manager.embed_texts(
            ["offline_chunk_1", "offline_chunk_2"],
            backend="openai",
            model="qwen3-embedding",
            api_base="http://127.0.0.1:8080/v1",
        )
    assert conn_vecs == [None, None]

    # 7. Tier 3 State Isolation: ingest() skips None vectors while persisting valid sibling chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        context_root = os.path.join(tmpdir, "lanceDB")
        job_dir = os.path.join(context_root, "partial_col")
        os.makedirs(job_dir, exist_ok=True)
        _write_file(job_dir, "good.md", "# Good Document\nValid content here.\n")
        _write_file(job_dir, "bad.md", "# Bad Document\nUn-embeddable content here.\n")

        def _partial_embed(texts, *args, **kwargs):
            if texts == ["dimension probe"]:
                return [[0.1, 0.2, 0.3, 0.4]]
            return [
                [0.1, 0.2, 0.3, 0.4] if "Good" in t else None
                for t in texts
            ]

        with patch.object(rag_manager, "embed_texts", side_effect=_partial_embed):
            ok_partial = rag_manager.ingest(
                context_root=context_root,
                collection_name="partial_col",
                embed_model="stub-model",
                overwrite=True,
                batch=True,
                use_docling=False,
            )
        assert ok_partial is True
        db = lancedb.connect(os.path.join(job_dir, "lancedb"))
        tbl = db.open_table("partial_col_docs")
        rows = tbl.to_arrow().to_pylist()
        assert len(rows) == 1
        assert rows[0]["source_file"] == "good.md"
        del tbl, db
        gc.collect()


if __name__ == "__main__":
    test_local_filter_matrix_python_and_bash()
    test_cli_help_and_missing_args()
    test_dry_run_and_ssh_safeguards()
    test_python_fallback_when_rsync_absent()
    test_walk_repo_defensive_guards_and_dedup()
    test_collection_sources_ingest_dedup_and_from_config()
    test_oracle_add_table_rsync_integration()
    test_dependency_floor_and_pyarrow_numpy_bridge()
    test_ast_chunk_size_cap_and_nan_batch_recovery()
    test_ast_chunk_and_embed_edge_contracts()
    print("\n🎉 All rsync-rag and RAG filter tests passed!")
