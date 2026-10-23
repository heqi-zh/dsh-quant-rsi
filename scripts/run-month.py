"""Offline monthly replay; optional --dsh exercises all three plugins with a model."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from dqr.monthly import monthly_replay
from dqr.service import Runtime
from dqr.storage import digest, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--month", help="YYYY-MM; default latest prior complete month")
    parser.add_argument("--dsh", action="store_true", help="Use existing Codex login for actual DSH plugin calls")
    args = parser.parse_args()
    runtime = Runtime(ROOT)
    before = (ROOT / "strategies/current.py").read_bytes()
    result = monthly_replay(runtime, args.snapshot, args.month)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not args.dsh:
        return
    spec = importlib.util.spec_from_file_location("dqr_launcher", ROOT / "scripts/run-research.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    node = launcher.node_path()
    token, model = launcher.codex_login()
    run = ROOT / "data/dsh-month-runs" / uuid.uuid4().hex
    run.mkdir(parents=True)
    task = f'''请验证 DQR 月度报告功能，使用真实工具。只允许以下三种工具：
1. 调用 fund_month_replay，snapshot_id={args.snapshot}，month={result['month']}。
2. 用返回的 replay_id 调用 operator_weekly_report，逐份读取 weekly_dates 中全部周报。
3. 调用 month_evaluation，读取完整月份的评测。
最后用中文简短汇总日报/周报数量、实际模拟指标、主要算子建议和产物目录。
这是历史回放；日报和周报由确定性规则生成，周报没有真实优化或候选评测。
不得调用旧研究工具，不得生成候选或切换当前策略，不得访问账户或交易。
你只解释工具证据，不能把周报中的建议说成已经验证的改进。'''
    (run / "task.txt").write_text(task, encoding="utf-8")
    env = dict(os.environ, DSH_HOME=str(ROOT / ".dsh"), DSH_TELEMETRY_DISABLED="1",
               DQR_MODEL=model, DQR_CODEX_ACCESS_TOKEN=token, DQR_REPORT_ONLY="1")
    env.pop("DQR_RESEARCH_RUN_ID", None)
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    command = [node, str(ROOT / "node_modules/@deepseek-ai/dsh/lib/bin.js"), "--profile", "dqr-research",
               "--patch", str(ROOT / "configs/cordis.patch.yml"), "--patch", str(ROOT / "configs/dsh-research.patch.yml"), "--json", task]
    manifest = {"status": "running", "model": model, "replay_id": result["replay_id"], "current_hash": digest(before.hex())}
    write(run / "manifest.json", manifest)
    print(json.dumps({"dsh_run": str(run)}), flush=True)
    try:
        with (run / "events.jsonl").open("w") as out, (run / "stderr.log").open("w") as err:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err, start_new_session=True)
            try:
                status = process.wait(timeout=180)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
        if status:
            raise RuntimeError("DSH failed; inspect " + str(run / "stderr.log"))
        events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
        calls = [e for e in events if e["type"] == "tool_call"]
        names = {c["tool"] for c in calls}
        expected = {"fund_month_replay", "operator_weekly_report", "month_evaluation"}
        if names != expected:
            raise ValueError("DSH did not use exactly the permitted plugin tools")
        reviews = set()
        for call in calls:
            event = next(e for e in events if e["type"] == "tool_result" and e["callId"] == call["callId"])
            if event["status"] != "completed":
                raise ValueError("tool did not complete")
            payload = json.loads(event["result"])
            if call["tool"] == "fund_month_replay":
                if payload["replay_id"] != result["replay_id"]:
                    raise ValueError("unexpected replay")
            elif call["tool"] == "operator_weekly_report":
                if call["input"]["replay_id"] != result["replay_id"] or payload["optimized"]:
                    raise ValueError("unexpected weekly report")
                reviews.add(call["input"]["date"])
            elif payload["candidate"]["metrics"] != result["metrics"]:
                raise ValueError("evaluation mismatch")
        if reviews != set(result["weekly_dates"]):
            raise ValueError("not all weekly reports were read")
        if (ROOT / "strategies/current.py").read_bytes() != before:
            raise ValueError("current strategy changed")
        text = "\n".join(e["text"] for e in events if e["type"] == "text")
        if not text.strip():
            raise ValueError("DSH produced no summary")
        (run / "summary.md").write_text(text, encoding="utf-8")
        manifest.update(status="verified", tools=sorted(names), weekly_reports_read=len(reviews),
                        current_strategy_unchanged=True)
    except BaseException as exc:
        manifest.update(status="failed", error=type(exc).__name__)
        raise
    finally:
        write(run / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
