from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from io import StringIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from dqr.candidate import validate
from dqr.data import fetch_fund, save_snapshot, validate_rows
from dqr.engine import simulate
from dqr.service import BASELINE, Runtime
from dqr.storage import read, write


def fixture(days=12):
    rows = []
    for i in range(days):
        for code in ["000001", "110022"]:
            rows.append({"date": str(date(2022, 12, 31) + timedelta(days=i)), "code": code, "nav": 1.0, "dividend": 0})
    return {"funds": ["000001", "110022"], "rows": rows}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.config = read(ROOT / "configs/evaluation.json")
        self.config.update(purchase_fee=0, redemption_fees=[[1000000, 0]], min_trade=1)
        self.config["validation_end"] = "2023-01-10"

    def test_flat_nav_preserves_capital(self):
        result = simulate(fixture(), self.config, BASELINE)
        self.assertEqual(result["metrics"]["total_return"], 0)
        self.assertEqual(result["metrics"]["trade_count"], 2)
        self.assertEqual(result["metrics"]["max_drawdown"], 0)

    def test_fee_and_unit_math(self):
        self.config["purchase_fee"] = 0.01
        result = simulate(fixture(), self.config, BASELINE)
        self.assertAlmostEqual(result["metrics"]["fees"], 100000 - 100000 / 1.01)
        self.assertAlmostEqual(result["curve"][0]["equity"], 99009.90)

    def test_full_curve_drawdown(self):
        snapshot = fixture()
        for row in snapshot["rows"]:
            if row["date"] == "2023-01-05":
                row["nav"] = 0.5
        result = simulate(snapshot, self.config, BASELINE)
        self.assertAlmostEqual(result["metrics"]["max_drawdown"], 0.5)
        self.assertEqual(result["metrics"]["total_return"], 0)

    def test_current_nav_is_not_visible_at_decision(self):
        code = '''def strategy(history, portfolio):
    if history[-1]["nav"]["000001"] > 1.5:
        return {"000001": 1.0}
    return None
'''
        snapshot = fixture()
        for row in snapshot["rows"]:
            if row["date"] >= "2023-01-05" and row["code"] == "000001":
                row["nav"] = 2.0
        result = simulate(snapshot, self.config, code)
        self.assertEqual(result["fills"][0]["date"], "2023-01-06")

    def test_confirmation_and_settlement_lock_cash(self):
        code = '''def strategy(history, portfolio):
    if history[-1]["date"] == "2023-01-01":
        return {"000001": 1.0}
    if history[-1]["date"] == "2023-01-02":
        return {"110022": 1.0}
    return None
'''
        result = simulate(fixture(), self.config, code)
        self.assertEqual([fill["side"] for fill in result["fills"]], ["purchase", "redeem"])
        self.assertEqual(result["metrics"]["total_return"], 0)
        self.config["confirmation_sessions"] = 2
        result = simulate(fixture(), self.config, code)
        self.assertEqual([fill["side"] for fill in result["fills"]], ["purchase"])

    def test_short_holding_redemption_fee(self):
        self.config["redemption_fees"] = [[7, 0.015], [1000000, 0]]
        code = '''def strategy(history, portfolio):
    if history[-1]["date"] == "2023-01-01":
        return {"000001": 1.0}
    return {}
'''
        result = simulate(fixture(), self.config, code)
        self.assertAlmostEqual(result["metrics"]["fees"], 1500)
        self.assertAlmostEqual(result["metrics"]["total_return"], -0.015)

    def test_dividend_cash_and_nav_drop(self):
        snapshot = fixture()
        for row in snapshot["rows"]:
            if row["date"] >= "2023-01-05":
                row["nav"] = 0.9
            if row["date"] == "2023-01-05":
                row["dividend"] = 0.1
        result = simulate(snapshot, self.config, BASELINE)
        self.assertAlmostEqual(result["metrics"]["total_return"], 0)

    def test_reject_capabilities_and_invalid_weights(self):
        for code in ['import os\ndef strategy(history, portfolio): return None',
                     'def strategy(history, portfolio): return history.__class__',
                     'def strategy(history, portfolio): return open("secret")']:
            with self.assertRaises(ValueError):
                validate(code)
        with self.assertRaisesRegex(ValueError, "weights exceed"):
            simulate(fixture(), self.config, 'def strategy(history, portfolio): return {"000001": 2}')

    def test_timeout_kills_worker(self):
        self.config["candidate_timeout_seconds"] = 0.05
        with self.assertRaisesRegex(ValueError, "timeout"):
            simulate(fixture(), self.config, 'def strategy(history, portfolio):\n    return {"000001": sum(range(1000000000))}')

    def test_duplicate_nav_rejected(self):
        snapshot = fixture()
        snapshot["rows"].append(snapshot["rows"][0])
        with self.assertRaises(ValueError):
            validate_rows(snapshot["rows"], snapshot["funds"])


class ResearchTests(unittest.TestCase):
    def test_archive_budget_lineage_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runtime = Runtime(ROOT, directory)
            runtime.config["validation_end"] = "2023-01-10"
            runtime.research_policy["total_trials_per_data_evaluator"] = 3
            snapshot = fixture()
            identity = save_snapshot(directory, snapshot["funds"], snapshot["rows"], "synthetic-test-only")
            first = runtime.trial(identity, BASELINE, "Baseline control")
            self.assertEqual(first["status"], "ok")
            self.assertFalse(first["eligible"])
            self.assertTrue((Path(first["artifact_dir"]) / "candidate.py").exists())
            second = runtime.trial(identity, BASELINE, "Repeat control", first["trial_id"])
            self.assertEqual(read(Path(second["artifact_dir"]) / "request.json")["parent_trial_id"], first["trial_id"])
            failure = runtime.trial(identity, "invalid code !", "Failure must be archived")
            self.assertEqual(failure["status"], "failed")
            # Re-fetching identical rows must not reset the search budget.
            identity2 = save_snapshot(directory, snapshot["funds"], snapshot["rows"], "synthetic-test-only")
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                runtime.trial(identity2, BASELINE, "Over budget")
            path = directory / "snapshots" / (identity + ".json")
            changed = read(path)
            changed["rows"][0]["nav"] = 2
            write(path, changed)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                runtime.daily(identity)

    def test_daily_is_explicitly_model_portfolio(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            snapshot = fixture()
            identity = save_snapshot(directory, snapshot["funds"], snapshot["rows"], "synthetic-test-only")
            result = Runtime(ROOT, directory).daily(identity)
            self.assertEqual(result["portfolio_kind"], "model_portfolio")
            self.assertFalse(result["account_connected"])
            self.assertLess(result["latest_decision_input_date"], result["latest_common_nav_date"])
            self.assertEqual(result["analysis_period"]["end"], "2023-01-11")
            self.assertEqual(result["research_evaluation_period"]["end"], "2025-12-31")


class SourceTests(unittest.TestCase):
    def test_actual_page_lengths_and_per_ten_dividend(self):
        pages = []
        for page in range(1, 4):
            items = [{"FSRQ": str(date(2023, 1, 10) - timedelta(days=(page - 1) * 2 + j)),
                      "DWJZ": "1.0", "FHSP": "每10份派现金0.1000元" if page == 1 and j == 0 else ""}
                     for j in range(2)]
            pages.append(StringIO(json.dumps({"ErrCode": 0, "PageIndex": page, "PageSize": 2,
                                               "TotalCount": 6, "Data": {"LSJZList": items}})))
        with patch("dqr.data.urlopen", side_effect=pages) as fetch:
            rows, raw = fetch_fund("000001")
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(len(rows), 6)
        self.assertAlmostEqual(rows[0]["dividend"], 0.01)

    def test_unknown_corporate_action_fails(self):
        page = {"ErrCode": 0, "PageIndex": 1, "TotalCount": 1,
                "Data": {"LSJZList": [{"FSRQ": "2023-01-01", "DWJZ": "1", "FHSP": "份额折算"}]}}
        with patch("dqr.data.urlopen", return_value=StringIO(json.dumps(page))):
            with self.assertRaisesRegex(ValueError, "unsupported corporate action"):
                fetch_fund("000001")


if __name__ == "__main__":
    unittest.main()
