"""Reader-facing daily reports. Full-precision evidence stays in JSON/CSV."""
from html import escape
from pathlib import Path

FACTORS = [
    ('momentum_contribution', .4, '上涨动力'),
    ('trend_contribution', .25, '近期趋势'),
    ('risk_contribution', .2, '下跌时的稳定性'),
    ('drawdown_contribution', .15, '距近期高点'),
]

def factor_fact(pick, factor):
    v = pick['values']
    if factor == 'momentum_contribution':
        return f'近20期收益 {v["return_20"]:+.2%}，近60期收益 {v["return_60"]:+.2%}'
    if factor == 'trend_contribution':
        return f'短期均线比长期均线{("高" if v["ema_gap"] >= 0 else "低")} {abs(v["ema_gap"]):.2%}'
    if factor == 'risk_contribution':
        return f'近20期下行波动 {v["downside_volatility"]:.2%}（数值越低，下跌时越稳定）'
    if abs(v['drawdown_60']) < 1e-8:
        return '当前处于近60期高点'
    return f'比近60期高点低 {abs(v["drawdown_60"]):.2%}'

def pick_summary(pick):
    """Compare unweighted rank percentiles, not unequal weighted contributions."""
    v = pick['values']
    ordered = sorted(FACTORS, key=lambda f: v[f[0]]/f[1], reverse=True)
    strong = ordered[0]
    # With many funds at their highs, min-tie ranks can be low despite zero drawdown.
    # That is a ranking convention, not evidence of a fund's downside weakness.
    weak_candidates = [f for f in ordered if not (f[0]=='drawdown_contribution' and abs(v['drawdown_60'])<1e-8)]
    weak = weak_candidates[-1]
    percentile = lambda f: v[f[0]]/f[1]
    support = f'{strong[2]}：{factor_fact(pick,strong[0])}。同类相对分 {percentile(strong)*100:.0f}/100。'
    weakness = f'{weak[2]}：{factor_fact(pick,weak[0])}。同类相对分 {percentile(weak)*100:.0f}/100。'
    # Relative quality and absolute direction are separate; never call a negative return strong growth.
    if v['return_20'] < 0:
        caution = f'近20期仍下跌 {abs(v["return_20"]):.2%}，同类排名相对靠前，转涨仍需后续净值确认。'
    elif v['return_60'] < 0:
        caution = f'近20期上涨 {v["return_20"]:.2%}，但近60期仍下跌 {abs(v["return_60"]):.2%}，更像短期修复。'
    else:
        caution = '短、较长两个收益窗口均为正，但历史涨幅不能证明后续仍会持续。'
    if 0 < pick.get('peer_count',100) < 10:
        caution = f'同类比较只有 {pick["peer_count"]} 只基金，名次和相对分的区分能力有限。' + caution
    return {'support_label':'优势' if percentile(strong)>=.65 else '相对支撑',
            'weak_label':'短板' if percentile(weak)<.5 else '相对弱项',
            'support':support,'weakness':weakness,'caution':caution}

def render_daily(path, report):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    analysis=report.get('model_analysis') or {}
    model_lines={}
    if analysis.get('reader_format')=='fund-cards-v1':
        model_lines={s.split('：',1)[0]:s for s in analysis['analysis'].splitlines() if '：' in s}
    title=f'{report["date"]} 基金日报'
    fresh='已更新净值' if report['data_updated'] else '暂无新净值，沿用上次名单'
    negatives=sum(p['values']['return_20']<0 for p in report['recommendations'])
    summary=f'本次从 {report["fund_count"]} 只基金中筛出 {len(report["recommendations"])} 只。'
    if negatives: summary+=f'其中 {negatives} 只近20期收益仍为负，名单体现同类相对优势，仍需关注下跌风险。'
    else: summary+='入选基金近20期收益均为正；仍需逐只看风险与较长周期表现。'
    md=[f'# {title}','',f'净值截至 {report["nav_cutoff"]} · {fresh}','',summary,'',
        '股票1只、指数1只、偏股混合2只、长债1只，名额用于组织观察名单，资金配比需另行制定。','']
    cards=[]
    for p in report['recommendations']:
        s=pick_summary(p);v=p['values']
        heading=f'{p["name"]}（{p["code"]}）'
        meta=f'{p["category"]} · 同类第 {p["rank_in_category"]}/{p["peer_count"]} · 近20期 {v["return_20"]:+.2%}'
        reason=f'按当前规则综合排名第 {p["rank_in_category"]}，且数据源记录为开放申购。'
        md += [f'## {heading}','',meta,'',f'**{s["support_label"]}**：{s["support"]}','',
               f'**{s["weak_label"]}**：{s["weakness"]}','',f'**还要留意**：{s["caution"]}','',
               f'**为什么入选**：{reason}','']
        opinion=model_lines.get(p['code'])
        if opinion: md += ['**模型判断**','',opinion,'']
        cards.append('<section class="fund"><header><h2>'+escape(heading)+'</h2><p class="meta">'+escape(meta)+'</p></header>'+
                     '<div class="factor good"><b>'+s['support_label']+'</b><p>'+escape(s['support'])+'</p></div>'+
                     '<div class="factor weak"><b>'+s['weak_label']+'</b><p>'+escape(s['weakness'])+'</p></div>'+
                     '<p class="caution">'+escape(s['caution'])+'</p><p><b>为什么入选：</b>'+escape(reason)+'</p>'+
                     ('<div class="opinion"><b>模型判断</b><p>'+escape(opinion)+'</p></div>' if opinion else '')+'</section>')
    chart_names=['近60期收益走势','入选分数的来源','基金池收益与波动','距近期高点的幅度']
    chart_paths=[report['chart'].replace('.png',f'-{n}.png') for n in range(1,5)]
    md += ['## 看图对照',''] + [f'![{name}]({url})\n' for name,url in zip(chart_names,chart_paths)] + ['',
           '因子的同类相对分越高，表示这一项相对越靠前；评分用于同类排序。并列会影响分数。','',
           '## 阅读口径','',
           '“期”指一条净值观察。优势、弱项和数值由程序提取；标为“模型判断”的文字是解释与推断。','',
           '这是一份历史筛选报告。基金池使用当前目录，存在幸存者偏差；交易前需核验最新申购状态，净值实际发布时间也待逐只核验。']
    if not model_lines: md += ['', '新版模型判断待生成；旧模型原文仍保存在原始 JSON 中。']
    path.write_text('\n'.join(md)+'\n',encoding='utf-8')
    css='''*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#203342;font:16px/1.75 system-ui,-apple-system,sans-serif}main{max-width:960px;margin:36px auto;padding:0 22px}h1{font-size:32px;line-height:1.3}h2{font-size:21px;line-height:1.5;margin:0}a{color:#236885}.meta{color:#647480;font-size:14px;margin:6px 0}.intro{font-size:18px}.fund{margin:24px 0;padding:26px;background:#fff;border:1px solid #e0e6eb;border-radius:12px}.factor{display:flex;gap:18px;margin-top:18px;padding:14px 16px;border-radius:8px}.factor b{flex:0 0 64px}.factor p{margin:0}.good{background:#eef6f1}.weak{background:#fcf3e9}.caution{font-weight:600}.opinion{border-left:3px solid #60899e;padding:10px 16px;background:#f4f8fb}.opinion p{margin:5px 0}.chart{display:block;width:100%;margin-top:20px}footer{font-size:14px;color:#687780;margin:30px 0} @media(max-width:600px){main{padding:0 14px;margin:22px auto}.fund{padding:18px}h1{font-size:26px}.factor{display:block}.factor b{display:block;margin-bottom:5px}}'''
    chart_html='<div class="charts">'+''.join('<a href="'+escape(url,quote=True)+'" target="_blank"><img class="chart" src="'+escape(url,quote=True)+'" alt="'+name+'"></a>' for name,url in zip(chart_names,chart_paths))+'</div>'
    css += '.charts{display:grid;grid-template-columns:1fr 1fr;gap:16px}.chart{margin-top:0}@media(max-width:700px){.charts{grid-template-columns:1fr}}'
    out='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(title)+'</title><style>'+css+'</style><main><a href="../index.html">← 月度目录</a><h1>'+title+'</h1><p class="meta">净值截至 '+report['nav_cutoff']+' · '+fresh+'</p><p class="intro">'+escape(summary)+'</p><p class="meta">股票1只 · 指数1只 · 偏股混合2只 · 长债1只。名额用于组织观察名单。</p>'+''.join(cards)+'<h2>看图对照</h2><p class="meta">点击图表可查看大图。</p>'+chart_html+'<footer>评分用于同类排序。程序提取关键因子，模型仅作解释与推断。因子相对分越高，表示同类中越靠前，后续收益需持续观察。<br>历史回放使用当前目录，存在幸存者偏差；申购状态与净值发布时间尚未完成交易级核验。</footer></main></html>'
    path.with_suffix('.html').write_text(out,encoding='utf-8')
