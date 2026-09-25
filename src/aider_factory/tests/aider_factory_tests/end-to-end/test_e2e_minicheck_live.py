#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.request


def _probe_local_minicheck_endpoint(url):
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/models")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return True, data
    except Exception:
        pass
    return False, None


class TestE2EMiniCheckLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidate_bases = [
            os.environ.get("GROUNDING_AGENT_API_BASE"),
            "http://192.168.100.1:8090/v1",
            "http://127.0.0.1:8090/v1",
            "http://localhost:8090/v1",
        ]
        cls.api_base = None
        for b in candidate_bases:
            if b:
                ok, _ = _probe_local_minicheck_endpoint(b)
                if ok:
                    cls.api_base = b
                    break

        if not cls.api_base:
            raise unittest.SkipTest("No local MiniCheck endpoint reachable at candidate addresses.")

        for cmd in ("aider-oracle", "aider-validate"):
            if not shutil.which(cmd):
                raise unittest.SkipTest(f"{cmd} CLI binary not found in PATH.")

    def _setup_env(self, workspace):
        env = os.environ.copy()
        env["PWD"] = workspace

        # Scrub ambient variables to guarantee state isolation
        for k in (
            "LITELLM_API_KEY",
            "LITELLM_BASE_URL",
            "ORACLE_EMBED_API_BASE",
            "ORACLE_RAG_DB_DIR",
            "ORACLE_SESSION_FILE",
            "ORACLE_DEBATE_SESSION_FILE",
            "ORACLE_CONTEXT_FILES",
            "ORACLE_JOB_READ_FILES",
            "ORACLE_NO_RAG_INGEST",
            "ORACLE_RETRIEVE_MODE",
            "GROUNDING_AGENT_API_KEY",
        ):
            env.pop(k, None)

        env["ORACLE_EMBED_MODEL"] = "BAAI/bge-m3"
        env["ORACLE_EMBED_BACKEND"] = "sentence-transformers"
        env["GROUNDING_AGENT_MODEL"] = "openai/minicheck-flan-t5-large"
        env["GROUNDING_AGENT_API_BASE"] = self.api_base
        env["GROUNDING_AGENT_API_KEY"] = "sk-dummy"
        env["OPENAI_API_BASE"] = self.api_base
        env["OPENAI_BASE_URL"] = self.api_base
        env["OPENAI_API_KEY"] = "sk-dummy"

        af_dir = os.path.join(workspace, ".aider_factory")
        os.makedirs(af_dir, exist_ok=True)
        config_path = os.path.join(af_dir, ".env.yml")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(
                f"working_directory: '{workspace}'\n"
                "rag:\n"
                "  embed_model: 'BAAI/bge-m3'\n"
                "  embed_backend: 'sentence-transformers'\n"
                "  batch: true\n"
            )
        env["ORACLE_CONFIG_FILE"] = config_path
        return env

    def test_e2e_live_grounded_claim_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = self._setup_env(tmpdir)
            source_file = os.path.join(tmpdir, "microstructure_paper.md")
            with open(source_file, "w", encoding="utf-8") as f:
                f.write(
                    "# High-Frequency Liquidity and Spread Dynamics\n\n"
                    "We examine the cross-section of liquid equity spreads during the opening auction "
                    "and first 15 minutes of continuous trading.\n"
                    "Empirical observations demonstrate that bid-ask spreads widen significantly in the "
                    "first 15 minutes of trading due to inventory risk and information asymmetry.\n"
                    "Market makers widen quoted spreads by an average of 2.4x the rolling baseline to "
                    "protect against informed adverse selection before price discovery stabilizes.\n"
                    "Consequently, liquidity-providing market makers earn a persistent premium when "
                    "placing post-only limit orders at the wide spread, yielding an average reversion "
                    "edge of 18 basis points over 5-minute intervals.\n"
                )

            res_ingest = subprocess.run(
                ["aider-oracle", "--collection", "kb_live_pass", "--add-file", source_file],
                cwd=tmpdir, env=env, capture_output=True, text=True
            )
            self.assertEqual(res_ingest.returncode, 0, f"Ingestion failed:\nSTDOUT: {res_ingest.stdout}\nSTDERR: {res_ingest.stderr}")
            kb_db = os.path.join(tmpdir, ".aider_factory", "markdown", "lanceDB", "kb_live_pass", "lancedb")
            self.assertTrue(os.path.exists(kb_db))

            grounded_file = os.path.join(tmpdir, "grounded.md")
            with open(grounded_file, "w", encoding="utf-8") as f:
                f.write(
                    "Market makers widen quoted spreads by an average of 2.4x the rolling baseline to protect against informed adverse selection before price discovery stabilizes.\n\n"
                    "Liquidity-providing market makers earn a persistent premium when placing post-only limit orders at the wide spread, yielding an average reversion edge of 18 basis points over 5-minute intervals.\n"
                )

            res_val = subprocess.run(
                [
                    "aider-validate", "--claims-only", "--file", grounded_file,
                    "--report", os.path.join(tmpdir, "rep.md"), "--collection", "*",
                    "--db", kb_db, "--region-threshold", "0.50",
                    "--grounding-model", "openai/minicheck-flan-t5-large",
                    "--grounding-api-base", self.api_base, "--grounding-api-key", "sk-dummy",
                    "--no-print",
                ],
                cwd=tmpdir, env=env, capture_output=True, text=True
            )
            self.assertEqual(res_val.returncode, 0, f"Validation failed:\nSTDOUT: {res_val.stdout}\nSTDERR: {res_val.stderr}")

    def test_e2e_live_hallucinated_claim_fails_and_generates_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = self._setup_env(tmpdir)
            source_file = os.path.join(tmpdir, "microstructure_paper.md")
            with open(source_file, "w", encoding="utf-8") as f:
                f.write(
                    "# High-Frequency Liquidity and Spread Dynamics\n\n"
                    "Empirical observations demonstrate that bid-ask spreads widen significantly in the "
                    "first 15 minutes of trading due to inventory risk and information asymmetry.\n"
                )

            res_ingest = subprocess.run(
                ["aider-oracle", "--collection", "kb_live_fail", "--add-file", source_file],
                cwd=tmpdir, env=env, capture_output=True, text=True
            )
            self.assertEqual(res_ingest.returncode, 0, f"Ingestion failed:\nSTDOUT: {res_ingest.stdout}\nSTDERR: {res_ingest.stderr}")
            kb_db = os.path.join(tmpdir, ".aider_factory", "markdown", "lanceDB", "kb_live_fail", "lancedb")

            hallucinated_file = os.path.join(tmpdir, "hallucinated.md")
            report_file = os.path.join(tmpdir, "rep_hallucinated.md")
            with open(hallucinated_file, "w", encoding="utf-8") as f:
                f.write(
                    "Market makers tighten quoted spreads to zero in the first 15 minutes of trading to maximize volume turnover.\n\n"
                    "Atmospheric spectroscopic observations of exoplanet HD 209458b confirm high concentrations of methane and water vapor.\n"
                )

            res_val = subprocess.run(
                [
                    "aider-validate", "--claims-only", "--file", hallucinated_file,
                    "--report", report_file, "--collection", "*",
                    "--db", kb_db, "--region-threshold", "0.50",
                    "--grounding-model", "openai/minicheck-flan-t5-large",
                    "--grounding-api-base", self.api_base, "--grounding-api-key", "sk-dummy",
                    "--no-print",
                ],
                cwd=tmpdir, env=env, capture_output=True, text=True
            )
            self.assertEqual(res_val.returncode, 1)
            self.assertTrue(os.path.exists(report_file))

    def test_e2e_live_mixed_document_trips_only_failing_paragraph(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = self._setup_env(tmpdir)
            source_file = os.path.join(tmpdir, "microstructure_paper.md")
            with open(source_file, "w", encoding="utf-8") as f:
                f.write(
                    "# High-Frequency Liquidity and Spread Dynamics\n\n"
                    "Market makers widen quoted spreads by an average of 2.4x the rolling baseline to protect against informed adverse selection before price discovery stabilizes.\n"
                )

            res_ingest = subprocess.run(
                ["aider-oracle", "--collection", "kb_mixed", "--add-file", source_file],
                cwd=tmpdir, env=env, capture_output=True, text=True
            )
            self.assertEqual(res_ingest.returncode, 0, f"Ingestion failed:\nSTDOUT: {res_ingest.stdout}\nSTDERR: {res_ingest.stderr}")
            kb_db = os.path.join(tmpdir, ".aider_factory", "markdown", "lanceDB", "kb_mixed", "lancedb")

            mixed_file = os.path.join(tmpdir, "mixed.md")
            report_file = os.path.join(tmpdir, "rep_mixed.md")
            with open(mixed_file, "w", encoding="utf-8") as f:
                f.write(
                    "Market makers widen quoted spreads by an average of 2.4x the rolling baseline to protect against informed adverse selection before price discovery stabilizes.\n\n"
                    "Market makers tighten quoted spreads to zero in the first 15 minutes of trading to maximize volume turnover.\n"
                )

            res_val = subprocess.run(
                [
                    "aider-validate", "--claims-only", "--file", mixed_file,
                    "--report", report_file, "--collection", "*",
                    "--db", kb_db, "--region-threshold", "0.50",
                    "--grounding-model", "openai/minicheck-flan-t5-large",
                    "--grounding-api-base", self.api_base, "--grounding-api-key", "sk-dummy",
                    "--no-print",
                ],
                cwd=tmpdir, env=env, capture_output=True, text=True
            )
            self.assertEqual(res_val.returncode, 1)
            with open(report_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("1 unsupported claims found", content)
            self.assertIn("Paragraph 2", content)
            self.assertNotIn("Paragraph 1", content)

    def test_e2e_live_hybrid_autofix_and_claims_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = self._setup_env(tmpdir)
            source_file = os.path.join(tmpdir, "execution_theory.md")
            with open(source_file, "w", encoding="utf-8") as f:
                f.write(
                    "# Market Microstructure and Order Execution\n\n"
                    "Empirical observations demonstrate that bid-ask spreads widen significantly in the "
                    "first 15 minutes of trading due to inventory risk and information asymmetry.\n\n"
                    "Consequently, liquidity-providing market makers earn a persistent premium when "
                    "placing post-only limit orders at the wide spread, yielding an average reversion "
                    "edge of 18 basis points over 5-minute intervals.\n"
                )

            res_ingest = subprocess.run(
                ["aider-oracle", "--collection", "kb_hybrid", "--add-file", source_file],
                cwd=tmpdir, env=env, capture_output=True, text=True
            )
            self.assertEqual(res_ingest.returncode, 0, f"Ingestion failed:\nSTDOUT: {res_ingest.stdout}\nSTDERR: {res_ingest.stderr}")
            kb_db = os.path.join(tmpdir, ".aider_factory", "markdown", "lanceDB", "kb_hybrid", "lancedb")

            hybrid_doc = os.path.join(tmpdir, "strategy_memo.md")
            with open(hybrid_doc, "w", encoding="utf-8") as f:
                f.write(
                    '[evidence] "bid-ask spreads widen significantly ... due to inventory risk"\n\n'
                    "Consequently, liquidity-providing market makers earn a persistent premium when "
                    "placing post-only limit orders at the wide spread, yielding an average reversion "
                    "edge of 18 basis points over 5-minute intervals.\n"
                )

            res_quote = subprocess.run(
                [
                    "aider-validate", "--file", hybrid_doc, "--source", source_file,
                    "--report", os.path.join(tmpdir, "quote_rep.md"), "--autofix",
                ],
                cwd=tmpdir, env=env, capture_output=True, text=True
            )
            self.assertEqual(res_quote.returncode, 0, f"Quote repair failed:\nSTDOUT: {res_quote.stdout}\nSTDERR: {res_quote.stderr}")
            with open(hybrid_doc, "r", encoding="utf-8") as f:
                doc_text = f.read()
            self.assertIn("[fixed]", doc_text)

            res_claims = subprocess.run(
                [
                    "aider-validate", "--claims-only", "--file", hybrid_doc,
                    "--report", os.path.join(tmpdir, "nli_rep.md"), "--collection", "*",
                    "--db", kb_db, "--region-threshold", "0.50",
                    "--grounding-model", "openai/minicheck-flan-t5-large",
                    "--grounding-api-base", self.api_base, "--grounding-api-key", "sk-dummy",
                    "--no-print",
                ],
                cwd=tmpdir, env=env, capture_output=True, text=True
            )
            self.assertEqual(res_claims.returncode, 0, f"Claims verification failed:\nSTDOUT: {res_claims.stdout}\nSTDERR: {res_claims.stderr}")


if __name__ == "__main__":
    unittest.main()
