import os
import shutil
import subprocess
import sys
import tempfile
import unittest

# Ensure package root is on sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
pkg_python_dir = os.path.abspath(os.path.join(script_dir, "../../../python"))
if pkg_python_dir not in sys.path:
    sys.path.insert(0, pkg_python_dir)

import rag_manager


def _probe_all_reranker_endpoints(candidate_urls):
    """Probe all candidate endpoints and return list of (api_base, model) for all active servers."""
    import requests

    active_endpoints = []
    models_to_try = [
        "qwen3-reranker-4b-gpu:LATEST",
        "qwen3-reranker-4b:LATEST",
    ]

    seen = set()
    for base in candidate_urls:
        if not base or base in seen:
            continue
        seen.add(base)

        clean_base = base.rstrip("/")
        base_no_v1 = clean_base[:-3] if clean_base.endswith("/v1") else clean_base

        for model in models_to_try:
            matched = False
            for url in [f"{base_no_v1}/v1/rerank", f"{base_no_v1}/rerank"]:
                try:
                    resp = requests.post(
                        url,
                        json={
                            "model": model,
                            "query": "test probe",
                            "documents": ["alpha", "beta"],
                            "texts": ["alpha", "beta"],
                            "top_n": 1,
                        },
                        headers={"Authorization": "Bearer sk-dummy", "Content-Type": "application/json"},
                        timeout=3,
                    )
                    if resp.status_code == 200:
                        active_endpoints.append((base, model))
                        matched = True
                        break
                except Exception:
                    pass
            if matched:
                break

    return active_endpoints


class TestE2EOracleRerankerLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidate_bases = [
            os.environ.get("RANKING_API_BASE"),
            os.environ.get("ORACLE_RANKING_API_BASE"),
            os.environ.get("LITELLM_BASE_URL"),
            "http://192.168.100.1:8080/v1",
            "http://192.168.100.2:8081/v1",
            "http://localhost:8080/v1",
        ]
        cls.active_endpoints = _probe_all_reranker_endpoints(candidate_bases)
        if cls.active_endpoints:
            print(f"\n[E2E Reranker Test] Discovered {len(cls.active_endpoints)} active live endpoint(s):")
            for ep, mod in cls.active_endpoints:
                print(f"  • {ep} (model: {mod})")
        else:
            print("\n[E2E Reranker Test] No live cluster reranker endpoint discovered. Remote tests will be conditionally skipped.")

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.collection_name = "e2e_rerank_docs"
        self.context_root = os.path.join(self.test_dir, ".aider_factory", "markdown", "lanceDB")
        self.job_dir = os.path.join(self.context_root, self.collection_name)
        os.makedirs(self.job_dir, exist_ok=True)

        # 1. Create real physical source markdown documents
        self.doc1_path = os.path.join(self.job_dir, "fx_arbitrage_framework.md")
        with open(self.doc1_path, "w", encoding="utf-8") as f:
            f.write(
                "# FX Triangular Arbitrage Strategy Framework\n\n"
                "Triangular arbitrage opportunities occur when currency exchange rates are misaligned.\n\n"
                "## Execution Threshold Parameter\n\n"
                "The minimum profitability spread threshold for EUR/USD/GBP synthetic cross-arbitrage "
                "is strictly defined as theta_exec = 14.8 bps net of transaction fees.\n\n"
                "## Latency Constraints\n\n"
                "Order routing must execute in under 2.5 milliseconds to prevent adverse selection.\n"
            )

        self.doc2_path = os.path.join(self.job_dir, "credit_risk_parameters.md")
        with open(self.doc2_path, "w", encoding="utf-8") as f:
            f.write(
                "# Credit Risk Assessment Guide\n\n"
                "Tier 1 capital leverage ratios must maintain a 6.0% buffer against counterparty default.\n\n"
                "## Recovery Rates\n\n"
                "Senior secured debt instruments are modeled with a baseline 65% loss-given-default assumption.\n"
            )

        # 2. Ingest real documents into LanceDB on disk (Zero Mocks)
        ingest_ok = rag_manager.ingest(
            context_root=self.context_root,
            collection_name=self.collection_name,
            embed_model="BAAI/bge-m3",
            embed_backend="sentence-transformers",
            batch=True,
            overwrite=True,
        )
        self.assertTrue(ingest_ok, "Physical LanceDB ingestion failed.")

        self.db_dir = os.path.join(self.job_dir, "lancedb")
        self.assertTrue(os.path.isdir(self.db_dir), "LanceDB directory not created on disk.")

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _get_subprocess_env(self, extra_env=None):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([pkg_python_dir, env.get("PYTHONPATH", "")])
        env["ORACLE_RAG_DB_DIR"] = self.db_dir
        env["ORACLE_COLLECTION"] = self.collection_name
        env["ORACLE_EMBED_MODEL"] = "BAAI/bge-m3"
        env["ORACLE_EMBED_BACKEND"] = "sentence-transformers"
        env.pop("ORACLE_NO_RERANK", None)
        if hasattr(self, "active_endpoints") and self.active_endpoints:
            env["ORACLE_AGENT_API_BASE"] = self.active_endpoints[0][0]
            env["ORACLE_AGENT_MODEL"] = f"openai/{self.active_endpoints[0][1]}"
            env["OPENAI_API_KEY"] = "sk-dummy"
        if extra_env:
            env.update(extra_env)
        return env

    def test_live_remote_qwen_reranker_oracle_cli(self):
        """Execute physical oracle CLI subprocess querying LanceDB across ALL active remote rerankers."""
        if not self.active_endpoints:
            self.skipTest("No active cluster reranker endpoint available for live remote test.")

        oracle_script = os.path.join(pkg_python_dir, "oracle_agent.py")
        query = "What is the minimum profitability spread threshold for triangular arbitrage?"

        for api_base, model in self.active_endpoints:
            with self.subTest(api_base=api_base, model=model):
                env = self._get_subprocess_env({
                    "ORACLE_RANKING_MODEL": model,
                    "ORACLE_RANKING_API_BASE": api_base,
                    "ORACLE_RECALL_K": "15",
                    "ORACLE_TOP_K": "1",
                })

                proc = subprocess.run(
                    [sys.executable, oracle_script, query],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=30,
                )

                self.assertEqual(proc.returncode, 0, f"Oracle CLI exited with {proc.returncode} for {api_base}. Stderr: {proc.stderr}")
                self.assertNotIn("[rerank] warning:", proc.stderr)
                self.assertIn("fx_arbitrage_framework.md", proc.stderr + proc.stdout)

    def test_live_remote_qwen_reranker_validator_cli(self):
        """Execute physical validator CLI subprocess across ALL active remote rerankers."""
        if not self.active_endpoints:
            self.skipTest("No active cluster reranker endpoint available for live remote test.")

        validator_script = os.path.join(pkg_python_dir, "validator.py")

        for idx, (api_base, model) in enumerate(self.active_endpoints):
            with self.subTest(api_base=api_base, model=model):
                review_file = os.path.join(self.test_dir, f"report_{idx}.md")
                with open(review_file, "w", encoding="utf-8") as f:
                    f.write(
                        f"# Strategy Audit ({idx})\n\n"
                        "The arbitrage system enforces theta_exec = 14.8 bps net of transaction fees.\n"
                        '[evidence] "The minimum profitability spread threshold for EUR/USD/GBP synthetic cross-arbitrage is strictly defined as theta_exec = 14.8 bps net of transaction fees."\n'
                    )

                gate_report = os.path.join(self.test_dir, f"report_{idx}.gate.md")
                env = self._get_subprocess_env({
                    "ORACLE_RANKING_MODEL": model,
                    "ORACLE_RANKING_API_BASE": api_base,
                    "ORACLE_RECALL_K": "10",
                    "ORACLE_TOP_K": "2",
                })

                proc = subprocess.run(
                    [
                        sys.executable,
                        validator_script,
                        "--file",
                        review_file,
                        "--source",
                        self.doc1_path,
                        "--report",
                        gate_report,
                        "--db",
                        self.db_dir,
                        "--collection",
                        self.collection_name,
                    ],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=30,
                )

                self.assertEqual(proc.returncode, 0, f"Validator exited with {proc.returncode} for {api_base}. Stderr: {proc.stderr}")
                self.assertNotIn("[rerank] warning:", proc.stderr)
                with open(review_file, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("[validated]", content)

    def test_live_no_rerank_bypass_cli(self):
        """Execute physical oracle CLI with --no-rerank flag and verify clean fallback."""
        env = self._get_subprocess_env({
            "ORACLE_RANKING_MODEL": "qwen3-reranker-4b:LATEST",
            "ORACLE_RANKING_API_BASE": "http://127.0.0.1:9999/v1",  # Intentionally offline base
            "ORACLE_AGENT_MODEL": "openai/dummy",
            "OPENAI_API_KEY": "sk-dummy",
        })

        oracle_script = os.path.join(pkg_python_dir, "oracle_agent.py")
        query = "What are the latency constraints?"

        proc = subprocess.run(
            [sys.executable, oracle_script, "--no-rerank", query],
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )

        self.assertEqual(proc.returncode, 0, f"Bypass test failed with {proc.returncode}. Stderr: {proc.stderr}")
        self.assertIn("fx_arbitrage_framework.md", proc.stderr.lower() + proc.stdout.lower())

    def test_live_in_process_jina_reranker_cli(self):
        """Execute physical oracle CLI using in-process local CrossEncoder."""
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            self.skipTest("sentence-transformers not installed in environment.")

        env = self._get_subprocess_env({
            "ORACLE_RANKING_MODEL": "jinaai/jina-reranker-v3.5",
            "ORACLE_RANKING_API_BASE": "",  # Forces in-process path
            "ORACLE_RECALL_K": "10",
            "ORACLE_TOP_K": "1",
            "ORACLE_AGENT_MODEL": "openai/dummy",
            "OPENAI_API_KEY": "sk-dummy",
        })

        oracle_script = os.path.join(pkg_python_dir, "oracle_agent.py")
        query = "What is the baseline loss-given-default assumption for senior secured debt?"

        proc = subprocess.run(
            [sys.executable, oracle_script, query],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

        self.assertEqual(proc.returncode, 0, f"In-process reranker failed with {proc.returncode}. Stderr: {proc.stderr}")
        self.assertNotIn("[rerank] warning:", proc.stderr)
        self.assertIn("credit_risk_parameters.md", proc.stderr + proc.stdout)

    def test_live_batch_false_multi_table_e2e(self):
        """Zero-mock physical test of batch=False (per-document tables) with multi-table RRF and in-process CrossEncoder."""
        try:
            import sentence_transformers  # noqa: F401
            import lancedb
        except ImportError:
            self.skipTest("sentence-transformers or lancedb not installed.")

        coll_batch_false = "e2e_batch_false_coll"
        job_dir = os.path.join(self.context_root, coll_batch_false)
        os.makedirs(job_dir, exist_ok=True)

        f1 = os.path.join(job_dir, "macro_rates.md")
        with open(f1, "w", encoding="utf-8") as fh:
            fh.write(
                "# Central Bank Policy Rates Guide\n\n"
                "Central banks establish monetary policy targets to regulate overnight interbank lending rates.\n\n"
                "## Overnight Policy Target\n\n"
                "The Federal Reserve overnight benchmark interest rate target is strictly defined as 5.25% per annum.\n\n"
                "## Liquidity Facilities\n\n"
                "Primary credit facilities provide backup liquidity against eligible collateral.\n"
            )

        f2 = os.path.join(job_dir, "equity_derivatives.md")
        with open(f2, "w", encoding="utf-8") as fh:
            fh.write(
                "# Equity Derivatives Pricing Manual\n\n"
                "Options valuation models account for volatility surface dynamics across strike prices.\n\n"
                "## Volatility Skew\n\n"
                "Implied volatility skew reflects downside put option protection demand in equity markets.\n\n"
                "## Delta Hedging\n\n"
                "Dynamic portfolio rebalancing offsets underlying delta exposures.\n"
            )

        ok = rag_manager.ingest(
            context_root=self.context_root,
            collection_name=coll_batch_false,
            embed_model="BAAI/bge-m3",
            embed_backend="sentence-transformers",
            batch=False,
            overwrite=True,
        )
        self.assertTrue(ok)

        db_path = os.path.join(job_dir, "lancedb")
        db = lancedb.connect(db_path)
        tables = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        tbl_names = list(getattr(tables, "tables", tables))
        self.assertIn("macro_rates", tbl_names)
        self.assertIn("equity_derivatives", tbl_names)

        env = self._get_subprocess_env({
            "ORACLE_RAG_DB_DIR": db_path,
            "ORACLE_COLLECTION": "*",
            "ORACLE_EMBED_MODEL": "BAAI/bge-m3",
            "ORACLE_EMBED_BACKEND": "sentence-transformers",
            "ORACLE_EMBED_API_BASE": "",
            "ORACLE_RANKING_MODEL": "jinaai/jina-reranker-v3.5",
            "ORACLE_RANKING_API_BASE": "",
            "ORACLE_RECALL_K": "10",
            "ORACLE_TOP_K": "1",
            "ORACLE_AGENT_MODEL": "openai/dummy",
            "OPENAI_API_KEY": "sk-dummy",
        })

        oracle_script = os.path.join(pkg_python_dir, "oracle_agent.py")
        query = "What is the Federal Reserve overnight benchmark interest rate target?"

        proc = subprocess.run(
            [sys.executable, oracle_script, query],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

        self.assertEqual(proc.returncode, 0, f"batch=False query failed. Stderr: {proc.stderr}")
        self.assertNotIn("[rerank] warning:", proc.stderr)
        self.assertIn("macro_rates.md", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
