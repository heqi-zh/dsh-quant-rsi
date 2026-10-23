"""Audit full product artifacts against saved public responses and independent arithmetic."""
from bisect import bisect_left
from collections import defaultdict,Counter
from datetime import date
import json
import math
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
from dqr.storage import read,write,digest
from dqr.editorial import validate_copy


def main():
    base=ROOT/'data/product';latest=read(base/'latest.json');folder=base/'runs'/latest['replay_id'];manifest=read(folder/'manifest.json');dataset=read(base/'datasets'/f'{manifest["dataset_id"]}.json')
    assert digest(dataset)==manifest['dataset_id']
    assert len({f['code'] for f in dataset['funds']})==len(dataset['funds'])
    assert len({f['share_family'] for f in dataset['funds']})==len(dataset['funds'])
    bycode=defaultdict(list)
    for r in dataset['rows']:
        assert dataset['start']<=r['date']<=dataset['end']
        assert math.isfinite(r['nav']) and r['nav']>0 and math.isfinite(r['dividend']) and r['dividend']>=0
        bycode[r['code']].append(r)
    series={};source_pages=0
    for code,rows in bycode.items():
        rows.sort(key=lambda r:r['date']);assert len({r['date'] for r in rows})==len(rows)
        raw={}
        paths=list((ROOT/'data/screening/source'/code).glob('*.json'))+list((base/'source'/code).glob('*/*.json'))
        for path in sorted(paths,key=lambda p:p.stat().st_mtime_ns):
            source_pages+=1
            for r in read(path)['Data']['LSJZList']:raw.setdefault(r['FSRQ'],[]).append(r)
        index=1.;previous=None;values=[];locations={}
        for n,r in enumerate(rows):
            if r.get('source_blob'):
                blob=read(base/'source/blobs'/f'{r["source_blob"]}.json');assert digest(blob)==r['source_blob']
                candidates=[x for x in blob['Data']['LSJZList'] if x['FSRQ']==r['date']]
            else:candidates=raw[r['date']]
            matches=[x for x in candidates if x.get('DWJZ') and r['nav']==float(x['DWJZ']) and r['purchase_status']==x['SGZT']]
            assert matches,(code,r['date'],'no matching raw response')
            source=matches[-1]
            action=(source.get('FHSP') or '').strip();dividend=0.
            if action not in ('','--','暂无分红信息'):
                match=re.fullmatch(r'每([0-9.]+)?份派现金([0-9.]+)元',action);assert match,action
                dividend=float(match[2])/float(match[1] or 1)
            assert r['dividend']==dividend
            if previous is not None:index*=(r['nav']+dividend)/previous
            previous=r['nav'];values.append(index);locations[r['date']]=n
        series[code]=(rows,values,locations)
    def close(a,b):assert math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-10),(a,b)
    checks=0;recommendations=0
    for day in manifest['report_days']:
        report=read(folder/'daily'/f'{day}.json');ranked=read(folder/'daily'/f'{day}.ranked.json');assert report['nav_cutoff']<day
        validate_copy((folder/'daily'/f'{day}.md').read_text())
        groups=defaultdict(list)
        for p in ranked:groups[(p['group'],p['nav_date'])].append(p)
        for peers in groups.values():
            assert all(p['peer_count']==len(peers) for p in peers)
            sources=[('momentum_contribution','smoothed_momentum',.4,1),('trend_contribution','ema_gap',.25,1),('risk_contribution','downside_volatility',.2,-1),('drawdown_contribution','drawdown_60',.15,1)]
            ranks={name:sorted(p['values'][source]*direction for p in peers) for name,source,weight,direction in sources}
            for rank,p in enumerate(sorted(peers,key=lambda p:(-p['values']['score'],p['code'])),1):
                assert p['rank_in_category']==rank
                rows,index,locations=series[p['code']];n=locations[p['nav_date']];v=p['values']
                assert n+1>=100 and p['nav_date']<day
                close(v['return_20'],index[n]/index[n-20]-1);close(v['return_60'],index[n]/index[n-60]-1);close(v['drawdown_60'],index[n]/max(index[n-59:n+1])-1)
                for name,source,weight,direction in sources:close(v[name],(1+bisect_left(ranks[name],v[source]*direction))/len(peers)*weight)
                close(v['score'],sum(v[x[0]] for x in sources));checks+=1
        chosen=[];themes=Counter();families=Counter()
        for p in sorted(ranked,key=lambda p:(-p['values']['score'],p['code'])):
            if not p['eligible'] or themes[p['primary_theme']]>=1 or families[p['theme_family']]>=2:continue
            if p['group'] in ('bond','gold','overseas_gold') and any(q['group'] in ('bond','gold','overseas_gold') for q in chosen):continue
            if len(chosen)>=5:break
            chosen.append(p);themes[p['primary_theme']]+=1;families[p['theme_family']]+=1
        assert [p['code'] for p in chosen]==[p['code'] for p in report['recommendations']]
        recommendations+=len(chosen)
        for t in report['theme_coverage']:
            assert t['discovered']==sum(t['id'] in f.get('themes',[]) for f in dataset['funds'])
            assert t['scored']==sum(t['id'] in p.get('themes',[]) for p in ranked)
            assert t['eligible']<=t['scored']<=t['warmup_ready']<=t['with_history']<=t['discovered']
        html=(folder/'daily'/f'{day}.html').read_text();assert '<svg id="chart"' in html and '<img' not in html
        payload=json.loads(html.split('<script id="report-data" type="application/json">',1)[1].split('</script>',1)[0])
        for code,points in payload['series'].items():assert all(d<day for d,v in points)
    for day in manifest['weekly_dates']:
        report=read(folder/'weekly'/f'{day}.json');assert report['candidate_runs']==0 and report['optimized'] is False
        for f in report['feedback'].values():
            for s in f['samples']:
                assert s['signal_date']<=s['start_nav_date']<s['end_nav_date']<=report['nav_cutoff']<day
                _,values,loc=series[s['code']];close(s['gross_return'],values[loc[s['end_nav_date']]]/values[loc[s['start_nav_date']]]-1)
                assert loc[s['end_nav_date']]-loc[s['start_nav_date']]==f['horizon_sessions']
                close(s['excess_return'],s['gross_return']-s['category_mean_return'])
    legacy_info=read(ROOT/'data/screening/dataset.json');legacy=read(legacy_info['path']);expected=set(legacy['september_sessions'])
    complete=[]
    for fund in dataset['funds']:
        days={r['date'] for r in bycode.get(fund['code'],[])}
        if fund.get('market')=='domestic' and expected<=days and sum(d<'2026-09-01' for d in days)>=100:complete.append(fund['code'])
    write(folder/'coverage-audit.json',{'september_reference_days':sorted(expected),'domestic_complete_with_100_warmup':complete,
                                       'themes':{t['id']:{'name':t['name'],'discovered':sum(t['id'] in f.get('themes',[]) for f in dataset['funds']),
                                                         'complete_with_warmup':sum(t['id'] in f.get('themes',[]) and f['code'] in complete for f in dataset['funds'])} for t in dataset['themes']},
                                       'overseas_note':'Separate valuation calendars; completeness against the domestic calendar is intentionally restricted to domestic funds.'})
    proof={'status':'verified','dataset_id':manifest['dataset_id'],'funds':len(dataset['funds']),'rows':len(dataset['rows']),'source_pages':source_pages,
           'factor_rows_checked':checks,'recommendations_checked':recommendations,'daily_reports':len(manifest['report_days']),'weekly_reports':len(manifest['weekly_dates']),
           'september_rows':sum('2026-09-01'<=r['date']<='2026-09-30' for r in dataset['rows']),
           'warmup_rows':sum(r['date']<'2026-09-01' for r in dataset['rows']),'candidate_runs':0,'domestic_complete_september_with_100_warmup':len(complete)}
    write(folder/'calculation-proof.json',proof);print(json.dumps(proof,ensure_ascii=False))

if __name__=='__main__':main()
