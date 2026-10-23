from datetime import date, datetime, timedelta, timezone
import fcntl
from pathlib import Path
import re
import uuid
import time

from .data import fetch_fund, save_snapshot
from .engine import panel, simulate, validate_config
from .storage import digest, read, write
from .research import Budget, check_run, complete_round, policy_for

# Buy once on first evaluation call, regardless of warmup length.
BASELINE = '''def strategy(history, portfolio):
    if sum(portfolio["units"][code] for code in portfolio["units"]) > 0:
        return None
    codes = sorted(portfolio["units"])
    return {code: 1.0 / len(codes) for code in codes}
'''


class Runtime:
    def __init__(self, root, directory=None):
        self.root = Path(root).resolve()
        self.directory = Path(directory).resolve() if directory else self.root / "data"
        self.config = read(self.root / "configs/evaluation.json")
        validate_config(self.config)
        self.research_policy = policy_for(self.root, self.config)

    def budget(self, identity):
        return Budget(self.directory, self.snapshot(identity)["rows"], self.config, self.research_policy)

    def run_path(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ValueError("invalid research run ID")
        return self.directory / "dsh-runs" / run_id / "research.json"

    def open_run(self, identity, run_id, rounds, seconds, parent_trial_id=None):
        for value, limit, name in [(rounds, self.research_policy["max_rounds_per_run"], "rounds"),
                                   (seconds, self.research_policy["max_seconds_per_run"], "seconds")]:
            if type(value) is not int or not 1 <= value <= limit:
                raise ValueError("requested " + name + " exceeds host research policy")
        path = self.run_path(run_id)
        if path.exists():
            raise ValueError("research run already exists; budget cannot be reset")
        available = self.budget(identity).status()
        if not available["remaining"]:
            raise ValueError("research budget exhausted for this data and evaluator")
        seed = None
        if parent_trial_id:
            folder = self.trial_path(identity, parent_trial_id)
            seed = read(folder / "result.json")
            if seed["evaluation_id"] != digest(self.config):
                raise ValueError("seed was evaluated under another fixed evaluator")
        state = {"schema": "dqr.research-run.v1", "run_id": run_id, "snapshot_id": identity,
                 "evaluation_id": digest(self.config), "evaluation": self.config,
                 "current_hash": digest((self.root / "strategies/current.py").read_text()),
                 "policy": self.research_policy, "max_rounds": min(rounds, available["remaining"]),
                 "requested_rounds": rounds, "rounds_used": 0, "deadline": time.time() + seconds,
                 "max_seconds": seconds, "budget_at_start": available,
                 "seed_trial_id": parent_trial_id, "last_trial_id": parent_trial_id,
                 "best_trial_id": parent_trial_id if seed and seed.get("eligible") else None,
                 "best_metrics": seed["candidate"]["metrics"] if seed and seed.get("eligible") else None,
                 "consecutive_failures": 0, "no_improvement_rounds": 0, "trials": [],
                 "status": "running", "stop_reason": None, "automatically_promoted": False}
        write(path, state)
        return state

    def finish_run(self, run_id, reason):
        path = self.run_path(run_id)
        state = read(path)
        if state["status"] == "running":
            state.update(status="stopped", stop_reason=reason)
        state["current_strategy_unchanged"] = state["current_hash"] == digest((self.root / "strategies/current.py").read_text())
        write(path, state)
        return state

    def trial_path(self, identity, trial_id):
        if not isinstance(trial_id, str) or not re.fullmatch(r"[0-9a-f]{32}", trial_id):
            raise ValueError("invalid parent trial ID")
        return self.directory / "experiments" / identity / trial_id

    def snapshot(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("invalid snapshot ID")
        snapshot = read(self.directory / "snapshots" / (identity + ".json"))
        if digest(snapshot) != identity:
            raise ValueError("snapshot hash mismatch")
        return snapshot

    def refresh(self):
        rows, raw = [], {}
        start = str(date.fromisoformat(self.config["validation_start"]) - timedelta(days=550))
        for fund in self.config["funds"]:
            items, pages = fetch_fund(fund, start)
            rows.extend(items)
            raw[fund] = pages
        identity = save_snapshot(self.directory, self.config["funds"], rows, "eastmoney-public-history", raw)
        return {"snapshot_id": identity, "source": "eastmoney-public-history", "rows": len(rows),
                "latest_nav_date": max(row["date"] for row in rows), "account_connected": False}

    def evaluate(self, identity, code):
        snapshot = self.snapshot(identity)
        reference = {"schema": "dqr.evaluation.v1", "snapshot_id": identity, "evaluation_id": digest(self.config),
                     "candidate_hash": digest(code), "baseline_hash": digest(BASELINE),
                     "source": snapshot["source"]}
        try:
            candidate = simulate(snapshot, self.config, code)
            baseline = simulate(snapshot, self.config, BASELINE)
        except Exception as exc:
            return dict(reference, status="failed", error=type(exc).__name__ + ": " + str(exc), eligible=False)
        delta = candidate["metrics"]["total_return"] - baseline["metrics"]["total_return"]
        eligible = delta > 0 and candidate["metrics"]["max_drawdown"] <= self.config["max_drawdown"]
        return dict(reference, status="ok", candidate=candidate, baseline=baseline,
                    return_delta=delta, eligible=eligible,
                    decision="retain_for_review" if eligible else "reject",
                    feedback="Passed fixed return/drawdown gates; manual review required." if eligible else "Did not improve baseline return within the configured drawdown limit.",
                    automatically_promoted=False)

    def trial(self, identity, code, hypothesis, parent_trial_id=None, run_id=None, previous_feedback=""):
        if not isinstance(hypothesis, str) or not hypothesis.strip() or len(hypothesis) > 4000:
            raise ValueError("a hypothesis of 1–4000 characters is required")
        if not isinstance(code, str) or len(code.encode()) > 32000:
            raise ValueError("candidate must be text of at most 32 KB")
        if not isinstance(previous_feedback, str) or len(previous_feedback) > 4000:
            raise ValueError("previous_feedback must be text of at most 4000 characters")
        self.snapshot(identity)
        area = self.directory / "experiments" / identity
        area.mkdir(parents=True, exist_ok=True)
        if parent_trial_id is not None:
            current = (self.trial_path(identity, parent_trial_id) / "candidate.py").read_text(encoding="utf-8")
        else:
            current = (self.root / "strategies/current.py").read_text(encoding="utf-8")
        # Serialize reservation and evaluation. Failed trials also consume budget.
        with (area / ".lock").open("w") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            state = read(self.run_path(run_id)) if run_id else None
            if state is not None:
                try:
                    check_run(state, identity, self.config,
                              digest((self.root / "strategies/current.py").read_text()),
                              parent_trial_id, previous_feedback)
                finally:
                    write(self.run_path(run_id), state)
                if code == current:
                    raise ValueError("candidate must change the parent strategy")
            try:
                budget = self.budget(identity).reserve()
            except ValueError:
                if state is not None:
                    state.update(status="stopped", stop_reason="global_budget_exhausted")
                    write(self.run_path(run_id), state)
                raise
            if state is not None:
                state["rounds_used"] += 1
                write(self.run_path(run_id), state)
            trial_id = uuid.uuid4().hex
            folder = area / trial_id
            folder.mkdir()
            (folder / "candidate.py").write_text(code, encoding="utf-8")
            (folder / "parent.py").write_text(current, encoding="utf-8")
            write(folder / "request.json", {"hypothesis": hypothesis, "snapshot_id": identity,
                                           "parent_hash": digest(current), "parent_trial_id": parent_trial_id,
                                           "created_at": datetime.now(timezone.utc).isoformat(),
                                           "evaluation": self.config, "trial_number": budget["used"],
                                           "research_run_id": run_id, "previous_feedback": previous_feedback,
                                           "round": state["rounds_used"] if state else None})
            try:
                result = self.evaluate(identity, code)
                # Parent comparison is informational. Baseline gates remain fixed.
                result["parent_evaluation"] = self.evaluate(identity, current)
            except KeyboardInterrupt:
                write(folder / "result.json", {"status": "cancelled", "trial_id": trial_id})
                if state is not None:
                    state.update(status="stopped", stop_reason="interrupted")
                    write(self.run_path(run_id), state)
                raise
            result["trial_id"] = trial_id
            result["artifact_dir"] = str(folder)
            result["trials_remaining"] = budget["remaining"]
            if state is not None:
                result["research"] = complete_round(state, result)
            write(folder / "result.json", result)
            if state is not None:
                write(self.run_path(run_id), state)
            return result

    def daily(self, identity):
        snapshot = self.snapshot(identity)
        bars = panel(snapshot)
        if len(bars) < 2:
            raise ValueError("at least two common NAV sessions required")
        config = dict(self.config, validation_end=bars[-1]["date"])
        code = (self.root / "strategies/current.py").read_text(encoding="utf-8")
        simulation = simulate(snapshot, config, code)
        result = {"schema": "dqr.daily.v1", "snapshot_id": identity, "strategy_hash": digest(code),
                  "analysis_id": digest(config), "analysis_config": config, "source": snapshot["source"],
                  "analysis_period": {"start": config["validation_start"], "end": config["validation_end"]},
                  "research_evaluation_id": digest(self.config),
                  "research_evaluation_period": {"start": self.config["validation_start"], "end": self.config["validation_end"]},
                  "latest_common_nav_date": bars[-1]["date"], "latest_decision_input_date": bars[-2]["date"],
                  "retrieved_at": snapshot["retrieved_at"], "account_connected": False,
                  "portfolio_kind": "model_portfolio", "simulation": simulation,
                  "research_question": "Can a different rebalancing rule improve fee-adjusted validation returns without exceeding the drawdown limit?"}
        path = self.directory / "reports" / (digest(result) + ".json")
        write(path, result)
        return dict(result, report_path=str(path))
