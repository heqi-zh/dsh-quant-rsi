from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from test_runtime import ROOT, fixture
from dqr.service import Runtime, BASELINE
from dqr.data import save_snapshot
from dqr.storage import digest, read, write


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.runtime = Runtime(ROOT, self.directory)
        self.runtime.config["validation_end"] = "2023-01-10"
        self.snapshot = fixture()
        self.identity = save_snapshot(self.directory, self.snapshot["funds"], self.snapshot["rows"], "synthetic-loop-test")
        self.run_id = "a" * 32

    def fake_result(self, score=0.1, eligible=True):
        return {"status": "ok", "eligible": eligible,
                "decision": "retain_for_review" if eligible else "reject", "evaluation_id": digest(self.runtime.config),
                "candidate": {"metrics": {"total_return": score, "max_drawdown": 0.1}},
                "baseline": {"metrics": {"total_return": 0, "max_drawdown": 0.1}}}

    def trial(self, code, parent=None, feedback=""):
        return self.runtime.trial(self.identity, code, "test hypothesis", parent, self.run_id, feedback)

    def test_legacy_budget_migrates_without_reset_and_limit_changes_keep_usage(self):
        key = digest({"rows": self.runtime.snapshot(self.identity)["rows"], "evaluation": self.runtime.config})
        write(self.directory / "budgets" / (key + ".json"), {"trials": 2})
        budget = self.runtime.budget(self.identity)
        self.assertEqual(budget.status(), {"used": 2, "limit": 6, "remaining": 4})
        self.assertEqual(budget.reserve()["used"], 3)
        self.runtime.research_policy["total_trials_per_data_evaluator"] = 8
        self.assertEqual(self.runtime.budget(self.identity).status()["used"], 3)
        self.runtime.config["max_trials_per_snapshot"] = 9
        self.assertEqual(self.runtime.budget(self.identity).status()["used"], 3)

    def test_round_cap_lineage_feedback_and_no_promotion(self):
        before = (ROOT / "strategies/current.py").read_bytes()
        self.runtime.open_run(self.identity, self.run_id, 2, 60)
        with patch.object(self.runtime, "evaluate", side_effect=lambda *_: self.fake_result()):
            first = self.trial(BASELINE)
            with self.assertRaisesRegex(ValueError, "previous trial"):
                self.trial(BASELINE + "\n#changed")
            with self.assertRaisesRegex(ValueError, "previous_feedback"):
                self.trial(BASELINE + "\n#changed", first["trial_id"])
            self.assertEqual(self.runtime.budget(self.identity).status()["used"], 1)
            with patch.object(self.runtime, "evaluate", side_effect=lambda *_: self.fake_result(0.2)):
                second = self.trial(BASELINE + "\n#changed", first["trial_id"], "prior return was 0.1; test next change")
            self.assertEqual(second["research"]["stop_reason"], "round_limit")
            self.assertEqual(second["research"]["best_trial_id"], second["trial_id"])
            with self.assertRaisesRegex(ValueError, "run stopped"):
                self.trial(BASELINE + "\n#third", second["trial_id"], "more")
        self.assertEqual(before, (ROOT / "strategies/current.py").read_bytes())
        state = read(self.runtime.run_path(self.run_id))
        self.assertEqual(len(state["trials"]), 2)
        request = read(Path(second["artifact_dir"]) / "request.json")
        self.assertEqual(request["parent_trial_id"], first["trial_id"])
        self.assertEqual(request["round"], 2)

    def test_consecutive_failures_stop_and_archive_both_candidates(self):
        self.runtime.open_run(self.identity, self.run_id, 3, 60)
        # Real parser/worker failures, not fabricated evaluation feedback.
        first = self.trial("invalid python !")
        second = self.trial("another invalid python !", first["trial_id"], "previous candidate had syntax error; try repair")
        self.assertEqual(second["research"]["stop_reason"], "failure_limit")
        self.assertEqual(self.runtime.budget(self.identity).status()["used"], 2)
        self.assertTrue((Path(first["artifact_dir"]) / "result.json").exists())
        self.assertTrue((Path(second["artifact_dir"]) / "result.json").exists())

    def test_no_improvement_keeps_best_and_stops(self):
        self.runtime.open_run(self.identity, self.run_id, 3, 60)
        with patch.object(self.runtime, "evaluate", side_effect=lambda *_: self.fake_result(0.2)):
            first = self.trial(BASELINE)
        with patch.object(self.runtime, "evaluate", side_effect=lambda *_: self.fake_result(0.1)):
            second = self.trial(BASELINE + "\n#two", first["trial_id"], "prior return 0.2")
            third = self.trial(BASELINE + "\n#three", second["trial_id"], "second returned 0.1, worse; revise")
        self.assertEqual(third["research"]["stop_reason"], "round_limit")
        self.assertEqual(third["research"]["best_trial_id"], first["trial_id"])
        # With a threshold of one, the second non-improvement stops immediately.
        self.runtime.research_policy["no_improvement_patience"] = 1
        other = "b" * 32
        self.runtime.open_run(self.identity, other, 3, 60)
        with patch.object(self.runtime, "evaluate", side_effect=lambda *_: self.fake_result(eligible=False)):
            result = self.runtime.trial(self.identity, BASELINE, "reject", run_id=other)
        self.assertEqual(result["research"]["stop_reason"], "no_improvement")

    def test_time_and_pinned_evaluator_rejected_before_budget_spend(self):
        self.runtime.open_run(self.identity, self.run_id, 3, 60)
        state = read(self.runtime.run_path(self.run_id))
        state["deadline"] = 0
        write(self.runtime.run_path(self.run_id), state)
        with self.assertRaisesRegex(ValueError, "time_limit"):
            self.trial(BASELINE)
        self.assertEqual(self.runtime.budget(self.identity).status()["used"], 0)
        other = "c" * 32
        self.runtime.open_run(self.identity, other, 3, 60)
        self.runtime.config["max_drawdown"] = 0.2
        with self.assertRaisesRegex(ValueError, "another snapshot or evaluator"):
            self.runtime.trial(self.identity, BASELINE, "change eval", run_id=other)

    def test_global_limit_applies_across_runs_and_alias_snapshots(self):
        self.runtime.research_policy["total_trials_per_data_evaluator"] = 1
        state = self.runtime.open_run(self.identity, self.run_id, 3, 60)
        self.assertEqual(state["max_rounds"], 1)
        with patch.object(self.runtime, "evaluate", side_effect=lambda *_: self.fake_result()):
            self.trial(BASELINE)
        alias = save_snapshot(self.directory, self.snapshot["funds"], self.snapshot["rows"], "same-data-new-fetch")
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.runtime.open_run(alias, "d" * 32, 3, 60)

    def test_concurrent_reservations_cannot_overspend(self):
        self.runtime.research_policy["total_trials_per_data_evaluator"] = 2
        def reserve(_):
            try:
                return self.runtime.budget(self.identity).reserve()["used"]
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=8) as executor:
            used = list(executor.map(reserve, range(8)))
        self.assertEqual(sorted(value for value in used if value is not None), [1, 2])
        self.assertEqual(self.runtime.budget(self.identity).status()["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
