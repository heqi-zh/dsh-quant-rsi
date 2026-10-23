"""Build the fund product from an immutable real NAV snapshot."""
import argparse
from datetime import date,timedelta
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
from dqr.product import calculate,daily_report,program_from,LIMITS,signal_feedback
from dqr.product_view import render_daily,render_weekly
from dqr.screening import weekly_report
from dqr.publication import report_routes,report_folder
from dqr.operators import provenance_hash
from dqr.storage import read,write,digest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--start',default='2026-09-01');p.add_argument('--end',default=date.today().isoformat());p.add_argument('--preview',action='store_true');p.add_argument('--published-history',action='store_true');args=p.parse_args()
    base=ROOT/'data/product'
    if args.preview:
        universe=read(base/'universe.json');records=[read(f) for f in sorted((base/'funds').glob('*.json'))]
        codes={r['fund']['code'] for r in records}
        dataset={'funds':[f for f in universe['funds'] if f['code'] in codes],'themes':universe['themes'],'rows':[r for rec in records for r in rec['rows']],'end':args.end,'audit':[]}
        identity=digest(dataset)
    else:
        identity=read(base/'dataset.json')['dataset_id'];dataset=read(base/'datasets'/f'{identity}.json')
        if digest(dataset)!=identity:raise ValueError('dataset hash mismatch')
    program=program_from(read(ROOT/'strategies/screening-current.json'))
    source={name:(ROOT/'runtime/dqr'/name).read_text() for name in ('product.py','product_view.py','report_view.py','web/product.html')}
    routes=report_routes(base) if args.published_history else {'daily':{},'weekly':{}}
    history_ids={d:i for d,i in routes['daily'].items() if d<args.start}
    replay=digest({'history':history_ids,'dataset':identity,'program':program,'source':source,'operators':provenance_hash(),'start':args.start,'end':args.end})
    folder=base/'design-preview' if args.preview else base/'runs'/replay
    if (folder/'manifest.json').exists() and not args.preview:
        print(json.dumps({'replay_id':replay,'path':str(folder),'reused':True}));return
    days=[];day=date.fromisoformat(args.start);end=date.fromisoformat(args.end)
    while day<=end:days.append(day.isoformat());day+=timedelta(days=1)
    values,prices,trace=calculate(dataset,program)
    write(folder/'program.json',program);write(folder/'trace.json',trace);write(folder/'prices.json',prices)
    reports=[]
    for d,i in sorted(history_ids.items()):
        source=report_folder(base,i)/'daily'/f'{d}.json'
        reports.append((read(source),read(source.with_suffix('.ranked.json'))))
    previous=reports[-1][0] if reports else None
    navigation_days=sorted(set(history_ids)|set(days))
    for day in days:
        report,ranked=daily_report(dataset,program,values,day,previous)
        report['dataset_id']=identity;report['preview']=args.preview
        write(folder/'daily'/f'{day}.json',report);write(folder/'daily'/f'{day}.ranked.json',ranked)
        render_daily(folder/'daily'/f'{day}.md',report,ranked,prices,navigation_days)
        reports.append((report,ranked));previous=report
        print(json.dumps({'date':day,'funds':report['fund_count'],'scored':report['scored_count'],'picks':[p['code'] for p in report['recommendations']]}),flush=True)
    weekly_dates=[d for d in days if date.fromisoformat(d).weekday()==6 or d==days[-1]]
    calendar=sorted({r['date'] for r in dataset['rows']})
    for day in weekly_dates:
        report=weekly_report(reports,prices,calendar,day);report['feedback']={str(h):signal_feedback(reports,prices,report['nav_cutoff'],h) for h in (1,5)};report['schema']='dqr.product-weekly.v2';report['limitations']=LIMITS+['观察反馈含重叠样本，统计推断需进一步检验。'];write(folder/'weekly'/f'{day}.json',report)
        # Weekly renderer is shared; prose and layout are checked separately.
        render_weekly(folder/'weekly'/f'{day}.md',report)
    write(folder/'evaluation.json',{'feedback':{str(h):signal_feedback(reports,prices,reports[-1][0]['nav_cutoff'],h) for h in (1,5)},'optimized':False,'candidate_runs':0,'fund_count':len(dataset['funds'])})
    manifest={'schema':'dqr.product-run.v2','replay_id':replay,'dataset_id':identity,'report_days':days,'navigation_days':navigation_days,'weekly_dates':weekly_dates,'published_history':history_ids,'program_id':digest(program),'fund_count':len(dataset['funds']),'preview':args.preview,'optimized':False}
    write(folder/'manifest.json',manifest)
    (folder/'index.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=daily/'+days[-1]+'.html"><a href="daily/'+days[-1]+'.html">打开最新基金日报</a>')
    if not args.preview:write(base/'latest.json',{'replay_id':replay,'path':str(folder),'latest_date':days[-1]})
    print(json.dumps({'replay_id':replay,'path':str(folder),'preview':args.preview}),flush=True)

if __name__=='__main__':main()
