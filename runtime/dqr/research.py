"""Host-owned research budgets and run state. This module never promotes code."""
from contextlib import contextmanager
import fcntl
import time

from .storage import digest, read, write


def policy_for(root, evaluation):
    path = root / "configs/research.json"
    policy = read(path) if path.exists() else {
        "total_trials_per_data_evaluator": evaluation["max_trials_per_snapshot"],
        "max_rounds_per_run": 3, "max_seconds_per_run": 300,
        "max_consecutive_failures": 2, "no_improvement_patience": 2,
    }
    for key in ("total_trials_per_data_evaluator", "max_rounds_per_run", "max_seconds_per_run",
                "max_consecutive_failures", "no_improvement_patience"):
        if type(policy.get(key)) is not int or policy[key] < 1:
            raise ValueError("research policy requires positive integer: " + key)
    return policy


def evaluator_identity(evaluation):
    # The old budget setting never affected numerical evaluation. Keep it out
    # of search identity so raising a host-owned limit cannot reset usage.
    return {key: value for key, value in evaluation.items() if key != "max_trials_per_snapshot"}


class Budget:
    def __init__(self, directory, rows, evaluation, policy):
        self.policy = policy
        area = directory / "budgets"
        area.mkdir(parents=True, exist_ok=True)
        self.path = area / (digest({"rows": rows, "evaluation": evaluator_identity(evaluation)}) + ".json")
        self.legacy = area / (digest({"rows": rows, "evaluation": evaluation}) + ".json")

    @contextmanager
    def locked(self):
        with self.path.with_suffix(".lock").open("w") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def used(self):
        # Old ledgers are retained. Their reservations include interrupted work,
        # so counting only archived experiments would undercount prior usage.
        return max(read(path)["trials"] if path.exists() else 0 for path in (self.path, self.legacy))

    def status(self):
        with self.locked():
            used = self.used()
        limit = self.policy["total_trials_per_data_evaluator"]
        return {"used": used, "limit": limit, "remaining": max(0, limit - used)}

    def reserve(self):
        with self.locked():
            used = self.used()
            limit = self.policy["total_trials_per_data_evaluator"]
            if used >= limit:
                raise ValueError("research budget exhausted for this data and evaluator")
            write(self.path, {"trials": used + 1, "legacy_ledger": self.legacy.name,
                              "limit_at_reservation": limit})
        return {"used": used + 1, "limit": limit, "remaining": limit - used - 1}


def check_run(state, identity, evaluation, current_hash, parent_id, previous_feedback):
    if state["snapshot_id"] != identity or state["evaluation_id"] != digest(evaluation):
        raise ValueError("research run is pinned to another snapshot or evaluator")
    if state["current_hash"] != current_hash:
        raise ValueError("current strategy changed during research")
    if state["status"] != "running":
        raise ValueError("research run stopped: " + str(state["stop_reason"]))
    if time.time() >= state["deadline"]:
        state.update(status="stopped", stop_reason="time_limit")
        raise ValueError("research run stopped: time_limit")
    if state["rounds_used"] >= state["max_rounds"]:
        state.update(status="stopped", stop_reason="round_limit")
        raise ValueError("research run stopped: round_limit")
    if parent_id != state["last_trial_id"]:
        raise ValueError("next round must name the previous trial as parent_trial_id")
    if parent_id and not previous_feedback.strip():
        raise ValueError("previous_feedback must explain the previous result and next change")


def complete_round(state, result):
    state["last_trial_id"] = result["trial_id"]
    state["consecutive_failures"] = state["consecutive_failures"] + 1 if result["status"] != "ok" else 0
    improved = (result.get("eligible", False) and
                (state["best_metrics"] is None or
                 result["candidate"]["metrics"]["total_return"] > state["best_metrics"]["total_return"] + 1e-12))
    if improved:
        state["best_trial_id"] = result["trial_id"]
        state["best_metrics"] = result["candidate"]["metrics"]
        state["no_improvement_rounds"] = 0
    else:
        state["no_improvement_rounds"] += 1
    state["trials"].append({"round": state["rounds_used"], "trial_id": result["trial_id"],
                            "status": result["status"], "decision": result.get("decision", "failed"),
                            "artifact_dir": result["artifact_dir"], "improved_best": improved})
    reason = None
    if time.time() >= state["deadline"]:
        reason = "time_limit"
    elif state["rounds_used"] >= state["max_rounds"]:
        reason = "round_limit"
    elif not result["trials_remaining"]:
        reason = "global_budget_exhausted"
    elif state["consecutive_failures"] >= state["policy"]["max_consecutive_failures"]:
        reason = "failure_limit"
    elif state["no_improvement_rounds"] >= state["policy"]["no_improvement_patience"]:
        reason = "no_improvement"
    if reason:
        state.update(status="stopped", stop_reason=reason)
    return {"run_id": state["run_id"], "round": state["rounds_used"],
            "max_rounds": state["max_rounds"], "rounds_remaining": max(0, state["max_rounds"] - state["rounds_used"]),
            "status": state["status"], "stop_reason": reason,
            "best_trial_id": state["best_trial_id"], "best_metrics": state["best_metrics"],
            "improved_best": improved, "automatically_promoted": False}
