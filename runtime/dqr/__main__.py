import argparse
import json
from pathlib import Path
import sys
import signal

from .service import Runtime
from .data import save_snapshot
from .monthly import monthly_replay, replay_artifact


def main():
    def cancelled(_signum, _frame):
        raise KeyboardInterrupt("DQR cancelled")
    signal.signal(signal.SIGTERM, cancelled)
    parser = argparse.ArgumentParser(description="DQR research runtime; no live orders")
    parser.add_argument("operation", choices=["screening-build", "screening-report", "screening-evaluation", "snapshot", "import", "daily", "evaluate", "trial", "month", "weekly-report", "month-evaluation", "operators", "program-preview", "program-evaluate", "analysis-context", "analysis-save"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--request", type=Path, help="JSON request file; default reads JSON from stdin")
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8")) if args.request else json.load(sys.stdin)
        runtime = Runtime(args.root, args.data_dir)
        from .analysis import enforce_job
        enforce_job(args.operation, request)
        if args.operation == "screening-build":
            from .screening import build
            result = build(runtime, request.get("dataset_id"))
        elif args.operation == "screening-report":
            from .analysis import context
            result = context(runtime, request["replay_id"], request.get("kind", "daily"), request["date"])
        elif args.operation == "screening-evaluation":
            from .storage import read
            import re
            if not re.fullmatch(r"[a-f0-9]{64}", request["replay_id"]):
                raise ValueError("invalid replay ID")
            folder = runtime.directory / "product/runs" / request["replay_id"]
            if not folder.exists():
                folder = runtime.directory / "screening/runs" / request["replay_id"]
            result = read(folder / "evaluation.json")
        elif args.operation == "operators":
            from .operators import catalogue
            result = catalogue()
        elif args.operation == "program-preview":
            from .programs import preview
            result = preview(runtime, request["snapshot_id"], request["as_of"], json.loads(request["program_json"]), request.get("save", False))
        elif args.operation == "program-evaluate":
            result = monthly_replay(runtime, request["snapshot_id"], request["month"], json.loads(request["program_json"]))
        elif args.operation == "analysis-context":
            from .analysis import context
            result = context(runtime, request["replay_id"], request["kind"], request["date"])
        elif args.operation == "analysis-save":
            from .analysis import save_analysis
            result = save_analysis(runtime, request["replay_id"], request["kind"], request["date"], request["analysis"],
                                   json.loads(request["evidence_json"]), json.loads(request.get("proposals_json", "[]")))
        elif args.operation == "month":
            result = monthly_replay(runtime, request["snapshot_id"], request.get("month"))
        elif args.operation == "weekly-report":
            from .analysis import location
            from .storage import read
            result = read(location(runtime, request["replay_id"], "weekly", request["date"]))
        elif args.operation == "month-evaluation":
            result = replay_artifact(runtime, request["replay_id"], "evaluation")
        elif args.operation == "snapshot":
            result = runtime.refresh()
        elif args.operation == "import":
            # Imports always identify their source; fixtures must never claim real data.
            if not request.get("source"):
                raise ValueError("import source label required")
            identity = save_snapshot(runtime.directory, runtime.config["funds"], request["rows"], request["source"])
            result = {"snapshot_id": identity, "source": request["source"]}
        elif args.operation == "daily":
            if request.get("snapshot_id"):
                from .daily import daily
                result = daily(runtime, request["snapshot_id"], request.get("as_of"))
            else:
                from .storage import read
                from .analysis import location
                latest = runtime.directory / "product/published.json"
                if not latest.exists():
                    latest = runtime.directory / "product/latest.json"
                manifest = read(latest if latest.exists() else runtime.directory / "screening/latest.json")
                day = manifest.get("latest_date") or manifest["report_days"][-1]
                day=request.get("as_of",day)
                from .publication import report_routes
                identity=request.get("replay_id") or report_routes(runtime.directory/"product")["daily"].get(day) or manifest["replay_id"]
                result = read(location(runtime,identity,"daily",day))
        elif args.operation == "evaluate":
            # Evaluation uses a recorded trial, so the same search budget applies.
            result = runtime.trial(request["snapshot_id"], request["code"], request.get("hypothesis", "Independent candidate evaluation"),
                                   request.get("parent_trial_id"), request.get("research_run_id"), request.get("previous_feedback", ""))
        else:
            result = runtime.trial(request["snapshot_id"], request["code"], request["hypothesis"], request.get("parent_trial_id"),
                                   request.get("research_run_id"), request.get("previous_feedback", ""))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled"}))
        sys.exit(130)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": type(exc).__name__ + ": " + str(exc)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
