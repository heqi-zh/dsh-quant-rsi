"""Use real DSH sessions for every daily/weekly report; no candidate search."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from dqr.analysis import context, location
from dqr.editorial import validate_copy,validate_fund_percentages,validate_weekly_prose
from dqr.service import Runtime
from dqr.storage import digest, read, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--date", help="Optional one report date for smoke testing")
    parser.add_argument("--kind", choices=["daily", "weekly"])
    parser.add_argument("--reader-daily", action="store_true", help="Regenerate old daily prose as concise per-fund reader judgments")
    args = parser.parse_args()
    runtime = Runtime(ROOT)
    report_folder = runtime.directory / "screening/runs" / args.replay
    product_folder = runtime.directory / "product/runs" / args.replay
    product = product_folder.exists()
    if product:
        report_folder = product_folder
    screening = report_folder.exists()
    if not screening:
        report_folder = runtime.directory / "monthly" / args.replay
    manifest = read(report_folder / "manifest.json")
    spec = importlib.util.spec_from_file_location("launcher", ROOT / "scripts/run-research.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    node, (token, model) = launcher.node_path(), launcher.codex_login()
    jobs = [{"replay_id": args.replay, "kind": kind, "date": day}
            for kind, key in [("daily", "report_days"), ("weekly", "weekly_dates")]
            for day in manifest[key] if (not args.kind or kind == args.kind) and (not args.date or day == args.date)]
    pinned = {str(p): p.read_bytes() for p in [ROOT / "strategies/current.py", ROOT / "strategies/operators-current.json", ROOT / "strategies/screening-current.json"] if p.exists()}

    def run(job):
        artifact = location(runtime, job["replay_id"], job["kind"], job["date"])
        old = read(artifact).get("model_analysis")
        # Only skip reports with independently verified prior session evidence and matching inputs.
        reader_job = screening and (args.reader_daily or product) and job['kind'] == 'daily'
        valid_old = True
        if old:
            try:
                validate_copy(old['analysis'])
                if reader_job:
                    report=read(artifact)
                    validate_fund_percentages(old['analysis'],report['recommendations'],report.get('categories'))
                elif product and job['kind']=='weekly':validate_weekly_prose(old['analysis'],old.get('proposals',[]))
            except ValueError:valid_old=False
        if valid_old and old and (not reader_job or old.get('reader_format') == 'fund-cards-v1' and old.get('editorial_version') == 2) and old.get("verified_session") and old.get("context_hash") == digest(context(runtime, **dict(replay_id=job["replay_id"], kind=job["kind"], day=job["date"]))):
            proof = Path(old["verified_session"]) / "manifest.json"
            if proof.is_file() and read(proof).get("status") == "verified":
                return {**job, "status": "already_verified"}
        folder = runtime.directory / "dsh-analysis-runs" / uuid.uuid4().hex
        folder.mkdir(parents=True)
        prefix = "daily_analysis" if job["kind"] == "daily" else "operator_weekly"
        focus = '''本任务是基金池的每日筛选。日报应逐只说明5只推荐基金的同类排名和具体算子贡献，指出动量/趋势与风险的冲突，引用真实因子值，区分数据更新与沿用名单。名额用于组织观察名单。所有持仓陈述须有真实持仓证据。
周报围绕筛选程序：结合名单替换率、同类排名和已成熟的1/5期观察反馈，提出1至3条算子表达式修改建议，说明证据、代价和后续验证办法。反馈是未计费用的净值信号观察，重叠样本存在依赖；交易收益还需纳入实际交易流程。不要执行任何优化或候选程序。
当前目录有幸存者偏差，同类分类仍宽；不要宣称是全市场最优基金。''' if screening else '''日报解释算子贡献、目标/模拟持仓偏离与费用。周报解释组合表现并提出算子建议。当前只有两只基金，排名分辨率有限。'''
        if product:
            focus += " 基金池覆盖多个热门主题，具体规模、主题覆盖、分组和分散规则均以工具返回为准。海外与境内净值日期可能不同。"
        task = f'''你正在生成 DQR 的一份真实历史分析报告。任务参数：{json.dumps(job)}。
必须先调用 {prefix}_context(replay_id,date)，再根据实际证据调用 {prefix}_save 保存你的中文分析。
这是独立的截至当日会话，不允许访问其他日期、完整月末评测、网络、修改策略或优化候选。
{focus}
禁止使用“不是、并非、而非、而是、不代表、不等于、不意味着”等对照否定句式，直接说明数据、含义和适用范围。
所有数字必须来自工具。不要捏造新闻、因果、未来结果；推断明确标注。技术指标 RSI 与自我改进 RSI 区分。
analysis 写约400至800个中文字，不要把数值计算宣称为模型计算。至少3条 evidence_json：{{"path":"/report/...","value":原始精确值}}，必须精确复制工具值，不用四舍五入值。
周报 proposals_json 是 [{{"feature":"要修改或新增的因子名","expression":"由目录中的函数、既有自定义算子与因子组成的表达式","reason":"依据与代价"}}]，每条为未执行未验证建议；日报使用 []。
遇到保存校验失败可修正后重试。成功保存后用一句话结束。不要调用任何其他工具。'''
        if product and job['kind']=='weekly':
            task += '''\n周报可读性要求：正文约400至650字，先概括程序本周表现，再解释1至3项改进建议的证据、代价与验证方法。删除重复的逐基金排名。收益、波动和替换比例使用百分比并保留两位小数，其他数值最多两位小数。正文只用中文因子名，变量名、函数和公式放在proposals_json的expression字段；reason也遵守两位小数。原始精度仅写evidence_json。'''
        if reader_job:
            task += '''\n日报可读性要求优先于上述通用长度要求：analysis严格按recommendations顺序每只写1行，每行“6位基金代码：判断”，每行35至180字，不要空行、标题、项目符号或其他段落。每行只讲这只基金最值得注意的优势与弱点，以及为何仍值得关注或需要谨慎，使用普通人能看懂的中文。页面已展示关键数据，禁止写贡献分值或重复排名；每行最多引用两项百分比数据，其余文字用于解释优势、风险和后续观察点。可以说短期修复、下跌中相对抗跌、趋势与风险冲突，但不得捏造因果。不要显示程序变量名、公式或原始长小数；收益/波动用百分数保留2位小数，其他数值最多2位。原始精度只放evidence_json。不要把高分说成必然上涨。'''
        (folder / "task.txt").write_text(task, encoding="utf-8")
        env = dict(os.environ, DSH_HOME=str(ROOT / ".dsh"), DSH_TELEMETRY_DISABLED="1",
                   DQR_MODEL=model, DQR_CODEX_ACCESS_TOKEN=token, DQR_REPORT_JOB=json.dumps(job))
        env.pop("DQR_REPORT_ONLY", None)
        env.pop("DQR_RESEARCH_RUN_ID", None)
        if reader_job:
            env['DQR_READER_FORMAT'] = 'fund-cards-v1'
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        command = [node, str(ROOT / "node_modules/@deepseek-ai/dsh/lib/bin.js"), "--profile", "dqr-research",
                   "--patch", str(ROOT / "configs/cordis.patch.yml"), "--patch", str(ROOT / "configs/dsh-research.patch.yml")]
        if screening:
            command += ["--patch", str(ROOT / "configs/dsh-screening.patch.yml")]
        command += ["--json", task]
        proof = {**job, "model": model, "status": "running", "run_dir": str(folder)}
        write(folder / "manifest.json", proof)
        try:
            with (folder / "events.jsonl").open("w") as out, (folder / "stderr.log").open("w") as err:
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err, start_new_session=True)
                try:
                    status = process.wait(timeout=180)
                except BaseException:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise
            if status:
                raise ValueError("DSH process failed")
            events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
            calls = [e for e in events if e["type"] == "tool_call"]
            if {c["tool"] for c in calls} != {prefix + "_context", prefix + "_save"}:
                raise ValueError("unexpected report tool calls")
            context_call = next(c for c in calls if c["tool"] == prefix + "_context")
            context_result = next(e for e in events if e["type"] == "tool_result" and e["callId"] == context_call["callId"] and e["status"] == "completed")
            saves = [c for c in calls if c["tool"] == prefix + "_save" and any(e["type"] == "tool_result" and e["callId"] == c["callId"] and e["status"] == "completed" for e in events)]
            if not saves:
                failures=[e.get("result", "") for e in events if e["type"] == "tool_result" and e["status"] != "completed"]
                raise ValueError("No successful analysis submission: " + str(failures[-1] if failures else "model ended without saving")[:600])
            saved = saves[-1]
            if events.index(context_result) >= events.index(saved):
                raise ValueError("analysis preceded evidence")
            report = read(artifact)
            if report["model_analysis"]["analysis"] != saved["input"]["analysis"]:
                raise ValueError("model text differs from saved report")
            # Headless tool_result text is truncated at ~8 KB; compare against the
            # same immutable as-of context, not a lossy event display string.
            if report["model_analysis"]["context_hash"] != digest(context(runtime, job["replay_id"], job["kind"], job["date"])):
                raise ValueError("model did not use the saved evidence")
            if any(Path(p).read_bytes() != data for p, data in pinned.items()):
                raise ValueError("selected program changed")
            report["model_analysis"]["verified_session"] = str(folder)
            write(artifact, report)
            proof.update(status="verified", context_hash=report["model_analysis"]["context_hash"],
                         model_text_hash=digest(saved["input"]["analysis"]), current_programs_unchanged=True)
        except Exception as exc:
            proof.update(status="failed", error=type(exc).__name__ + ": " + str(exc))
        write(folder / "manifest.json", proof)
        return proof

    results = []
    with ThreadPoolExecutor(max_workers=min(4, max(1, args.workers))) as executor:
        for future in as_completed([executor.submit(run, job) for job in jobs]):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    failed = [r for r in results if r["status"] == "failed"]
    write(report_folder / "analysis-run.json", {"jobs": results, "failures": len(failed)})
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
