"""Refresh report presentation while preserving calculations and model provenance."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
from dqr.storage import read,write,digest
from dqr.product_view import render_daily,render_weekly


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay');args=p.parse_args()
    identity=args.replay or read(ROOT/'data/product/latest.json')['replay_id']
    if len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('invalid replay ID')
    folder=ROOT/'data/product/runs'/identity;manifest=read(folder/'manifest.json');prices=read(folder/'prices.json')
    originals={}
    for kind,key in [('daily','report_days'),('weekly','weekly_dates')]:
        for day in manifest[key]:
            path=folder/kind/f'{day}.json';originals[str(path)]=path.read_bytes();report=read(path)
            if kind=='daily':render_daily(path.with_suffix('.md'),report,read(path.with_suffix('.ranked.json')),prices,manifest.get('navigation_days',manifest['report_days']))
            else:render_weekly(path.with_suffix('.md'),report)
    assert all(Path(path).read_bytes()==value for path,value in originals.items()),'Reports changed concurrently; rerun presentation after model generation completes'
    sources={name:(ROOT/'runtime/dqr'/name).read_text() for name in ('product_view.py','report_view.py','web/product.html')}
    result={'daily':len(manifest['report_days']),'weekly':len(manifest['weekly_dates']),'presentation_hash':digest(sources),'raw_reports_unchanged':True,'palette':'purple'}
    write(folder/'presentation.json',result);print(result)

if __name__=='__main__':main()
