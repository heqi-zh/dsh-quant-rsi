"""Run the shipped DSH headless profile using the existing local Codex login.

No token is written to configuration, command arguments or research artifacts.
The token is passed only to DSH's built-in openai-codex provider at launch.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from dqr.service import Runtime
from dqr.storage import read


def node_path(explicit=None):
    result = explicit or os.environ.get("DQR_NODE") or shutil.which("node")
    if not result:
        bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
        if bundled.is_file():
            result = str(bundled)
    if not result:
        raise ValueError("Node 22.19+ required; supply --node or DQR_NODE")
    return str(Path(result).resolve())


def codex_login():
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    auth = json.loads((codex_home / "auth.json").read_text())
    if auth.get("auth_mode") != "chatgpt":
        raise ValueError("This launcher expects an existing ChatGPT Codex login")
    token = auth.get("tokens", {}).get("access_token")
    if not token:
        raise ValueError("No cached Codex access token; sign in through Codex first")
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
    if claims.get("exp", 0) < time.time() + 120:
        raise ValueError("Codex access token expired; refresh through Codex before launching")
    text = (codex_home / "config.toml").read_text()
    match = re.search(r'^model\s*=\s*"([^"\n]+)"', text, re.M)
    if not match:
        raise ValueError("No explicit Codex model found; configure one in Codex first")
    return token, match.group(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--node")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--parent-trial", help="Continue from an archived candidate in the same snapshot")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.snapshot):
        raise ValueError("invalid snapshot ID")
    node = node_path(args.node)
    token, model = codex_login()
    profile = ROOT / ".dsh/profiles/dqr-research"
    if not (profile / "package.json").exists():
        raise ValueError("Initialize the DQR DSH profile first; see docs/dsh-run.md")
    run_id = uuid.uuid4().hex
    run = ROOT / "data/dsh-runs" / run_id
    run.mkdir(parents=True)
    current = (ROOT / "strategies/current.py").read_text()
    evaluation = json.loads((ROOT / "configs/evaluation.json").read_text())
    runtime = Runtime(ROOT)
    state = runtime.open_run(args.snapshot, run_id, args.rounds, args.timeout, args.parent_trial)
    parent = current
    seed_feedback = None
    if args.parent_trial:
        folder = runtime.trial_path(args.snapshot, args.parent_trial)
        parent = (folder / "candidate.py").read_text()
        previous = read(folder / "result.json")
        seed_feedback = {"trial_id": args.parent_trial, "status": previous["status"],
                         "decision": previous.get("decision"), "error": previous.get("error"),
                         "candidate_metrics": previous.get("candidate", {}).get("metrics"),
                         "baseline_metrics": previous.get("baseline", {}).get("metrics")}
    task = f'''Complete a bounded multi-round DQR research run using actual tools.
The existing public-data snapshot ID is {args.snapshot}. Do not fetch a replacement.
Host budget: at most {state['max_rounds']} NEW candidate rounds in this run,
within {args.timeout} seconds. Global usage before run: {json.dumps(state['budget_at_start'])}.
Budget policy: {json.dumps(state['policy'])}. The legacy max_trials_per_snapshot
field in the fixed evaluation config is retained for historical fingerprints;
the actual host budget is the policy and ledger above, not that legacy field.
The host enforces these limits, counts failures, and may stop early after
consecutive failures or no improvement. NEVER work around a stopped budget.
1. Call fund_daily on that snapshot, and read its returned metrics and assumptions.
   Daily analysis runs through the latest common NAV date; fixed research uses
   the host validation period below. These intentionally have different ends.
2. State a specific, testable hypothesis in Chinese. Generate a changed Python
   candidate based on your current parent and its actual feedback. Keep it simple.
3. Call research_trial with snapshot_id, hypothesis, code, parent_trial_id and
   previous_feedback (your specific analysis of the parent's metrics/error).
   This invokes the independent fixed evaluator and saves your candidate file.
   Do not call strategy_evaluate too: it uses the same limited trial budget.
4. Read the result before making another candidate. If research.status is running,
   explain the prior result, change that candidate again and repeat steps 2–3.
   Use the returned trial_id as parent_trial_id of the NEXT round, even if the
   candidate failed. previous_feedback must refer to that result. Do not submit
   parallel rounds or start a new root. If a candidate fails, use feedback to fix
   it on the next round unless the host has stopped. A rejected result is valid
   feedback, not an infrastructure error. Continue until the host stop reason.
5. Finish in Chinese with a table for EVERY round: trial ID, hypothesis, code
   change, candidate/baseline metrics, decision; explain the best candidate and
   the exact host stop reason. Cite every trial ID in your final answer.
   Never invent results. No candidate is automatically deployed.
Do not promote a strategy, change the evaluator, or perform trades.

Unchanged current/deployed strategy (not a research candidate):
{current}

Starting parent_trial_id: {json.dumps(args.parent_trial)}
Starting parent code (modify this for round one):
{parent}
Starting parent feedback: {json.dumps(seed_feedback, ensure_ascii=False)}

Fixed evaluation config (cannot be changed):
{json.dumps(evaluation, ensure_ascii=False)}

Candidate is ONE function def strategy(history, portfolio). Allowed pure calls:
abs, min, max, sum, len, range, sorted, float, int, round. No imports, attributes,
print, while, classes, helper functions or other calls. Ordinary loops and
comprehensions are allowed. history is a list of {{date, nav: {{code: unit_nav}}}},
up to 252 past sessions, never current fill NAV. portfolio contains cash, units,
prices and pending_cash. Return None for no action or a fund-weight dict with
nonnegative finite weights totaling <=1; omitted weight means zero.
The report is a MODEL PORTFOLIO, not personal holdings. Repeated search uses
the validation interval; there is no untouched final test or performance claim.
'''
    (run / "task.txt").write_text(task, encoding="utf-8")
    env = dict(os.environ)
    env.update(DSH_HOME=str(ROOT / ".dsh"), DSH_TELEMETRY_DISABLED="1",
               DQR_MODEL=model, DQR_CODEX_ACCESS_TOKEN=token, DQR_RESEARCH_RUN_ID=run_id)
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    dsh = ROOT / "node_modules/@deepseek-ai/dsh/lib/bin.js"
    command = [node, str(dsh), "--profile", "dqr-research", "--patch",
               str(ROOT / "configs/cordis.patch.yml"), "--patch",
               str(ROOT / "configs/dsh-research.patch.yml"), "--json", task]
    manifest = {"model": model, "snapshot_id": args.snapshot, "run_dir": str(run),
                "research_run_id": run_id, "max_rounds": state["max_rounds"],
                "seed_trial_id": args.parent_trial, "evaluation": evaluation,
                "parent_sha256": hashlib.sha256(current.encode()).hexdigest(),
                "auth": "existing-local-codex-access-token-in-memory", "status": "running"}
    (run / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({"run_dir": str(run), "model": model}), flush=True)
    try:
        with (run / "events.jsonl").open("w") as out, (run / "stderr.log").open("w") as err:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err, start_new_session=True)
            try:
                status = process.wait(timeout=args.timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                manifest["status"] = "timed_out" if isinstance(exc, subprocess.TimeoutExpired) else "interrupted"
                reason = "time_limit" if isinstance(exc, subprocess.TimeoutExpired) else "interrupted"
                runtime.finish_run(run_id, reason)
                raise
        manifest.update(status="completed" if status == 0 else "failed", exit_code=status)
        research = runtime.finish_run(run_id, "model_finished" if status == 0 else "model_error")
        manifest["stop_reason"] = research["stop_reason"]
        manifest["rounds_used"] = research["rounds_used"]
        manifest["best_trial_id"] = research["best_trial_id"]
        unchanged = hashlib.sha256((ROOT / "strategies/current.py").read_bytes()).hexdigest() == manifest["parent_sha256"]
        manifest["current_strategy_unchanged"] = unchanged
        if not unchanged:
            raise ValueError("Current strategy unexpectedly changed during the run")
        if status == 0:
            # Independent transcript/artifact checks; model prose is not the verifier.
            (run / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            subprocess.run([node, str(ROOT / "scripts/verify-research.mjs"), str(run)], cwd=ROOT, check=True)
        print(json.dumps(manifest, ensure_ascii=False), flush=True)
        return status
    finally:
        if manifest["status"] == "running":
            manifest["status"] = "interrupted"
            runtime.finish_run(run_id, "interrupted")
        (run / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
