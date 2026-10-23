"""Independent dataset, ranking, factor and historical feedback audit."""
from collections import Counter,defaultdict
import csv
import json
import math
from pathlib import Path
import statistics
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from dqr.storage import read,write,digest

def main():
    latest=read(ROOT/'data/screening/latest.json')
    folder=Path(latest['folder'])
    dataset=read(ROOT/'data/screening/datasets'/f'{latest["dataset_id"]}.json')
    assert digest(dataset)==latest['dataset_id']
    assert len(dataset['funds'])==300
    assert set(Counter(f['group'] for f in dataset['funds']).values())=={75}
    bycode=defaultdict(list)
    for r in dataset['rows']:
        assert math.isfinite(r['nav']) and r['nav']>0 and math.isfinite(r['dividend']) and r['dividend']>=0
        assert dataset['start']<=r['date']<=dataset['end']
        bycode[r['code']].append(r)
    assert len(bycode)==300
    series={}
    source_pages=0
    for code,rows in bycode.items():
        rows.sort(key=lambda r:r['date'])
        days={r['date'] for r in rows}
        assert len(days)==len(rows)
        assert set(dataset['september_sessions'])<=days
        assert len([d for d in days if d<'2026-09-01'])>=100
        raw={}
        for p in sorted((ROOT/'data/screening/source'/code).glob('*.json')):
            source_pages+=1
            for r in read(p)['Data']['LSJZList']: raw[r['FSRQ']]=r
        values=[];returns=[];index=1.;previous=None
        for r in rows:
            assert r['nav']==float(raw[r['date']]['DWJZ'])
            assert r['purchase_status']==raw[r['date']]['SGZT']
            ret=(r['nav']+r['dividend'])/previous-1 if previous is not None else 0
            index*=1+ret;previous=r['nav'];values.append(index);returns.append(ret)
        series[code]=(rows,values,returns)
    checked=0
    def close(a,b): assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-10),(a,b)
    for day in latest['report_days']:
        report=read(folder/'daily'/f'{day}.json')
        assert report['nav_cutoff']<day
        assert len(report['recommendations'])==5
        assert (folder/'charts'/f'{day}.png').stat().st_size>10000
        with (folder/'daily'/f'{day}.csv').open() as f: ranked=list(csv.DictReader(f))
        assert len(ranked)==300
        groups=defaultdict(list)
        for r in ranked: groups[r['category']].append(r)
        for peers in groups.values():
            assert len(peers)==75
            ordered=sorted(peers,key=lambda r:(-float(r['score']),r['code']))
            for rank,r in enumerate(ordered,1):
                assert int(r['rank_in_category'])==rank
                rows,index,returns=series[r['code']]
                n=next(i for i,x in enumerate(rows) if x['date']==report['nav_cutoff'])
                close(float(r['return_20']),index[n]/index[n-20]-1)
                close(float(r['return_60']),index[n]/index[n-60]-1)
                close(float(r['drawdown_60']),index[n]/max(index[n-59:n+1])-1)
                for feature,source,weight,direction in [('momentum_contribution','smoothed_momentum',.4,1),('trend_contribution','ema_gap',.25,1),('risk_contribution','downside_volatility',.2,-1),('drawdown_contribution','drawdown_60',.15,1)]:
                    v=float(r[source])*direction
                    rank_min=1+sum(float(p[source])*direction<v for p in peers)
                    close(float(r[feature]),rank_min/len(peers)*weight)
                close(float(r['score']),sum(float(r[f]) for f in ['momentum_contribution','trend_contribution','risk_contribution','drawdown_contribution']))
                checked+=1
            picks=[r['code'] for r in ordered if r['purchase_status']=='开放申购']
            actual=[r['code'] for r in report['recommendations'] if r['category']==ordered[0]['category']]
            assert actual==picks[:len(actual)]
    for day in latest['weekly_dates']:
        report=read(folder/'weekly'/f'{day}.json')
        assert report['candidate_runs']==0 and report['optimized'] is False
        for f in report['feedback'].values():
            for s in f['samples']:
                assert s['signal_date']<=s['start_nav_date']<s['end_nav_date']<=report['nav_cutoff']<day
                rows,index,_=series[s['code']];bydate={r['date']:index[i] for i,r in enumerate(rows)}
                close(s['gross_return'],bydate[s['end_nav_date']]/bydate[s['start_nav_date']]-1)
                close(s['excess_return'],s['gross_return']-s['category_mean_return'])
    proof={'status':'verified','funds':300,'rows':len(dataset['rows']),'september_rows':sum(r['date']>='2026-09-01' for r in dataset['rows']),
           'warmup_rows':sum(r['date']<'2026-09-01' for r in dataset['rows']),'source_pages':source_pages,'factor_rows_checked':checked,
           'daily_reports':30,'weekly_reports':5,'candidate_runs':0,'program_id':digest(read(ROOT/'strategies/screening-current.json'))}
    assert proof['program_id']==latest['program_id']
    write(folder/'calculation-proof.json',proof)
    print(json.dumps(proof,ensure_ascii=False))

if __name__=='__main__':main()
