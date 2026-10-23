"""Build theme-complete fund universe and incrementally refresh public NAV history."""
import argparse
import fcntl
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date,timedelta,datetime,timezone
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from dqr.storage import read,write,digest
from dqr.universe import discover
spec=importlib.util.spec_from_file_location('fetcher',ROOT/'scripts/prepare-screening.py');fetcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(fetcher)

def history(fund,start,end,cache,refresh=False):
    folder=cache/fund['code']/f'{start}_{end}';rows=[];page=1;total=None
    while total is None or len(rows)<total:
        path=folder/f'{page:03}.json'
        if path.exists() and not refresh:raw=read(path)
        else:
            query=urlencode({'fundCode':fund['code'],'pageIndex':page,'pageSize':20,'startDate':start,'endDate':end})
            raw=json.loads(fetcher.fetch('https://api.fund.eastmoney.com/f10/lsjz?'+query))
            if raw.get('ErrCode')!=0 or not raw.get('Data'):raise ValueError('invalid API response')
            if int(raw.get('PageIndex',0))!=page:raise ValueError('unexpected page')
            if path.exists():
                prior=read(path);write(cache/'blobs'/f'{digest(prior)}.json',prior)
            write(path,raw);time.sleep(.15)
        blob=digest(raw);write(cache/'blobs'/f'{blob}.json',raw)
        total=int(raw['TotalCount']);data=raw['Data'].get('LSJZList') or []
        if total==0:return []
        if not data or total>1000:raise ValueError('invalid page count')
        for r in data:
            if not start<=r['FSRQ']<=end:raise ValueError('date outside requested range')
            action=(r.get('FHSP') or '').strip();dividend=0.
            if action not in ('','--','暂无分红信息'):
                m=re.fullmatch(r'每([0-9.]+)?份派现金([0-9.]+)元',action)
                if not m:raise ValueError('unsupported corporate action '+action)
                dividend=float(m[2])/float(m[1] or 1)
            nav=float(r['DWJZ'])
            if not math.isfinite(nav) or nav<=0 or not math.isfinite(dividend) or dividend<0:raise ValueError('invalid NAV/dividend')
            rows.append({'code':fund['code'],'date':r['FSRQ'],'nav':nav,'dividend':dividend,'purchase_status':r.get('SGZT','unknown'),'redemption_status':r.get('SHZT','unknown'),'source_blob':blob})
        page+=1
        if page>60:raise ValueError('pagination bound')
    if len({r['date'] for r in rows})!=len(rows):raise ValueError('duplicate NAV dates')
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--end',default=(date.today()-timedelta(days=1)).isoformat());p.add_argument('--workers',type=int,default=4);p.add_argument('--refresh',action='store_true');p.add_argument('--refresh-catalog',action='store_true',help='Refresh fund directory explicitly; NAV refresh keeps the current directory');args=p.parse_args()
    date.fromisoformat(args.end)
    base=ROOT/'data/product';base.mkdir(parents=True,exist_ok=True)
    lock=(base/'prepare.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('A product data refresh is already running')
    catalogpath=ROOT/'data/screening/source/catalog.raw.js'
    catalogarchive=base/'source/catalog';catalogarchive.mkdir(parents=True,exist_ok=True)
    if catalogpath.exists():
        oldcatalog=catalogpath.read_bytes();(catalogarchive/(__import__('hashlib').sha256(oldcatalog).hexdigest()+'.js')).write_bytes(oldcatalog)
    if args.refresh_catalog or not catalogpath.exists():catalogpath.write_text(fetcher.fetch('https://fund.eastmoney.com/js/fundcode_search.js'))
    catalogbytes=catalogpath.read_bytes();(catalogarchive/(__import__('hashlib').sha256(catalogbytes).hexdigest()+'.js')).write_bytes(catalogbytes)
    s=catalogpath.read_text();catalog=json.loads(s[s.index('['):s.rindex(']')+1])
    legacy=read(ROOT/'data/screening/dataset.json');legacy=read(legacy['path'])
    universe=discover(catalog,read(ROOT/'configs/themes.json'),legacy['funds'])
    write(base/'universe.json',universe)
    existing={}
    for r in legacy['rows']:existing.setdefault(r['code'],[]).append(r)
    if (base/'dataset.json').exists():
        old=read(base/'dataset.json')
        for r in read(base/'datasets'/f'{old["dataset_id"]}.json')['rows']:
            existing.setdefault(r['code'],[]).append(r)
    def task(f):
        cached=base/'funds'/f'{f["code"]}.json'
        old=read(cached)['rows'] if cached.exists() else existing.get(f['code'],[])
        old={r['date']:r for r in old if r['date']<=args.end}
        # Recheck last 10 calendar days to catch delayed publication and corrections.
        start=max('2026-01-01',(date.fromisoformat(max(old))-timedelta(days=10)).isoformat()) if old else '2026-01-01'
        if cached.exists() and read(cached).get('requested_end')==args.end and not args.refresh:return read(cached)
        try:
            new=history(f,start,args.end,base/'source',args.refresh)
            old.update({r['date']:r for r in new})
            rows=[old[d] for d in sorted(old)]
            result={'fund':f,'rows':rows,'requested_end':args.end,'latest_nav':max(old) if old else None,'error':None,'fetched_at':datetime.now(timezone.utc).isoformat()}
            write(cached,result);return result
        except Exception as e:
            return {'fund':f,'rows':[old[d] for d in sorted(old)],'requested_end':args.end,'error':str(e),'latest_nav':max(old) if old else None}
    rows=[];checks=[]
    with ThreadPoolExecutor(max_workers=min(6,max(1,args.workers))) as ex:
        for n,result in enumerate(ex.map(task,universe['funds']),1):
            rows.extend(result['rows']);checks.append({k:v for k,v in result.items() if k not in ('rows','fund')}|{'code':result['fund']['code'],'count':len(result['rows'])})
            if n%20==0:print(json.dumps({'completed':n,'total':len(universe['funds']),'rows':len(rows),'errors':sum(bool(c.get('error')) for c in checks)}),flush=True)
    payload={'schema':'dqr.product-data.v2','funds':universe['funds'],'themes':universe['themes'],'rows':sorted(rows,key=lambda r:(r['date'],r['code'])),'audit':checks,'start':'2026-01-01','end':args.end,'source':'Eastmoney public NAV history and current directory','retrieved_at':datetime.now(timezone.utc).isoformat(),'universe_id':digest(universe),'catalog_sha256':__import__('hashlib').sha256(catalogpath.read_bytes()).hexdigest()}
    identity=digest(payload);write(base/'datasets'/f'{identity}.json',payload)
    info={'dataset_id':identity,'funds':len(universe['funds']),'rows':len(rows),'errors':sum(bool(c.get('error')) for c in checks),'end':args.end};write(base/'dataset.json',info);print(json.dumps(info),flush=True)

if __name__=='__main__':main()
