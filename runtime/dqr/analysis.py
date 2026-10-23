"""As-of evidence and separately attributed DSH model-authored reports."""
import ast
import json
import os
from pathlib import Path
import re

from .monthly import render_daily, render_weekly
from .operators import catalogue, REGISTRY
from .storage import digest, read, write


def location(runtime, replay_id, kind, day):
    if not re.fullmatch(r"[0-9a-f]{64}", replay_id) or kind not in {"daily", "weekly"}:
        raise ValueError("invalid report location")
    folder = runtime.directory / "screening" / "runs" / replay_id
    if not folder.exists():
        folder = runtime.directory / "product" / "runs" / replay_id
    if not folder.exists():
        folder = runtime.directory / "monthly" / replay_id
    manifest = read(folder / "manifest.json")
    if day not in manifest["report_days" if kind == "daily" else "weekly_dates"]:
        raise ValueError("date not recorded")
    return folder / kind / (day + ".json")


def context(runtime, replay_id, kind, day):
    path = location(runtime, replay_id, kind, day)
    report = read(path)
    report.pop("model_analysis", None)
    if kind == "weekly":
        for item in report["daily_evidence"]:
            item.pop("model_analysis", None)
    product = report.get("schema", "").startswith("dqr.product-")
    if product:
        # Preserve scalar paths while keeping raw exclusions, curves and samples on disk.
        report.pop("exclusions", None)
        report.pop("theme_coverage", None)
        report.pop("data_signature", None)
        def compact_pick(pick, weekly=False):
            result={k:pick[k] for k in ("code","name","category","group","nav_date","rank_in_category","peer_count","purchase_status") if k in pick}
            result["values"]={k:v for k,v in pick["values"].items() if k in ({"return_20","return_60","downside_volatility","drawdown_60","score"} if weekly else {"return_20","return_60","daily_volatility_20","downside_volatility","drawdown_60","ema_gap","technical_rsi","momentum_contribution","trend_contribution","risk_contribution","drawdown_contribution","score"})}
            return result
        if kind == "daily":
            report["recommendations"]=[compact_pick(p) for p in report["recommendations"]]
        else:
            for feedback in report["feedback"].values():feedback.pop("samples",None)
            report["daily_evidence"]=[{k:row[k] for k in ("date","nav_cutoff","data_updated","eligible_count","selection_changes")} | {"recommended_codes":[p["code"] for p in row["recommendations"]]} for row in report["daily_evidence"]]
            original=read(path)
            report["latest_recommendations"]=[compact_pick(p,True) for p in original["daily_evidence"][-1]["recommendations"]]
    cat = catalogue()
    rules = "Write reader-facing Chinese directly. 禁止使用不是、并非、而非、而是、不代表、不等于、不意味着等对照否定句式；直接描述数据及含义。 Historical as-of report. No future data, no account. Distinguish calculation from interpretation. Proposals are untested; do not optimize or promote."
    if report.get("schema", "").startswith(("dqr.screening-", "dqr.product-")) and (day == "2026-09-01" or report.get("week_start") == "2026-08-31"):
        rules += " September 1 is the first recorded shortlist: its zero replacement fraction is initialization, not evidence of retaining a prior list. No August recommendation list was computed."
    candidates = cat["operators"]
    if product:
        allowed={"ts_rank","ts_mean","ts_std","ts_delay","ts_corr","ts_max","ts_min","ts_quantile","ts_decay_linear","ts_delta","cs_rank","greater","less","abs","ta_rsi","am_ema","ts_slope","ts_rsquare"}
        candidates=[o for o in candidates if o["name"] in allowed]
        rules += " Compact evidence view: raw exclusions and individual feedback samples remain archived. Operator catalogue is the NAV-compatible proposal subset."
    return {"replay_id": replay_id, "kind": kind, "date": day, "report": report,
            "operators": [{"name": o["name"], "signature": o["signature"], "fund_nav_usage": o["fund_nav_usage"]}
                          for o in candidates],
            "rules": rules}


def pointer(data, path):
    if not isinstance(path, str) or not path.startswith("/report/"):
        raise ValueError("evidence pointer must start /report/")
    value = data
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    if isinstance(value, (dict, list)):
        raise ValueError("cite scalar evidence fields")
    return value


def save_analysis(runtime, replay_id, kind, day, analysis, evidence, proposals):
    if not isinstance(analysis, str) or not 100 <= len(analysis) <= 12000:
        raise ValueError("analysis must be 100..12000 characters")
    from .editorial import validate_copy
    validate_copy(analysis)
    ctx = context(runtime, replay_id, kind, day)
    if not isinstance(evidence, list) or len(evidence) < 3:
        raise ValueError("at least three exact evidence references required")
    for item in evidence:
        actual = pointer(ctx, item["path"])
        if actual != item["value"]:
            raise ValueError("evidence value mismatch at " + item["path"])
    if kind == "weekly" and (not isinstance(proposals, list) or not 1 <= len(proposals) <= 5):
        raise ValueError("weekly analysis requires 1..5 explicit operator proposals")
    program = ctx["report"].get("program") or ctx["report"]["daily_evidence"][-1]["program"]
    names = set(REGISTRY) | set(program.get("operators", {}))
    for proposal in proposals:
        if not all(isinstance(proposal.get(k), str) and proposal[k].strip() for k in ("feature", "expression", "reason")):
            raise ValueError("each proposal needs feature, expression and reason")
        validate_copy(proposal["feature"])
        validate_copy(proposal["reason"])
        tree = ast.parse(proposal["expression"], mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in names):
                raise ValueError("proposal uses unknown operator")
        proposal["status"] = "not_executed_or_evaluated"
    if kind == "weekly" and ctx["report"].get("schema", "").startswith("dqr.product-"):
        from .editorial import validate_weekly_prose
        validate_weekly_prose(analysis, proposals)
    path = location(runtime, replay_id, kind, day)
    report = read(path)
    reader_format = os.environ.get('DQR_READER_FORMAT') if kind == 'daily' else None
    if reader_format == 'fund-cards-v1':
        lines = analysis.splitlines()
        codes = [p['code'] for p in report['recommendations']]
        if len(lines) != len(codes) or any(not line.startswith(code+'：') for line,code in zip(lines,codes)):
            raise ValueError('Reader format requires exactly one line per recommended fund, in order: code：judgment')
        if any(not 35 <= len(line) <= 180 for line in lines) or re.search(r'\d+\.\d{3,}',analysis):
            raise ValueError('Reader judgment must be 35..180 characters per fund; numbers at most two decimal places')
        if re.search(r'贡献[为是达约\s]*[0-9]|第[0-9]+|[0-9]+只中', analysis) or any(len(re.findall(r'[0-9]+(?:\.[0-9]+)?%',line))>2 for line in lines):
            raise ValueError('请写简明判断：每只最多引用两项百分比数据；删除贡献分值和重复排名，解释优势、风险及后续观察点。')
        from .editorial import validate_fund_percentages
        validate_fund_percentages(analysis, report['recommendations'], report.get('categories'))
    if report.get('model_analysis'):
        write(path.parent / 'raw-analyses' / day / (digest(report['model_analysis'])+'.json'), report['model_analysis'])
    report["model_analysis"] = {"analysis": analysis, "evidence": evidence, "proposals": proposals,
                                "context_hash": digest(ctx), "model": os.environ.get("DQR_MODEL", "unspecified"),
                                "provenance": "DSH tool submission; verify associated session events",
                                "optimized": False}
    if reader_format:
        report['model_analysis']['reader_format'] = reader_format
        report['model_analysis']['editorial_version'] = 2
    write(path, report)
    if report.get("schema", "").startswith("dqr.product-daily"):
        from .product_view import render_daily as render_product
        render_product(path.with_suffix(".md"), report)
    elif report.get("schema", "").startswith("dqr.product-weekly"):
        from .product_view import render_weekly as render_product_weekly
        render_product_weekly(path.with_suffix(".md"), report)
    elif report.get("schema", "").startswith("dqr.screening-"):
        from .screening import render
        render(path.with_suffix(".md"), report)
    else:
        (render_daily if kind == "daily" else render_weekly)(path.with_suffix(".md"), report)
    return {"saved": str(path.with_suffix(".md")), "context_hash": digest(ctx), "evidence_count": len(evidence), "optimized": False}


def enforce_job(operation, request):
    raw = os.environ.get("DQR_REPORT_JOB")
    if not raw:
        return
    job = json.loads(raw)
    if operation not in {"analysis-context", "analysis-save"}:
        raise ValueError("isolated report job permits only its own context and analysis submission")
    if any(request.get(key) != job[key] for key in ("replay_id", "kind", "date")):
        raise ValueError("report job cannot access another date or report")
