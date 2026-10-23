"""Publish only calculation-checked reports with verified model sessions."""
import argparse
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
from dqr.analysis import context
from dqr.publication import report_routes
from dqr.editorial import validate_copy,validate_fund_percentages,validate_weekly_prose
from dqr.storage import read,write,digest


def publish(root,identity,day=None,kind=None):
    if not re.fullmatch('[a-f0-9]{64}',identity):raise ValueError('invalid replay ID')
    base=root/'data/product';folder=base/'runs'/identity;manifest=read(folder/'manifest.json')
    calculation=read(folder/'calculation-proof.json')
    if calculation.get('status')!='verified' or calculation.get('dataset_id')!=manifest['dataset_id']:raise ValueError('calculation proof missing or stale')
    proofname=f'model-proof-{day or "all"}-{kind or "all"}.json' if day or kind else 'model-proof.json'
    model=read(folder/proofname)
    expected={(k,d) for k,key in [('daily','report_days'),('weekly','weekly_dates')] for d in manifest[key] if (not day or d==day) and (not kind or k==kind)}
    actual={(s['kind'],s['day']) for s in model.get('sessions',[])}
    if model.get('status')!='verified' or not expected or actual!=expected:raise ValueError('model verification scope is incomplete')
    runtime=SimpleNamespace(directory=root/'data');checked=[]
    for k,d in sorted(expected):
        path=folder/k/f'{d}.json';report=read(path);analysis=report.get('model_analysis') or {}
        if not analysis.get('verified_session') or analysis.get('context_hash')!=digest(context(runtime,identity,k,d)):raise ValueError('model context missing or stale: '+d)
        validate_copy(analysis['analysis']);body=path.with_suffix('.md').read_text();validate_copy(body)
        rendered=path.with_suffix('.html').read_text()
        if k=='daily':
            validate_fund_percentages(analysis['analysis'],report['recommendations'],report.get('categories'))
            if analysis.get('reader_format')!='fund-cards-v1' or analysis.get('editorial_version')!=2:raise ValueError('daily reader format missing')
            payload=json.loads(rendered.split('<script id="report-data" type="application/json">',1)[1].split('</script>',1)[0])
            for line in analysis['analysis'].splitlines():
                code,_,text=line.partition('：')
                if line not in body or payload['opinions'].get(code)!=text:raise ValueError('rendered daily analysis differs from verified text')
        else:
            validate_weekly_prose(analysis['analysis'],analysis.get('proposals',[]))
            if analysis['analysis'] not in body or escape(analysis['analysis']) not in rendered:raise ValueError('rendered weekly analysis differs from verified text')
        checked.append({'kind':k,'date':d,'context_hash':analysis['context_hash']})
    latest_day=day or manifest['report_days'][-1]
    if ('daily',latest_day) not in expected:raise ValueError('publishing requires a verified daily report for its landing date')
    proof={'status':'verified','replay_id':identity,'dataset_id':manifest['dataset_id'],'reports':checked,'published_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
    write(folder/'publication-proof.json',proof)
    routes=report_routes(base)
    for k,d in expected:routes[k][d]=identity
    info={'report_runs':routes,'replay_id':identity,'path':str(folder),'latest_date':latest_day,'published_at':proof['published_at']}
    write(base/'published.json',info)
    return info|{'verified_reports':len(checked)}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',required=True);p.add_argument('--date');p.add_argument('--kind',choices=['daily','weekly']);args=p.parse_args()
    result=publish(ROOT,args.replay,args.date,args.kind)
    print(json.dumps({k:v for k,v in result.items() if k!='report_runs'},ensure_ascii=False))

if __name__=='__main__':main()
