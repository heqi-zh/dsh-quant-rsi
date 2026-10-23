from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from dqr.data import save_snapshot
from dqr.monthly import monthly_replay, replay_artifact
from dqr.service import Runtime
from dqr.storage import read


class MonthlyTests(unittest.TestCase):
    def rows(self):
        rows = []
        for i in range(291):
            day = date(2026, 1, 1) + timedelta(days=i)
            if day.weekday() >= 5:
                continue
            for fund, growth in [("000001", 0.001), ("110022", 0.0002)]:
                rows.append({"date": day.isoformat(), "code": fund,
                             "nav": 1 + i * growth, "dividend": 0})
        return rows

    def run_replay(self, directory, rows):
        runtime = Runtime(ROOT, directory)
        identity = save_snapshot(directory, runtime.config["funds"], rows, "synthetic-test")
        result = monthly_replay(runtime, identity, "2026-09")
        return runtime, result, Path(result["artifact_dir"])

    def test_calendar_and_evaluation_and_no_mutation(self):
        current = (ROOT / "strategies/current.py").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            runtime, result, folder = self.run_replay(Path(directory), self.rows())
            self.assertEqual(result["daily_reports"], 30)
            self.assertEqual(result["weekly_dates"], ["2026-09-06", "2026-09-13", "2026-09-20", "2026-09-27", "2026-09-30"])
            for day in result["report_days"]:
                r = read(folder / "daily" / (day + ".json"))
                self.assertLess(r["visible_nav_date"], day)
                self.assertTrue(all(f["date"] < day for f in r["fills_to_date"]))
                self.assertEqual(r["program_id"], result["program_id"])
                self.assertTrue((folder / "daily" / (day + ".md")).is_file())
            first = read(folder / "daily/2026-09-01.json")
            self.assertEqual(first["portfolio"]["equity"], 100000)
            self.assertEqual(first["fills_to_date"], [])
            sun = read(folder / "daily/2026-09-06.json")
            self.assertFalse(sun["new_nav_since_previous_report"])
            self.assertEqual(sun["visible_nav_date"], "2026-09-04")
            evaluation = replay_artifact(runtime, result["replay_id"], "evaluation")
            self.assertEqual(evaluation["candidate"]["metrics"], result["metrics"])
            self.assertEqual(len(evaluation["candidate"]["curve"]), 22)
            self.assertFalse((Path(directory) / "experiments").exists())
            for day in result["weekly_dates"]:
                review = replay_artifact(runtime, result["replay_id"], "weekly", day)
                self.assertFalse(review["optimized"])
                self.assertFalse(review["candidate_created"])
                self.assertLess(review["evidence"]["visible_through"], day)
        self.assertEqual((ROOT / "strategies/current.py").read_bytes(), current)

    def test_future_nav_does_not_change_earlier_report_evidence(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            rows = self.rows()
            changed = deepcopy(rows)
            for row in changed:
                if row["date"] >= "2026-09-15":
                    row["nav"] *= 2
            _, _, left = self.run_replay(Path(a), rows)
            _, _, right = self.run_replay(Path(b), changed)
            for day in ["2026-09-01", "2026-09-14", "2026-09-15"]:
                x, y = [read(p / "daily" / (day + ".json")) for p in (left, right)]
                for key in ("scores", "portfolio", "fills_to_date", "signal_target", "return_to_date"):
                    self.assertEqual(x[key], y[key], key)
            x, y = [read(p / "weekly/2026-09-13.json") for p in (left, right)]
            for review in (x, y):
                for daily in review["daily_evidence"]:
                    daily.pop("snapshot_id")  # The full source snapshots intentionally differ.
            self.assertEqual(x, y)

    def test_insufficient_history(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "warmup"):
                self.run_replay(Path(directory), [r for r in self.rows() if r["date"] >= "2026-08-20"])

    def test_incomplete_month_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(ROOT, directory)
            identity = save_snapshot(Path(directory), runtime.config["funds"], self.rows(), "synthetic-test")
            with self.assertRaisesRegex(ValueError, "complete calendar month"):
                monthly_replay(runtime, identity, "2026-10")


if __name__ == "__main__":
    unittest.main()
