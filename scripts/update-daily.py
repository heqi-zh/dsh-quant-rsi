"""Refresh real NAV data and publish one verified daily fund report.

Run once after NAV publication, or invoke this command from an external scheduler.
No schedule is installed by this command. A failed refresh never replaces the
last successful model-verified publication pointer.
"""
import argparse
from datetime import datetime,timedelta
import fcntl
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
from dqr.storage import read,write


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--date',default=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat());p.add_argument('--workers',type=int,default=4);p.add_argument('--skip-model',action='store_true',help='Publish calculation artifacts only; model-verified pointer stays unchanged');args=p.parse_args()
    day=datetime.fromisoformat(args.date).date();base=ROOT/'data/product';base.mkdir(parents=True,exist_ok=True)
    lock=(base/'update.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('A daily update is already running')
    status={'date':args.date,'started_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'status':'running','stage':'data'}
    write(base/'update-status.json',status)
    log=base/'update-logs'/f'{args.date}-{datetime.now().strftime("%H%M%S")}.log';log.parent.mkdir(parents=True,exist_ok=True)
    def run(command,stage):
        status['stage']=stage;write(base/'update-status.json',status)
        with log.open('a') as stream:subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
    try:
        run([sys.executable,'scripts/prepare-product.py','--end',(day-timedelta(days=1)).isoformat(),'--workers',str(args.workers),'--refresh'],'data')
        run([sys.executable,'scripts/build-product.py','--start',args.date,'--end',args.date,'--published-history'],'calculation')
        latest=read(base/'latest.json');status['replay_id']=latest['replay_id']
        run([sys.executable,'scripts/verify-product.py'],'calculation-verification')
        if not args.skip_model:
            scope=['--date',args.date]+([] if day.weekday()==6 else ['--kind','daily'])
            run([sys.executable,'scripts/analyze-month.py','--replay',latest['replay_id'],'--reader-daily','--workers','2',*scope],'model')
            import importlib.util
            spec=importlib.util.spec_from_file_location('launcher',ROOT/'scripts/run-research.py');launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
            node=launcher.node_path()
            run([node,'scripts/verify-month.mjs',latest['replay_id'],*scope],'verification')
            run([sys.executable,'scripts/render-product.py','--replay',latest['replay_id']],'presentation')
            run([sys.executable,'scripts/publish-product.py','--replay',latest['replay_id'],*scope],'publication')
        status.update(status='calculated' if args.skip_model else 'published',finished_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),log=str(log))
    except Exception as exc:
        status.update(status='failed',error=str(exc),log=str(log));write(base/'update-status.json',status);raise
    write(base/'update-status.json',status)
    print(status)

if __name__=='__main__':main()
