"""Current operator program on an as-of snapshot; shares the replay computation."""
from datetime import date, timedelta

from .engine import panel, simulate
from .monthly import OperatorProgram, render_daily
from .operators import evaluate_program, frame_from_bars, provenance_hash, target_weights
from .storage import digest, read, write


def daily(runtime, snapshot_id, as_of=None):
    snapshot = runtime.snapshot(snapshot_id)
    all_bars = panel(snapshot)
    as_of = as_of or (date.fromisoformat(all_bars[-1]["date"]) + timedelta(days=1)).isoformat()
    date.fromisoformat(as_of)
    bars = [b for b in all_bars if b["date"] < as_of]
    program = read(runtime.root / "strategies/operators-current.json")
    if len(bars) < program.get("warmup_sessions", 100):
        raise ValueError("insufficient operator warmup")
    features, traces = evaluate_program(frame_from_bars(bars), program)
    by_date = {}
    for row in features.to_dicts():
        day, fund = row.pop("datetime"), row.pop("vt_symbol")
        by_date.setdefault(day, {})[fund] = row
    config = dict(runtime.config, validation_end=bars[-1]["date"])
    visible_snapshot = dict(snapshot, rows=[r for r in snapshot["rows"] if r["date"] < as_of])
    simulation = simulate(visible_snapshot, config, "", runner=OperatorProgram(by_date, program))
    state = simulation["curve"][-1]
    values = by_date[bars[-1]["date"]]
    result = {"schema": "dqr.operator-daily.v1", "snapshot_id": snapshot_id, "report_date": as_of,
              "program_id": digest({"program": program, "operators": provenance_hash()}),
              "visible_nav_date": bars[-1]["date"], "new_nav_since_previous_report": None,
              "portfolio_kind": "model_portfolio", "account_connected": False,
              "portfolio": state, "scores": values, "signal_target": target_weights(values, program["portfolio"]),
              "return_to_date": state["equity"] / config["initial_cash"] - 1,
              "fills_to_date": simulation["fills"], "program": program, "operator_trace": traces,
              "analysis_period": {"start": config["validation_start"], "end": config["validation_end"]},
              "action": "按已可见净值的周调仓规则执行模拟；每日评分不自动触发实际交易",
              "assumptions": config["assumptions"], "model_analysis": None}
    path = runtime.directory / "operator-daily" / (digest(result) + ".json")
    write(path, result)
    render_daily(path.with_suffix(".md"), result)
    markdown = path.with_suffix(".md")
    text = markdown.read_text().replace("月初从现金开始", config["validation_start"] + " 从现金开始").replace("月初至今", "模拟期至今").replace("没有新净值，沿用上次数据。", "未与上一份日报比较净值更新。")
    markdown.write_text(text, encoding="utf-8")
    return dict(result, report_path=str(path))
