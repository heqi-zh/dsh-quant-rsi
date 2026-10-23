"""Causal multi-market fund screening with explicit coverage and diversification."""
from collections import defaultdict, Counter
from copy import deepcopy
from datetime import date
import math
import statistics
import polars as pl
from .operators import evaluate_program, frame_from_bars
from .storage import digest

GROUP_NAMES = {'stock':'股票型','mixed':'混合型','index':'股票指数','bond':'长债','gold':'黄金','overseas':'海外权益','overseas_gold':'海外黄金','commodity':'境内商品','overseas_commodity':'海外商品'}
CONTRIBUTIONS = ('momentum_contribution','trend_contribution','risk_contribution','drawdown_contribution')
LIMITS = [
    '主题标签来自基金名称匹配，持仓行业占比尚待核验；同一基金可以覆盖多个主题。',
    '基金池取自当前目录，历史回放含幸存者偏差。报告使用报告日前的净值；数据源未提供逐条发布时间。',
    '推荐遵循同类评分与主题分散规则。每个主题最多1只，每个主题大类最多2只；实际持仓相关性仍需进一步核验。',
    '申购状态来自净值接口记录，交易前需核实渠道、限额、费用及最新开放状态。',
    '评分权重维持初始设定。技术指标RSI用于辅助解读；周报提供筛选程序改进建议，执行优化需另行授权。',
]


def program_from(base):
    program=deepcopy(base)
    program['name']='theme-fund-screening-v2'
    program['description']='Category-relative ranks after 100 observations, theme-diversified shortlist; fixed unoptimized factor weights.'
    program['selection']={'slots':{'all':5},'purchase_status':'开放申购','tie_break':'code_ascending',
                          'max_per_primary_theme':1,'max_per_family':2,'max_defensive':1}
    return program


def group_of(fund):
    if fund.get('market')=='overseas':
        return 'overseas_gold' if '黄金' in fund['name'] else 'overseas_commodity' if '商品' in fund['category'] else 'overseas'
    if '期货' in fund['name']:return 'commodity'
    return fund['group']


def calculate(dataset, program, before=None):
    """Evaluate rolling operators on full histories, then rank mature peers only.

    Filtering is confined to the second (cross-sectional) stage, so every
    rolling operator keeps its actual warmup and no artificial values enter it.
    """
    metadata={f['code']:f for f in dataset['funds']}
    bars=defaultdict(lambda:defaultdict(dict))
    for row in dataset['rows']:
        if before and row['date']>=before:continue
        bars[group_of(metadata[row['code']])][row['date']][row['code']]=row
    first=deepcopy(program);second=deepcopy(program)
    first['features']=[f for f in program['features'] if f['name'] not in CONTRIBUTIONS]
    first['score']='return_20'
    second['features']=[f for f in program['features'] if f['name'] in CONTRIBUTIONS]
    values=defaultdict(dict);prices=defaultdict(dict);traces={}
    for group,days in bars.items():
        frame=frame_from_bars([{'date':d,'funds':items} for d,items in sorted(days.items())])
        raw,trace1=evaluate_program(frame,first)
        features=frame.join(raw.drop('score'),on=['datetime','vt_symbol'],how='left')
        features=features.with_columns(pl.col('datetime').cum_count().over('vt_symbol').alias('observations'))
        eligible=features.filter(pl.col('observations')>=program['warmup_sessions'])
        if eligible.height:
            scored,trace2=evaluate_program(eligible,second)
            result=eligible.join(scored,on=['datetime','vt_symbol'],how='left')
            for row in result.to_dicts():
                d,code=row.pop('datetime'),row.pop('vt_symbol');values[d][code]=row
        else:trace2={}
        traces[group]={'time_series':trace1,'cross_section':trace2}
        for row in frame.to_dicts():prices[row['vt_symbol']][row['datetime']]=row['total_return_index']
    return dict(values),dict(prices),traces


def daily_report(dataset, program, values, day, previous=None):
    metadata={f['code']:{**f,'group':group_of(f)} for f in dataset['funds']}
    latest={};counts=Counter();market_dates={}
    for row in dataset['rows']:
        if row['date']>=day:continue
        code=row['code'];counts[code]+=1
        if code not in latest or latest[code]['date']<row['date']:latest[code]=row
        market=metadata[code].get('market','domestic')
        market_dates[market]=max(market_dates.get(market,''),row['date'])
    if not latest:raise ValueError('no earlier NAV')
    cutoff=max(market_dates.values());ranked=[];exclusions=[]
    for code,fund in metadata.items():
        raw=latest.get(code);market=fund.get('market','domestic')
        expected=market_dates.get(market)
        v=values.get(raw['date'],{}).get(code) if raw else None
        reason=('no_history' if not raw else 'insufficient_warmup' if counts[code]<program['warmup_sessions']
                else 'missing_latest_nav' if raw['date']!=expected else 'invalid_score' if not v or v.get('score') is None or not math.isfinite(v['score']) else None)
        if reason:exclusions.append({'code':code,'reason':reason,'nav_date':raw['date'] if raw else None});continue
        eligible=raw.get('purchase_status')==program['selection']['purchase_status']
        ranked.append({**fund,'nav_date':raw['date'],'nav':raw['nav'],'purchase_status':raw.get('purchase_status','unknown'),
                       'values':v,'eligible':eligible,'selected':False,'lag_calendar_days':(date.fromisoformat(day)-date.fromisoformat(raw['date'])).days})
        if not eligible:exclusions.append({'code':code,'reason':'subscription_not_verified_open','status':raw.get('purchase_status')})
    categories={}
    for group in sorted({f['group'] for f in metadata.values()}):
        peers=sorted([p for p in ranked if p['group']==group],key=lambda p:(-p['values']['score'],p['code']))
        for n,p in enumerate(peers,1):p.update(rank_in_category=n,peer_count=len(peers))
        categories[group]={'category':GROUP_NAMES[group],'scored':len(peers),'eligible':sum(p['eligible'] for p in peers),
                           'median_return_20':statistics.median(p['values']['return_20'] for p in peers) if peers else None}
    theme_meta={t['id']:t for t in dataset['themes']}
    theme_counts=Counter();family_counts=Counter();picks=[]
    for p in sorted(ranked,key=lambda p:(-p['values']['score'],p['code'])):
        themes=p.get('themes',[])
        # The ordered theme registry puts specific themes before broad technology.
        primary=themes[0] if themes else p['group']
        family=theme_meta[primary]['family'] if primary in theme_meta else p['group']
        p.update(primary_theme=primary,theme_family=family)
        if not p['eligible']:continue
        if theme_counts[primary]>=program['selection']['max_per_primary_theme']:continue
        if family_counts[family]>=program['selection']['max_per_family']:continue
        if p['group'] in ('bond','gold','overseas_gold') and sum(q['group'] in ('bond','gold','overseas_gold') for q in picks)>=program['selection']['max_defensive']:continue
        if len(picks)>=sum(program['selection']['slots'].values()):continue
        p['selected']=True;picks.append(p);theme_counts[primary]+=1;family_counts[family]+=1
    coverage=[]
    for t in dataset['themes']:
        members=[f for f in metadata.values() if t['id'] in f.get('themes',[])]
        peers=[p for p in ranked if t['id'] in p.get('themes',[])]
        returns=[p['values']['return_20'] for p in peers]
        coverage.append({**t,'discovered':len(members),'with_history':sum(f['code'] in latest for f in members),
                         'warmup_ready':sum(counts[f['code']]>=program['warmup_sessions'] for f in members),
                         'scored':len(peers),'eligible':sum(p['eligible'] for p in peers),
                         'positive_fraction':statistics.mean(r>0 for r in returns) if returns else None,
                         'median_return_20':statistics.median(returns) if returns else None})
    signature=digest(sorted((p['code'],p['nav_date'],p['values']['score'],p['eligible']) for p in ranked))
    codes={p['code'] for p in picks};old={p['code'] for p in previous['recommendations']} if previous else codes
    report={'schema':'dqr.product-daily.v2','date':day,'nav_cutoff':cutoff,'expected_nav_date':cutoff,'market_nav_dates':market_dates,
            'data_signature':signature,'data_updated':previous is None or signature!=previous['data_signature'],
            'fund_count':len(metadata),'scored_count':len(ranked),'eligible_count':sum(p['eligible'] for p in ranked),
            'program':program,'program_id':digest(program),'recommendations':picks,'categories':categories,'theme_coverage':coverage,
            'selection_changes':{'added':sorted(codes-old),'removed':sorted(old-codes),'replacement_fraction':len(codes-old)/len(codes) if codes else 0},
            'exclusions':exclusions,'exclusion_counts':dict(Counter(p['reason'] for p in exclusions)),
            'limitations':LIMITS,'model_analysis':None,'optimized':False}
    return report,ranked


def signal_feedback(reports, prices, cutoff, horizon):
    """Use each selected fund's actual valuation sessions, with matched peer dates."""
    samples=[];pending=0
    for report,ranked in reports:
        if not report['data_updated'] or report['date']>cutoff:continue
        for selected in report['recommendations']:
            series=prices.get(selected['code'],{})
            days=sorted(d for d in series if report['date']<=d<=cutoff)
            if len(days)<=horizon:pending+=1;continue
            start,end=days[0],days[horizon]
            peers=[]
            for p in ranked:
                if p['group']!=selected['group'] or not p['eligible']:continue
                price=prices.get(p['code'],{})
                if start in price and end in price:peers.append(price[end]/price[start]-1)
            if not peers:pending+=1;continue
            result=series[end]/series[start]-1;baseline=statistics.mean(peers)
            samples.append({'signal_date':report['date'],'code':selected['code'],'group':selected['group'],'start_nav_date':start,
                            'end_nav_date':end,'gross_return':result,'category_mean_return':baseline,'excess_return':result-baseline,'peer_count':len(peers)})
    return {'horizon_sessions':horizon,'matured_count':len(samples),'pending_count':pending,
            'mean_gross_return':statistics.mean(s['gross_return'] for s in samples) if samples else None,
            'mean_category_return':statistics.mean(s['category_mean_return'] for s in samples) if samples else None,
            'mean_excess_return':statistics.mean(s['excess_return'] for s in samples) if samples else None,
            'positive_excess_fraction':statistics.mean(s['excess_return']>0 for s in samples) if samples else None,'samples':samples,
            'interpretation':'Each fund uses actual valuation sessions; peers matched at identical start/end dates. Gross NAV observations exclude fees. Overlapping samples require dependency-aware inference.'}
