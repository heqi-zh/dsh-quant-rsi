"""Download a reproducible, stratified 300-fund NAV panel; resume cached pages."""
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, datetime, timezone
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from dqr.storage import read, write, digest

GROUPS = {'stock': '股票型', 'index': '指数型-股票', 'mixed': '混合型-偏股', 'bond': '债券型-长债'}

def sessions():
    holidays = [('2026-01-01','2026-01-03'), ('2026-02-15','2026-02-23'),
                ('2026-04-04','2026-04-06'), ('2026-05-01','2026-05-05'),
                ('2026-06-19','2026-06-21'), ('2026-09-25','2026-09-27')]
    day, result = date(2026,1,1), []
    while day <= date(2026,9,30):
        s = day.isoformat()
        if day.weekday() < 5 and not any(a <= s <= b for a,b in holidays): result.append(s)
        day += timedelta(days=1)
    return result

def fetch(url):
    error = None
    for attempt in range(4):
        try:
            request = Request(url, headers={'Referer':'https://fundf10.eastmoney.com/', 'User-Agent':'Mozilla/5.0 DQR/0.1'})
            with urlopen(request, timeout=25) as response: return response.read().decode('utf-8-sig')
        except Exception as exc:
            error = exc
            time.sleep(1 + attempt * 2)
    raise error

def candidates(catalog):
    groups = {g: {} for g in GROUPS}
    for code, _, name, category, *_ in catalog:
        if category not in GROUPS.values(): continue
        # Exclude exchange-only ETF shares, holding/closed products and overseas funds.
        if ('ETF' in name.upper() and '联接' not in name) or re.search('持有|定开|定期|封闭|后端|QDII|美元|港币|一年|两年|三年|六个月',name): continue
        group = next(g for g,c in GROUPS.items() if c == category)
        base = re.sub(r'[ABCDEFHIY](?:类)?$', '', name)
        item = {'code':code, 'name':name, 'category':category, 'group':group, 'share_family':base}
        old = groups[group].get(base)
        priority = lambda x: (0 if x['name'].endswith('A') else 1, x['code'])
        if old is None or priority(item) < priority(old): groups[group][base] = item
    # Deterministic hash sampling, unrelated to returns, prevents ordering by fund age/provider.
    return {g: sorted(items.values(), key=lambda x: hashlib.sha256(('DQR-2026-09-v1:'+x['code']).encode()).hexdigest()) for g,items in groups.items()}

def download(item, source):
    code = item['code']
    folder = source / code
    folder.mkdir(parents=True, exist_ok=True)
    rows, page, total = [], 1, None
    while total is None or len(rows) < total:
        path = folder / f'{page:03}.json'
        if path.exists(): raw = read(path)
        else:
            params = {'fundCode':code,'pageIndex':page,'pageSize':20,'startDate':'2026-01-01','endDate':'2026-09-30'}
            raw = json.loads(fetch('https://api.fund.eastmoney.com/f10/lsjz?' + urlencode(params)))
            if raw.get('ErrCode') != 0 or not raw.get('Data') or int(raw.get('PageIndex',0)) != page:
                raise ValueError('unexpected history response')
            write(path,raw)
            time.sleep(.12)
        data = raw['Data']['LSJZList']
        total = int(raw['TotalCount'])
        if not data or total > 1000: raise ValueError('empty or oversized NAV history')
        for r in data:
            action = (r.get('FHSP') or '').strip()
            dividend = 0.
            if action not in ('','--','暂无分红信息'):
                match = re.fullmatch(r'每([0-9.]+)?份派现金([0-9.]+)元', action)
                if not match: raise ValueError('unsupported corporate action: '+action)
                dividend = float(match[2]) / float(match[1] or 1)
            nav = float(r['DWJZ'])
            if not math.isfinite(nav) or nav <= 0 or not math.isfinite(dividend) or dividend < 0:
                raise ValueError('invalid NAV or dividend')
            rows.append({'code':code,'date':r['FSRQ'],'nav':nav,'dividend':dividend,
                         'purchase_status':r.get('SGZT','unknown'), 'redemption_status':r.get('SHZT','unknown')})
        page += 1
        if page > 30: raise ValueError('page limit')
    if len({r['date'] for r in rows}) != len(rows): raise ValueError('duplicate dates')
    return sorted(rows,key=lambda r:r['date'])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--per-group',type=int,default=75)
    parser.add_argument('--workers',type=int,default=4)
    args = parser.parse_args()
    folder = ROOT / 'data/screening'
    source = folder / 'source'
    source.mkdir(parents=True,exist_ok=True)
    catalog_path = source / 'catalog.raw.js'
    if not catalog_path.exists(): catalog_path.write_text(fetch('https://fund.eastmoney.com/js/fundcode_search.js'))
    raw = catalog_path.read_text()
    catalog = json.loads(raw[raw.index('['):raw.rindex(']')+1])
    pools = candidates(catalog)
    expected = sessions()
    september = [d for d in expected if d >= '2026-09-01']
    selected, all_rows, audit = [], [], []
    def process(item):
        try:
            rows = download(item,source)
            dates = {r['date'] for r in rows}
            warmup = [d for d in dates if d < '2026-09-01']
            missing = sorted(set(september)-dates)
            ok = len(warmup) >= 100 and '2026-08-31' in dates and not missing
            return item,rows,{'code':item['code'],'group':item['group'],'accepted':ok,'warmup_sessions':len(warmup),'september_sessions':len(set(september)&dates),'missing_september':missing,'reason':None if ok else 'warmup_or_month_coverage'}
        except Exception as exc:
            return item,[],{'code':item['code'],'group':item['group'],'accepted':False,'reason':str(exc)}
    with ThreadPoolExecutor(max_workers=max(1,min(6,args.workers))) as executor:
        for group, pool in pools.items():
            accepted = 0
            offset = 0
            while accepted < args.per_group and offset < len(pool):
                batch = pool[offset:offset+min(12,args.per_group-accepted)]
                offset += len(batch)
                for item,rows,check in executor.map(process,batch):
                    audit.append(check)
                    if check['accepted']:
                        selected.append(item); all_rows.extend(rows); accepted += 1
                    print(json.dumps({'group':group,'accepted':accepted,'code':item['code'],'check':check},ensure_ascii=False),flush=True)
                write(folder/'preparation-progress.json',{'selected':selected,'audit':audit})
            if accepted < args.per_group: raise ValueError('insufficient complete funds in '+group)
    payload = {'schema':'dqr.screening-data.v1','month':'2026-09','start':'2026-01-01','end':'2026-09-30',
               'funds':selected,'rows':sorted(all_rows,key=lambda r:(r['date'],r['code'])),
               'calendar':expected,'september_sessions':september,'audit':audit,
               'source':'Eastmoney public fund directory and historical NAV API',
               'retrieved_at':datetime.now(timezone.utc).isoformat(),
               'catalog_sha256':hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
               'sampling':'Seeded hash order by share family, 75 per category; >=100 pre-September observations and complete September reference sessions. Current directory and retrospective completeness filter: NOT a point-in-time investable universe.',
               'calendar_source':'https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml',
               'limitations':['Current directory survivorship/classification bias','Historical NAV publication timestamps unavailable; assumed next-calendar-day availability','Historical subscription status text does not establish fee/limit/platform tradability','Domestic exchange calendar is a reference, not a product-specific NAV publication calendar']}
    identity = digest(payload)
    write(folder/'datasets'/f'{identity}.json',payload)
    write(folder/'dataset.json',{'dataset_id':identity,'fund_count':len(selected),'row_count':len(all_rows),'path':str(folder/'datasets'/f'{identity}.json')})
    for name,records in [('fund-pool.csv',selected),('nav-2026-01-to-09.csv',payload['rows'])]:
        with (folder/name).open('w',newline='',encoding='utf-8-sig') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    print(json.dumps({'dataset_id':identity,'funds':len(selected),'rows':len(all_rows)},ensure_ascii=False))

if __name__ == '__main__': main()
