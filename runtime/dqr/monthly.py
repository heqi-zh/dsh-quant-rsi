"""Offline calendar replay. Weekly RSI is an evidence-based proposal, not a search."""
import calendar
import json
from datetime import date, timedelta
import math
from pathlib import Path
import re

from .engine import panel, simulate
from .storage import digest, read, write


from .operators import catalogue, evaluate_program, frame_from_bars, provenance_hash, target_weights


class OperatorProgram:
    def __init__(self, by_date, program):
        self.by_date, self.program, self.last_week = by_date, program, None

    def decide(self, history, portfolio):
        day = history[-1]["date"]
        week = date.fromisoformat(day).isocalendar()[:2]
        if week == self.last_week:
            return None
        self.last_week = week
        return target_weights(self.by_date[day], self.program["portfolio"])

    def close(self):
        pass


class EqualExposure:
    def __init__(self, exposure):
        self.exposure = exposure

    def decide(self, history, portfolio):
        if any(portfolio["units"].values()):
            return None
        return {f: self.exposure / len(portfolio["units"]) for f in portfolio["units"]}

    def close(self):
        pass


def monthly_replay(runtime, identity, month=None, program=None):
    program = program or read(runtime.root / "strategies/operators-current.json")
    snapshot = runtime.snapshot(identity)
    bars = panel(snapshot)
    latest = date.fromisoformat(bars[-1]["date"])
    if month is None:
        month = (latest.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("month must be YYYY-MM")
    first = date.fromisoformat(month + "-01")
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    if latest < last:
        raise ValueError("snapshot must cover the complete calendar month")
    start, end = first.isoformat(), last.isoformat()
    before = [b for b in bars if b["date"] < start]
    if len(before) < program.get("warmup_sessions", 100):
        raise ValueError("insufficient pre-month operator warmup")
    config = dict(runtime.config, validation_start=start, validation_end=end)
    # Pin the real implementation, not just its display name, for artifact identity.
    implementation_hash = digest(Path(__file__).read_text(encoding="utf-8"))
    engine_hash = digest(Path(__file__).with_name("engine.py").read_text(encoding="utf-8"))
    operator_hash = provenance_hash()
    program_id = digest({"program": program, "operators": operator_hash})
    replay_id = digest({"snapshot": identity, "config": config, "program": program_id, "engine": engine_hash, "replay": implementation_hash})
    folder = runtime.directory / "monthly" / replay_id
    features, traces = evaluate_program(frame_from_bars(bars), program)
    by_date = {}
    for row in features.to_dicts():
        day, fund = row.pop("datetime"), row.pop("vt_symbol")
        by_date.setdefault(day, {})[fund] = row
    simulation = simulate(snapshot, config, "", runner=OperatorProgram(by_date, program))
    baseline = simulate(snapshot, config, "", runner=EqualExposure(program["portfolio"]["exposure"]))
    evaluation = {"schema": "dqr.month-evaluation.v1", "period": {"start": start, "end": end},
                  "program_id": program_id, "config": config, "candidate": simulation,
                  "baseline": baseline, "baseline_description": "equal-weight buy-and-hold; same initial target exposure and fees",
                  "return_delta": simulation["metrics"]["total_return"] - baseline["metrics"]["total_return"],
                  "conclusion": "单月模拟仅用于检查运行与报告，不作为程序改进或样本外有效性的证明。",
                  "optimized": False, "automatically_promoted": False}
    write(folder / "evaluation.json", evaluation)
    records, weekly = [], []
    initial = {"date": None, "equity": config["initial_cash"], "cash": config["initial_cash"],
               "pending_cash": 0, "units": {f: 0 for f in snapshot["funds"]}, "last_target": None,
               "fees_to_date": 0}
    for offset in range((last - first).days + 1):
        today = first + timedelta(days=offset)
        day = today.isoformat()
        # Morning report: never expose that day's eventual NAV, fills or valuation.
        visible = [b for b in bars if b["date"] < day]
        values = by_date[visible[-1]["date"]]
        available_curve = [p for p in simulation["curve"] if p["date"] < day]
        state = available_curve[-1] if available_curve else initial
        fills = [f for f in simulation["fills"] if f["date"] < day]
        nav_date = visible[-1]["date"]
        previous_nav = records[-1]["visible_nav_date"] if records else None
        previous_week = date.fromisoformat(visible[-2]["date"]).isocalendar()[:2]
        nav_week = date.fromisoformat(nav_date).isocalendar()[:2]
        # Describe the intended next common-session action, without pretending to know publication schedules.
        due = not available_curve or (previous_week != nav_week and nav_date != previous_nav)
        report = {"schema": "dqr.month-daily.v1", "report_date": day, "timing": "morning; NAV dates strictly before report date",
                  "snapshot_id": identity, "program_id": program_id, "visible_nav_date": nav_date,
                  "new_nav_since_previous_report": previous_nav != nav_date,
                  "portfolio_kind": "simulated; starts this month with cash", "account_connected": False,
                  "scores": values, "signal_target": target_weights(values, program["portfolio"]), "portfolio": state,
                  "return_to_date": state["equity"] / config["initial_cash"] - 1,
                  "fills_to_date": fills, "weekly_rebalance_due": due,
                  "action": "下一个可执行共同净值日按周规则模拟调仓" if due else "等待周调仓，不因每日评分变化立即交易",
                  "assumptions": config["assumptions"], "program": program, "operator_trace": traces, "model_analysis": None}
        write(folder / "daily" / (day + ".json"), report)
        render_daily(folder / "daily" / (day + ".md"), report)
        records.append(report)
        if today.weekday() == 6 or today == last:
            period = records[-(today.weekday() + 1):] if today.weekday() == 6 else [r for r in records if date.fromisoformat(r["report_date"]).isocalendar()[:2] == today.isocalendar()[:2]]
            review = weekly_review(period, program_id)
            write(folder / "weekly" / (day + ".json"), review)
            render_weekly(folder / "weekly" / (day + ".md"), review)
            weekly.append(day)
    manifest = {"schema": "dqr.month-replay.v1", "replay_id": replay_id, "snapshot_id": identity,
                "source": snapshot["source"], "retrieved_at": snapshot["retrieved_at"],
                "month": month, "program": program, "program_id": program_id, "operator_hash": operator_hash,
                "operator_count": catalogue()["count"], "operator_trace": traces, "initial_cash": config["initial_cash"],
                "implementation_hash": implementation_hash, "engine_hash": engine_hash,
                "report_days": [r["report_date"] for r in records], "weekly_dates": weekly,
                "daily_reports": len(records), "weekly_reports": len(weekly),
                "rsi_mode": "proposal_only; model reports pending until DSH analysis completes",
                "optimized": False, "automatically_promoted": False,
                "artifact_dir": str(folder), "metrics": simulation["metrics"],
                "baseline_metrics": baseline["metrics"], "return_delta": evaluation["return_delta"],
                "assumptions": config["assumptions"]}
    write(folder / "manifest.json", manifest)
    (folder / "program.json").write_text(json.dumps(program, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "operator-source.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    write(folder / "operators.json", catalogue())
    write(folder / "operator-trace.json", traces)
    from .programs import archive_evaluation
    archive_evaluation(folder, program_id, program, evaluation)
    render_index(folder, manifest)
    return manifest


def weekly_review(reports, program_id):
    first, last = reports[0], reports[-1]
    top = [max(r["scores"], key=lambda f: r["scores"][f]["score"] if r["scores"][f]["score"] is not None else -math.inf) for r in reports]
    switches = sum(a != b for a, b in zip(top, top[1:]))
    evidence = {"start": first["report_date"], "end": last["report_date"],
                "visible_through": last["visible_nav_date"], "leader_switches": switches,
                "equity_change": last["portfolio"]["equity"] - first["portfolio"]["equity"],
                "fees_to_date": last["portfolio"]["fees_to_date"], "latest_scores": last["scores"]}
    return {"schema": "dqr.weekly-proposal.v1", "program_id": program_id, "evidence": evidence,
            "mode": "proposal_only", "author": "program evidence; model analysis pending",
            "daily_evidence": reports, "proposals": [], "model_analysis": None,
            "next_evaluation": "No candidate execution in report-only mode.",
            "optimized": False, "candidate_created": False, "automatically_promoted": False}


def render_daily(path, report):
    p = report["portfolio"]
    rows = [f"| {f} | {v['score'] if v['score'] is not None else '预热不足或计算无有效值'} | {report['signal_target'][f]:.0%} | {p['units'][f]:.2f} |"
            for f, v in report["scores"].items()]
    text = f"""# {report['report_date']} 每日模拟分析

晨报；数据截至 **{report['visible_nav_date']}**。{'有新净值。' if report['new_nav_since_previous_report'] else '没有新净值，沿用上次数据。'}
这是月初从现金开始的模拟组合，不是个人账户。程序版本：`{report['program_id']}`。

模拟资产 **{p['equity']:.2f} 元**，月初至今 **{report['return_to_date']:.2%}**；可用现金 {p['cash']:.2f} 元，待到账 {p['pending_cash']:.2f} 元，累计费用 {p['fees_to_date']:.2f} 元。

| 基金 | 评分 | 信号目标 | 模拟持有份额 |
|---|---:|---:|---:|
""" + "\n".join(rows) + f"\n\n{report['action']}。目标权重是信号输出，实际成交受费用、确认和到账约束。\n\n评分由下列显式算子组合生成；技术指标 RSI 与自我改进 RSI 为两个不同概念。\n\n数据按下一日可见的保守假设处理，缺少历史公布时刻及申赎限制；模拟费用和确认规则仍需产品核实。\n"
    text += "\n## 程序计算：算子表达式与因子值\n\n"
    for feature in report["program"]["features"] + [{"name": "score", "expression": report["program"]["score"]}]:
        values = ", ".join(f"{fund}: {row.get(feature['name'])}" for fund, row in report["scores"].items())
        text += f"- **{feature['name']}** = `{feature['expression']}`；{values}\n"
    text += "\n## 大模型分析\n\n" + (report.get("model_analysis") or {}).get("analysis", "尚未生成；此处不使用模板替代模型分析。") + "\n"
    path.write_text(text, encoding="utf-8")


def render_weekly(path, review):
    e = review["evidence"]
    text = f"# {e['start']} 至 {e['end']} RSI 算子周报\n\n**仅建议；未生成候选、未优化、未评测、未替换当前程序。** 下列数值由程序计算；模型建议单独标注。\n\n可见数据截至 {e['visible_through']}；周内晨报资产变化 {e['equity_change']:.2f} 元，累计费用 {e['fees_to_date']:.2f} 元，评分领先者切换 {e['leader_switches']} 次。\n"
    analysis = review.get("model_analysis")
    text += "\n## 大模型分析与算子建议\n\n" + (analysis["analysis"] if analysis else "尚未生成模型分析。") + "\n"
    for proposal in (analysis or {}).get("proposals", []):
        text += f"\n- **{proposal['feature']}**：{proposal['reason']}\n  建议表达式：`{proposal['expression']}`；未执行、未评测。\n"
    text += "\n" + review["next_evaluation"] + "\n"
    path.write_text(text, encoding="utf-8")


def render_index(folder, manifest):
    m, b = manifest["metrics"], manifest["baseline_metrics"]
    text = f"""# {manifest['month']} 基金月度模拟

完成 {manifest['daily_reports']} 份自然日晨报、{manifest['weekly_reports']} 份周末／月末算子建议报告。使用已有历史数据回放，没有执行实际交易或真实算子优化。

初始模拟资金 {manifest['initial_cash']:.2f} 元，本月程序 `{manifest['program']['name']}`，使用实际 vn.py 算子与显式组合。[程序定义](program.json) · [已接入算子目录](operators.json) · [实际调用记录](operator-trace.json)。

| 月末完整模拟指标 | 算子程序 | 同初始暴露等权持有对照 |
|---|---:|---:|
| 费用后收益 | {m['total_return']:.2%} | {b['total_return']:.2%} |
| 最大回撤 | {m['max_drawdown']:.2%} | {b['max_drawdown']:.2%} |
| 费用（元） | {m['fees']:.2f} | {b['fees']:.2f} |
| 成交笔数 | {m['trade_count']} | {b['trade_count']} |

晨报仅展示报告日期之前的净值与持仓状态；此表使用整月结束后的结果，因此可能与最后一天晨报不同。单月结果不证明策略有效或得到改进。

## 每日报告

"""
    text += "\n".join(f"- [{d}](daily/{d}.md)" for d in manifest["report_days"])
    text += "\n\n## RSI 周报（仅建议）\n\n"
    text += "\n".join(f"- [{d}](weekly/{d}.md)" for d in manifest["weekly_dates"])
    text += "\n\n## 运行边界\n\n使用历史净值快照，非实时账户。确认和到账按共同净值日估计；不含历史暂停申赎、限购信息。数值来自实际 vn.py 算子与基金模拟器；模型分析通过 DSH 单独生成，未生成时明确标注。OpenEvolve 仅归档已评测程序，本次不执行候选搜索或自动晋升。\n"
    (folder / "index.md").write_text(text, encoding="utf-8")


def replay_artifact(runtime, replay_id, kind, day=None):
    if not isinstance(replay_id, str) or not re.fullmatch(r"[0-9a-f]{64}", replay_id):
        raise ValueError("invalid replay ID")
    folder = runtime.directory / "monthly" / replay_id
    manifest = read(folder / "manifest.json")
    if kind == "evaluation":
        return read(folder / "evaluation.json")
    if day not in manifest["weekly_dates"]:
        raise ValueError("date is not a recorded weekly review")
    return read(folder / "weekly" / (day + ".json"))
