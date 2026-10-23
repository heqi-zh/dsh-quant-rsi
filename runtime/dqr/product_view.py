"""Self-contained interactive HTML; raw evidence remains separate from reader copy."""
import json
from pathlib import Path
import re
from .editorial import validate_copy
from .report_view import pick_summary
from .storage import read


def weekly_dates(folder):
    from .publication import report_routes
    known=set(report_routes(folder.parent.parent)['weekly'])
    for path in (folder/'weekly').glob('*.json'):
        if (read(path).get('model_analysis') or {}).get('verified_session'):known.add(path.stem)
    return sorted(known)


def render_daily(path, report, ranked=None, prices=None, report_days=None):
    path=Path(path);folder=path.parent.parent
    if ranked is None:ranked=read(path.with_suffix('.ranked.json'))
    if prices is None:prices=read(folder/'prices.json')
    if report_days is None:
        manifest=read(folder/'manifest.json')
        report_days=manifest.get('navigation_days',manifest['report_days'])
    analysis=report.get('model_analysis') or {}
    opinions={}
    if analysis.get('reader_format')=='fund-cards-v1':
        for line in analysis['analysis'].splitlines():
            code,sep,text=line.partition('：')
            if sep:opinions[code]=text
    summaries={p['code']:pick_summary(p) for p in ranked}
    for summary in summaries.values():
        for text in summary.values():validate_copy(text)
    for text in opinions.values():validate_copy(text)
    validate_copy('。'.join(report['limitations']))
    # Every series ends at this fund's actual as-of valuation. No future samples in HTML.
    series={p['code']:[[d,v] for d,v in sorted(prices.get(p['code'],{}).items()) if d<=p['nav_date']][-121:] for p in ranked}
    payload={'report':report,'ranked':ranked,'summaries':summaries,'opinions':opinions,'series':series,'report_days':report_days,'weekly_dates':weekly_dates(folder)}
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template=Path(__file__).with_name('web').joinpath('product.html').read_text()
    validate_copy(re.sub(r'<script[\s\S]*?</script>','',template))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.with_suffix('.html').write_text(template.replace('__REPORT_DATA__',encoded))
    lines=[f'# {report["date"]} 基金日报','',f'净值截至 {report["nav_cutoff"]} · 覆盖 {report["fund_count"]} 只 · 可评分 {report["scored_count"]} 只','']
    for p in report['recommendations']:
        s=summaries[p['code']]
        lines += [f'## {p["name"]}（{p["code"]}）','',f'近20期收益 {p["values"]["return_20"]:+.2%} · 同类第 {p["rank_in_category"]}/{p["peer_count"]}','',f'**{s["support_label"]}**：{s["support"]}','',f'**{s["weak_label"]}**：{s["weakness"]}','',f'**观察重点**：{s["caution"]}','']
        if p['code'] in opinions:lines+=['**模型判断**：'+p['code']+'：'+opinions[p['code']],'']
    lines+=['## 阅读口径','']+report['limitations']
    content='\n'.join(lines)+'\n';validate_copy(content);path.with_suffix('.md').write_text(content)


def render_weekly(path, report):
    from html import escape
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    analysis=report.get('model_analysis') or {};text=analysis.get('analysis','模型解读正在准备。');validate_copy(text)
    proposals=analysis.get('proposals',[])
    pct=lambda v:'待成熟' if v is None else f'{v:+.2%}'
    lines=[f'# {report["date"]} 筛选程序 RSI 周报','',f'本周更新 {report["updates_this_week"]} 次 · 观察 {len(report["unique_recommended_codes"])} 只基金 · 名单平均替换 {report["mean_replacement_fraction"]:.2%}','',
           '## 成熟反馈','', '|观察期|成熟样本|平均毛收益|同类均值|平均超额|','|---|---|---|---|---|']
    table=''
    for h,f in report['feedback'].items():
        cells=[h+'期',str(f['matured_count']),pct(f['mean_gross_return']),pct(f['mean_category_return']),pct(f['mean_excess_return'])]
        lines.append('|'+ '|'.join(cells)+'|');table+='<tr>'+''.join('<td>'+escape(c)+'</td>' for c in cells)+'</tr>'
    lines+=['','## 模型判断','',text,'','## 待验证的程序建议','']
    cards=''
    for p in proposals:
        validate_copy(p['feature']);validate_copy(p['reason'])
        lines+=[f'### {p["feature"]}','',p['reason'],'',f'`{p["expression"]}`','']
        cards+='<article><span class="tag">待验证 · 未执行</span><h3>'+escape(p['feature'])+'</h3><p>'+escape(p['reason'])+'</p><code>'+escape(p['expression'])+'</code></article>'
    lines+=['观察期按每只基金自身的净值日期计算，起点取报告日当日或之后首条净值。反馈为未计费用的净值观察，重叠样本存在依赖。','',*report['limitations']]
    validate_copy('\n'.join(lines));path.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DQR · 筛选程序周报</title><style>*{box-sizing:border-box}body{margin:0;background:#f7f4fa;color:#282135;font:15px/1.9 system-ui,-apple-system,sans-serif}main{max-width:1000px;margin:40px auto;padding:0 22px}a{color:#7450bd;text-decoration:none}h1{font-size:32px;line-height:1.4}h2{font-size:21px;margin:0 0 16px}h3{font-size:18px;margin:10px 0}section,article{background:white;padding:25px;border:1px solid #e9e2ef;border-radius:13px;margin:20px 0}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.stats div{padding:18px;background:white;border-radius:10px;border:1px solid #e9e2ef}.stats strong{display:block;font-size:28px}.muted,footer{color:#766980;font-size:12px}.tag{color:#7450bd;background:#f0e7f8;border-radius:5px;padding:4px 8px;font-size:11px}.model{white-space:pre-wrap}code{display:block;padding:14px;background:#f4eff8;border-radius:7px;overflow-wrap:anywhere;font-size:13px}.table{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-variant-numeric:tabular-nums}td,th{text-align:right;padding:12px;border-bottom:1px solid #e9e2ef}th:first-child,td:first-child{text-align:left}th{font-weight:500;color:#766980;font-size:12px}@media(max-width:600px){main{margin:22px auto;padding:0 15px}h1{font-size:25px}section,article{padding:18px}.stats{gap:8px}.stats div{padding:12px}.stats strong{font-size:22px}}</style><main>'''
    html+='<a href="../daily/'+report['date']+'.html">← 返回基金日报</a><h1>筛选程序，本周有哪些值得改进？</h1><p class="muted">'+report['week_start']+' — '+report['date']+' · 净值截至 '+report['nav_cutoff']+'</p>'
    html+='<div class="stats">'+''.join('<div><span class="muted">'+label+'</span><strong>'+value+'</strong></div>' for label,value in [('净值更新',str(report['updates_this_week'])+' 次'),('名单平均替换',f'{report["mean_replacement_fraction"]:.1%}'),('候选执行','0 次')])+'</div>'
    html+='<section><h2>已有反馈</h2><div class="table"><table><thead><tr><th>观察期</th><th>成熟样本</th><th>平均毛收益</th><th>同类均值</th><th>平均超额</th></tr></thead><tbody>'+table+'</tbody></table></div><p class="muted">累计成熟观察；按基金自身净值日期计算。样本相互重叠，费用与交易确认需在后续评测中计入。</p></section>'
    html+='<section><h2>模型判断</h2><div class="model">'+escape(text)+'</div></section><h2>具体改进建议</h2>'+cards+'<footer>所有建议保持未执行状态，当前筛选程序未自动替换。<p>'+escape(' '.join(report['limitations']))+'</p></footer></main></html>'
    path.with_suffix('.html').write_text(html)
