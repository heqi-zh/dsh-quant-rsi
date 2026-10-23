"""Category-relative fund screening, causal signal diagnostics and report artifacts.

No portfolio simulator, candidate search or promotion is called from this module.
"""
from collections import defaultdict
from datetime import date, timedelta
import csv
import html
import math
from pathlib import Path
import statistics

from .operators import evaluate_program, frame_from_bars, provenance_hash, validate_program
from .storage import digest, read, write

GROUPS = {'stock':'股票型','index':'指数型-股票','mixed':'混合型-偏股','bond':'债券型-长债'}
CONTRIBUTIONS = ['momentum_contribution','trend_contribution','risk_contribution','drawdown_contribution']
LABELS = {'return_20':'20期总收益','return_60':'60期总收益','daily_volatility_20':'20期日波动',
          'downside_volatility':'下行波动','drawdown_60':'距60期高点','trend_slope':'趋势斜率',
          'trend_fit':'趋势拟合度','ema_gap':'EMA10/30偏离','technical_rsi':'技术指标RSI(14)',
          'return_quantile':'日收益10%分位','risk_adjusted_momentum':'风险调整动量',
          'smoothed_momentum':'平滑动量','momentum_contribution':'动量贡献(40%)',
          'trend_contribution':'趋势贡献(25%)','risk_contribution':'风险贡献(20%)',
          'drawdown_contribution':'回撤贡献(15%)'}
LIMITS = [
    '当前目录及历史完整性筛选存在幸存者偏差；本页是历史回放，不是严格时点基金池的收益证明。',
    '仅使用报告日前的净值，假设前一日净值次日可知；数据源缺少真实发布时间，不能保证晨间已全部发布。',
    '同类排名分组仍较宽，可能重复暴露于同一行业；5个推荐名额不是资金权重。',
    '申购状态为历史接口文本；费用、限额、渠道和份额适用性未核验，名单不代表可直接成交。',
    '默认权重未优化；技术指标RSI仅作为解释项，不参与当前分数。周报RSI指程序自我改进建议。',
]

def calculate(dataset, program, before=None):
    """Keep each symbol's own history; never intersect all fund dates or backfill."""
    metadata = {f['code']:f for f in dataset['funds']}
    bars = {g:defaultdict(dict) for g in GROUPS}
    for row in dataset['rows']:
        if before and row['date'] >= before: continue
        bars[metadata[row['code']]['group']][row['date']][row['code']] = row
    values, prices, trace = defaultdict(dict), defaultdict(dict), {}
    for group, days in bars.items():
        if not days: continue
        frame = frame_from_bars([{'date':d,'funds':items} for d,items in sorted(days.items())])
        output, trace[group] = evaluate_program(frame,program)
        for row in output.to_dicts():
            day,code = row.pop('datetime'),row.pop('vt_symbol')
            values[day][code] = row
        for row in frame.to_dicts(): prices[row['vt_symbol']][row['datetime']] = row['total_return_index']
    return dict(values),dict(prices),trace

def daily_report(dataset, program, values, day, previous=None):
    available = sorted(d for d in values if d < day)
    if not available: raise ValueError('no earlier NAV')
    cutoff = available[-1]
    # Expected session explicitly prevents a missing latest session from silently becoming current.
    expected = max(d for d in dataset['calendar'] if d < day)
    metadata = {f['code']:f for f in dataset['funds']}
    raw = {(r['date'],r['code']):r for r in dataset['rows'] if r['date'] <= cutoff}
    counts = defaultdict(int)
    for d,code in raw: counts[code] += 1
    ranked, exclusions, summaries, recommendations = [], [], {}, []
    for group, slots in program['selection']['slots'].items():
        peers = []
        for code,meta in metadata.items():
            if meta['group'] != group: continue
            v = values.get(expected,{}).get(code)
            observation = raw.get((expected,code),{})
            reason = ('missing_latest_nav' if v is None else 'insufficient_warmup' if counts[code] < program.get('warmup_sessions',100)
                      else 'invalid_score' if v['score'] is None or not math.isfinite(v['score']) else None)
            if reason:
                exclusions.append({'code':code,'reason':reason}); continue
            peers.append({**meta,'nav_date':expected,'nav':observation['nav'],
                          'purchase_status':observation.get('purchase_status','unknown'),'values':v})
        peers.sort(key=lambda r:(-r['values']['score'],r['code']))
        chosen = 0
        for rank,p in enumerate(peers,1):
            p['rank_in_category'] = rank
            p['peer_count'] = len(peers)
            p['eligible'] = p['purchase_status'] == program['selection']['purchase_status']
            if not p['eligible']: exclusions.append({'code':p['code'],'reason':'subscription_not_verified_open','status':p['purchase_status']})
            p['selected'] = p['eligible'] and chosen < slots
            if p['selected']: recommendations.append(p); chosen += 1
        ranked.extend(peers)
        summaries[group] = {'category':GROUPS[group],'scored':len(peers),'eligible':sum(p['eligible'] for p in peers),'slots':slots,'selected':chosen,
                            'median_return_20':statistics.median(p['values']['return_20'] for p in peers) if peers else None,
                            'median_daily_volatility_20':statistics.median(p['values']['daily_volatility_20'] for p in peers) if peers else None}
    codes = {r['code'] for r in recommendations}
    old = {r['code'] for r in previous['recommendations']} if previous else codes
    report = {'schema':'dqr.screening-daily.v1','date':day,'nav_cutoff':cutoff,'expected_nav_date':expected,
              'data_updated':previous is None or cutoff != previous['nav_cutoff'],
              'fund_count':len(metadata),'scored_count':len(ranked),'eligible_count':sum(p['eligible'] for p in ranked),
              'program':program,'program_id':digest(program),'categories':summaries,'recommendations':recommendations,
              'selection_changes':{'added':sorted(codes-old),'removed':sorted(old-codes),'replacement_fraction':len(codes-old)/len(codes) if codes else 0},
              'exclusions':exclusions,'limitations':LIMITS,'model_analysis':None,'optimized':False}
    return report,ranked

def signal_feedback(reports, prices, calendar, cutoff, horizon):
    """Matured gross NAV signal outcomes from next available valuation, not fills.

    Each updated shortlist is one signal. Entry is the first reference session on
    or after report day; endpoint is horizon sessions later. Both must be known
    by cutoff. Compare each pick with its same-day eligible category peers.
    """
    samples, pending = [], 0
    for report,ranked in reports:
        if not report['data_updated'] or report['date'] > cutoff: continue
        future = [d for d in calendar if d >= report['date']]
        if len(future) <= horizon or future[horizon] > cutoff:
            pending += len(report['recommendations']); continue
        start,end = future[0],future[horizon]
        def ret(code):
            p = prices.get(code,{})
            return p[end]/p[start]-1 if start in p and end in p else None
        for selected in report['recommendations']:
            outcome = ret(selected['code'])
            peers = [ret(r['code']) for r in ranked if r['group']==selected['group'] and r['eligible']]
            peers = [r for r in peers if r is not None]
            if outcome is None or not peers: pending += 1; continue
            baseline = statistics.mean(peers)
            samples.append({'signal_date':report['date'],'code':selected['code'],'group':selected['group'],
                            'start_nav_date':start,'end_nav_date':end,'gross_return':outcome,'category_mean_return':baseline,
                            'excess_return':outcome-baseline,'peer_count':len(peers)})
    return {'horizon_sessions':horizon,'matured_count':len(samples),'pending_count':pending,
            'mean_gross_return':statistics.mean(s['gross_return'] for s in samples) if samples else None,
            'mean_category_return':statistics.mean(s['category_mean_return'] for s in samples) if samples else None,
            'mean_excess_return':statistics.mean(s['excess_return'] for s in samples) if samples else None,
            'positive_excess_fraction':statistics.mean(s['excess_return']>0 for s in samples) if samples else None,
            'samples':samples,'interpretation':'Overlapping signal observations, not independent trades; gross NAV diagnostics without fees, confirmation or settlement. No portfolio P&L.'}

def weekly_report(reports, prices, calendar, day):
    visible = [(r,p) for r,p in reports if r['date'] <= day]
    cutoff = visible[-1][0]['nav_cutoff']
    start = (date.fromisoformat(day)-timedelta(days=date.fromisoformat(day).weekday())).isoformat()
    week = [r for r,_ in visible if r['date'] >= start]
    updates = [r for r in week if r['data_updated']]
    return {'schema':'dqr.screening-weekly.v1','date':day,'week_start':start,'nav_cutoff':cutoff,
            'program':week[-1]['program'],'program_id':week[-1]['program_id'],'fund_count':week[-1]['fund_count'],
            'updates_this_week':len(updates),'mean_replacement_fraction':statistics.mean(r['selection_changes']['replacement_fraction'] for r in updates) if updates else 0,
            'unique_recommended_codes':sorted({p['code'] for r in week for p in r['recommendations']}),
            'feedback':{str(h):signal_feedback(visible,prices,calendar,cutoff,h) for h in [1,5]},
            'daily_evidence':[{k:r[k] for k in ('date','nav_cutoff','data_updated','eligible_count','categories','recommendations','selection_changes')} for r in week],
            'limitations':LIMITS+['反馈仅纳入截至本周已成熟的观察；重叠样本不能作为独立交易胜率或显著性检验。'],
            'model_analysis':None,'optimized':False,'candidate_runs':0}

def charts(folder, report, ranked, prices):
    import os
    os.environ.setdefault('MPLCONFIGDIR',str(folder / '.matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import font_manager
    candidates = [Path('/System/Library/Fonts/STHeiti Medium.ttc'), Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    font_path = next((p for p in candidates if p.exists()), None)
    if font_path is None:
        raise RuntimeError('Chinese font required: install Noto Sans CJK or configure a supported system font')
    font_manager.fontManager.addfont(str(font_path))
    matplotlib.rcParams['font.family'] = font_manager.FontProperties(fname=str(font_path)).get_name()
    matplotlib.rcParams['axes.unicode_minus'] = False
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'#f5f7fb','axes.facecolor':'white'})
    fig,axes = plt.subplots(2,2,figsize=(14,9),layout='constrained')
    picks = report['recommendations']; cutoff = report['nav_cutoff']
    for p in picks:
        series = prices[p['code']]
        dates = sorted(d for d in series if d <= cutoff)[-60:]
        base = series[dates[0]]
        axes[0,0].plot([date.fromisoformat(d) for d in dates],[100*series[d]/base for d in dates],label=p['name'][:12]+' '+p['code'],linewidth=1.8)
    axes[0,0].set_title('近60期收益走势（含分红，起点为100）')
    axes[0,0].legend(ncol=2,fontsize=7); axes[0,0].tick_params(axis='x',rotation=20)
    bottom = np.zeros(len(picks))
    for name,label in zip(CONTRIBUTIONS,['上涨动力 40%','近期趋势 25%','下跌稳定性 20%','距高点幅度 15%']):
        v = [p['values'][name] for p in picks]
        axes[0,1].bar([p['code'] for p in picks],v,bottom=bottom,label=label); bottom += np.array(v)
    axes[0,1].set_title('入选分数来自哪里（不是预期收益）'); axes[0,1].set_ylim(0,1.05); axes[0,1].legend(fontsize=8,ncol=2)
    for group in GROUPS:
        peers = [r for r in ranked if r['group']==group]
        axes[1,0].scatter([100*p['values']['daily_volatility_20'] for p in peers],[100*p['values']['return_20'] for p in peers],s=16,alpha=.5,label=GROUPS[group])
    for p in picks:
        x,y = 100*p['values']['daily_volatility_20'],100*p['values']['return_20']
        axes[1,0].scatter([x],[y],marker='*',s=170,color='black'); axes[1,0].annotate(p['code'],(x,y),fontsize=8,xytext=(4,5),textcoords='offset points')
    axes[1,0].set(xlabel='近20期日波动（%，越左越稳定）',ylabel='近20期收益（%）',title='基金池收益与波动（星号为本次入选）')
    axes[1,0].legend(fontsize=8)
    labels = [p['code'] for p in picks]
    axes[1,1].barh(labels,[100*p['values']['drawdown_60'] for p in picks],color='#cf6c53')
    axes[1,1].set(title='比近60期高点低多少（并非最大回撤）',xlabel='距近期高点（%，越接近0越靠近高点）')
    fig.suptitle(f'基金日报 · {report["date"]} · 净值截至 {cutoff} · {report["fund_count"]}只基金',fontsize=15,fontweight='bold')
    path = folder/'charts'/f'{report["date"]}.png'; path.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(path,dpi=140)
    renderer = fig.canvas.get_renderer()
    for n, ax in enumerate(axes.flat, 1):
        bounds = ax.get_tightbbox(renderer).transformed(fig.dpi_scale_trans.inverted()).padded(.08)
        fig.savefig(path.with_name(path.stem+f'-{n}.png'),dpi=160,bbox_inches=bounds)
    plt.close(fig)
    return '../charts/'+path.name

def fmt(value):
    return '缺失' if value is None else f'{value:.6f}' if isinstance(value,float) else str(value)

def render(path, report):
    """Write Markdown plus a self-contained HTML page with linked real-data charts."""
    daily = report['schema']=='dqr.screening-daily.v1'
    if daily:
        from .report_view import render_daily as readable_daily
        return readable_daily(path, report)
    title = f'DQR {report["date"]} '+('基金推荐日报' if daily else '筛选程序 RSI 周报')
    lines = [f'# {title}', '', f'净值截止：{report["nav_cutoff"]} · 基金池：{report["fund_count"]} · 程序：{report["program_id"][:12]}', '',
             '**程序计算与模型分析分别列示。当前程序未经优化，周报不执行建议。**','']
    if daily:
        lines += [f'有效评分 {report["scored_count"]} 只；历史申购状态符合筛选条件 {report["eligible_count"]} 只。'+('本次净值更新。' if report['data_updated'] else '没有新净值，沿用前次名单。'),'',
                  '股票1只、指数1只、偏股混合2只、长债1只，分别取同类排名靠前且状态开放的基金；名额不是仓位。','',
                  '|基金|类别|同类排名|评分|20期收益|下行波动|距60期高点|','|---|---|---|---|---|---|---|']
        for p in report['recommendations']:
            v=p['values']; lines.append(f'|{p["code"]} {p["name"]}|{p["category"]}|{p["rank_in_category"]}/{p["peer_count"]}|{v["score"]:.4f}|{v["return_20"]:.2%}|{v["downside_volatility"]:.2%}|{v["drawdown_60"]:.2%}|')
        if report.get('chart'): lines += ['',f'![实际净值、算子贡献、基金池收益风险和回撤图]({report["chart"]})','']
        lines += ['## 程序算子明细','', '分数 = 动量贡献 + 趋势贡献 + 风险贡献 + 回撤贡献。cs_rank 在同类基金内计算，越接近1排名越高。','']
        for p in report['recommendations']:
            lines += [f'### {p["code"]} {p["name"]}', '', f'单位净值 {p["nav"]}；历史状态 {p["purchase_status"]}；同类第 {p["rank_in_category"]}。', '', '|算子/因子|表达式|程序值|','|---|---|---|']
            for f in report['program']['features']: lines.append(f'|{LABELS.get(f["name"],f["name"])}|`{f["expression"]}`|{fmt(p["values"][f["name"]])}|')
        lines += ['', f'新增：{", ".join(report["selection_changes"]["added"]) or "无"}；移出：{", ".join(report["selection_changes"]["removed"]) or "无"}。', f'完整同类排名与排除原因见同日 CSV 和 JSON。', '']
    else:
        lines += [f'本周 {report["updates_this_week"]} 次数据更新，推荐名单平均替换比例 {report["mean_replacement_fraction"]:.2%}；观察到 {len(report["unique_recommended_codes"])} 只不同基金。','',
                  '## 程序评测反馈（截至本周，累计成熟观察）','', '|观察期|成熟样本|待成熟|平均毛收益|同类均值|超额|','|---|---|---|---|---|---|']
        for h,f in report['feedback'].items():
            pct=lambda v:'未成熟' if v is None else f'{v:.2%}'
            lines.append(f'|{h}期|{f["matured_count"]}|{f["pending_count"]}|{pct(f["mean_gross_return"])}|{pct(f["mean_category_return"])}|{pct(f["mean_excess_return"])}|')
        lines += ['', '从推荐日当日或之后首个参考交易日净值开始观察；不假设可以按已知净值成交。反馈使用净值毛收益，费用、确认时间和到账时间需在交易评测中另行计入。重复、重叠样本存在依赖。','']
    lines += ['## 大模型分析（解释与推断）','']
    analysis=report.get('model_analysis')
    lines += [analysis['analysis'] if analysis else '尚未生成模型分析；以上数值、排名、图表全部由程序计算。','']
    if analysis and analysis.get('proposals'):
        lines += ['## 未执行的 RSI 程序改进建议','']
        for p in analysis['proposals']: lines += [f'- **{p["feature"]}**：`{p["expression"]}`。{p["reason"]}（未执行、未评测）','']
    lines += ['## 数据口径与限制',''] + ['- '+s for s in report['limitations']]
    if report.get('schema','').startswith('dqr.product-'):
        from .editorial import validate_copy
        validate_copy('\n'.join(lines))
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); path.write_text('\n'.join(lines)+'\n')
    # Tiny safe renderer: escape all model content; never inject model HTML/scripts.
    body=[]; table=False
    for line in lines:
        if line.startswith('|'):
            if line.startswith('|---'): continue
            if not table: body.append('<table>'); table=True
            body.append('<tr>'+''.join('<td>'+html.escape(c.strip())+'</td>' for c in line.strip('|').split('|'))+'</tr>'); continue
        if table: body.append('</table>'); table=False
        if line.startswith('!['): body.append('<img alt="程序数据图表" src="'+html.escape(report['chart'],quote=True)+'">')
        elif line.startswith('#'):
            n=len(line)-len(line.lstrip('#')); body.append(f'<h{n}>'+html.escape(line[n:].strip())+f'</h{n}>')
        elif line: body.append('<p>'+html.escape(line)+'</p>')
    if table: body.append('</table>')
    path.with_suffix('.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>'+html.escape(title)+'</title><style>body{max-width:1120px;margin:40px auto;padding:0 24px;font:16px/1.7 system-ui;color:#183043;background:#f5f7fb}h1{font-size:30px}h2{margin-top:42px;border-top:1px solid #d4dce5;padding-top:18px}table{width:100%;border-collapse:collapse;background:white;font-size:14px}td{padding:9px;border-bottom:1px solid #e2e8ef;overflow-wrap:anywhere}tr:first-child{font-weight:600;background:#e7eef5}img{width:100%;height:auto}p{white-space:pre-wrap}</style><a href="../index.html">← 月度目录</a>'+''.join(body)+'</html>')

def build(runtime, dataset_id=None):
    base=runtime.directory/'screening'
    if dataset_id is None: dataset_id=read(base/'dataset.json')['dataset_id']
    if len(dataset_id)!=64 or any(c not in '0123456789abcdef' for c in dataset_id): raise ValueError('invalid dataset ID')
    dataset=read(base/'datasets'/f'{dataset_id}.json')
    if digest(dataset)!=dataset_id: raise ValueError('dataset hash mismatch')
    program=validate_program(read(runtime.root/'strategies/screening-current.json'))
    identity=digest({'dataset':dataset_id,'program':program,'operators':provenance_hash(),'screening_source':Path(__file__).read_text()})
    folder=base/'runs'/identity
    if (folder/'manifest.json').exists(): return read(folder/'manifest.json')
    values,prices,trace=calculate(dataset,program)
    folder.mkdir(parents=True,exist_ok=True)
    write(folder/'program.json',program); write(folder/'operator-trace.json',trace)
    reports=[]; previous=None
    for n in range(1,31):
        day=f'2026-09-{n:02}'
        report,ranked=daily_report(dataset,program,values,day,previous)
        report['chart']=charts(folder,report,ranked,prices)
        write(folder/'daily'/f'{day}.json',report); render(folder/'daily'/f'{day}.md',report)
        with (folder/'daily'/f'{day}.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=['code','name','category','nav_date','nav','purchase_status','rank_in_category','peer_count','eligible','selected']+[f['name'] for f in program['features']]+['score'])
            writer.writeheader()
            for r in ranked: writer.writerow({**{k:r[k] for k in writer.fieldnames if k in r},**r['values']})
        reports.append((report,ranked));previous=report
    weekly_dates=['2026-09-06','2026-09-13','2026-09-20','2026-09-27','2026-09-30']
    for day in weekly_dates:
        report=weekly_report(reports,prices,dataset['calendar'],day)
        write(folder/'weekly'/f'{day}.json',report);render(folder/'weekly'/f'{day}.md',report)
    evaluation={'schema':'dqr.screening-evaluation.v1','feedback':{str(h):signal_feedback(reports,prices,dataset['calendar'],'2026-09-30',h) for h in [1,5]},'optimized':False,'candidate_runs':0,'fund_count':len(dataset['funds'])}
    write(folder/'evaluation.json',evaluation)
    manifest={'schema':'dqr.screening-run.v1','replay_id':identity,'dataset_id':dataset_id,'month':dataset['month'],
              'fund_count':len(dataset['funds']),'row_count':len(dataset['rows']),'program_id':digest(program),'operator_hash':provenance_hash(),
              'report_days':[r['date'] for r,_ in reports],'weekly_dates':weekly_dates,'optimized':False,'candidate_runs':0,'folder':str(folder)}
    links=['<h1>DQR · 300只基金 · 2026年9月</h1><p>每日推荐与算子证据 / 每周程序改进建议（不执行优化）</p><h2>每日分析</h2>']
    links += [f'<li><a href="daily/{r["date"]}.html">{r["date"]} · {len(r["recommendations"])}只推荐</a> · <a href="daily/{r["date"]}.csv">完整排名 CSV</a></li>' for r,_ in reports]
    links += ['<h2>RSI周报</h2>']+[f'<li><a href="weekly/{d}.html">{d}</a></li>' for d in weekly_dates]
    (folder/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>DQR September</title><style>body{max-width:900px;margin:40px auto;font:17px/1.8 system-ui;background:#f5f7fb;color:#183043}a{color:#126c9c}</style>'+''.join(links))
    (folder/'index.md').write_text('# DQR 2026年9月基金筛选\n\n'+f'基金 {len(dataset["funds"])} 只；净值 {len(dataset["rows"])} 条；30份日报、5份周报。\n\n'+ '\n'.join(f'- [日报 {r["date"]}](daily/{r["date"]}.md)' for r,_ in reports)+'\n\n'+'\n'.join(f'- [RSI周报 {d}](weekly/{d}.md)' for d in weekly_dates)+'\n')
    write(folder/'manifest.json',manifest);write(base/'latest.json',manifest)
    return manifest
