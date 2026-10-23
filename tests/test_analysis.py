from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from dqr.analysis import context, enforce_job, save_analysis
from dqr.storage import read
from dqr.programs import preview
from dqr.daily import daily
from dqr.vendor.openevolve.config import DatabaseConfig
from dqr.vendor.openevolve.database import ProgramDatabase
import test_monthly as fixtures


class AnalysisTests(unittest.TestCase):
    def test_daily_and_replay_execute_same_program(self):
        fixture = fixtures.MonthlyTests()
        with tempfile.TemporaryDirectory() as directory:
            runtime, manifest, folder = fixture.run_replay(Path(directory), fixture.rows())
            runtime.config["validation_start"] = "2026-09-01"
            result = daily(runtime, manifest["snapshot_id"], "2026-09-16")
            report = read(folder / "daily/2026-09-16.json")
            self.assertEqual(result["scores"], report["scores"])
            self.assertEqual(result["portfolio"], report["portfolio"])
            self.assertEqual(result["program_id"], report["program_id"])
            self.assertEqual(result["signal_target"], report["signal_target"])

    def test_report_job_cannot_read_future_or_run_candidates(self):
        job = {"replay_id": "a" * 64, "kind": "daily", "date": "2026-09-03"}
        with patch.dict(os.environ, {"DQR_REPORT_JOB": json.dumps(job)}):
            enforce_job("analysis-context", job)
            for op, request in [("month-evaluation", job), ("program-preview", job),
                                ("analysis-context", dict(job, date="2026-09-04"))]:
                with self.assertRaises(ValueError):
                    enforce_job(op, request)

    def test_evidence_verification_and_model_attribution(self):
        fixture = fixtures.MonthlyTests()
        with tempfile.TemporaryDirectory() as directory:
            runtime, manifest, folder = fixture.run_replay(Path(directory), fixture.rows())
            ctx = context(runtime, manifest["replay_id"], "daily", "2026-09-03")
            evidence = [{"path": "/report/report_date", "value": "2026-09-03"},
                        {"path": "/report/visible_nav_date", "value": ctx["report"]["visible_nav_date"]},
                        {"path": "/report/portfolio/equity", "value": ctx["report"]["portfolio"]["equity"]}]
            text = "测试模型分析：所列信息来自当时可见的模拟数据，不能据此推断未来行情。" * 5
            save_analysis(runtime, manifest["replay_id"], "daily", "2026-09-03", text, evidence, [])
            report = read(folder / "daily/2026-09-03.json")
            self.assertEqual(report["model_analysis"]["analysis"], text)
            self.assertNotIn("verified_session", report["model_analysis"])
            broken = deepcopy(evidence)
            broken[2]["value"] += 1
            with self.assertRaisesRegex(ValueError, "mismatch"):
                save_analysis(runtime, manifest["replay_id"], "daily", "2026-09-03", text, broken, [])
            self.assertEqual(ctx, context(runtime, manifest["replay_id"], "daily", "2026-09-03"))

    def test_custom_program_draft_and_real_openevolve_archive(self):
        fixture = fixtures.MonthlyTests()
        with tempfile.TemporaryDirectory() as directory:
            runtime, manifest, folder = fixture.run_replay(Path(directory), fixture.rows())
            program = read(ROOT / "strategies/operators-current.json")
            program["operators"]["extra_smoothing"] = {"parameters": ["x"], "expression": "ts_mean(x, 5)"}
            program["score"] = "extra_smoothing(momentum_contribution) + trend_contribution + risk_contribution + drawdown_contribution"
            result = preview(runtime, manifest["snapshot_id"], "2026-09-10", program, save=True)
            self.assertTrue(Path(result["saved_draft"]).exists())
            self.assertIn("extra_smoothing", result["operator_trace"]["score"])
            self.assertFalse(result["promoted"])
            database = ProgramDatabase(DatabaseConfig(db_path=str(folder / "openevolve"), num_islands=1, feature_dimensions=["complexity"]))
            self.assertIn(manifest["program_id"], database.programs)
            stored = database.programs[manifest["program_id"]]
            self.assertEqual(json.loads(stored.code), manifest["program"])
            self.assertEqual(stored.metrics["total_return"], manifest["metrics"]["total_return"])
            parent, _ = database.sample()
            self.assertEqual(parent.id, manifest["program_id"])


if __name__ == "__main__":
    unittest.main()
