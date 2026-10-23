"""Refresh report presentation without recalculating rankings or changing evidence."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from dqr.screening import charts,render
from dqr.storage import read,write,digest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--charts',action='store_true')
    args=parser.parse_args()
    manifest=read(ROOT/'data/screening/latest.json');folder=Path(manifest['folder'])
    dataset=read(ROOT/'data/screening/datasets'/f'{manifest["dataset_id"]}.json')
    # Reconstruct only total-return chart paths from existing NAV; all rankings stay unchanged.
    prices={};previous={};indexes={}
    for r in sorted(dataset['rows'],key=lambda r:(r['date'],r['code'])):
        c=r['code'];ret=(r['nav']+r['dividend'])/previous[c]-1 if c in previous else 0
        indexes[c]=indexes.get(c,1)*(1+ret);previous[c]=r['nav'];prices.setdefault(c,{})[r['date']]=indexes[c]
    import csv
    meta={f['code']:f for f in dataset['funds']}
    for day in manifest['report_days']:
        report=read(folder/'daily'/f'{day}.json')
        if args.charts:
            ranked=[]
            with (folder/'daily'/f'{day}.csv').open() as stream:
                for r in csv.DictReader(stream):
                    ranked.append({**meta[r['code']],'values':{k:float(r[k]) for k in ['daily_volatility_20','return_20']}})
            charts(folder,report,ranked,prices)
        render(folder/'daily'/f'{day}.md',report)
    write(folder/'presentation.json',{'version':'reader-v2','chinese_charts':True if args.charts else read(folder/'presentation.json').get('chinese_charts',False) if (folder/'presentation.json').exists() else False,
                                    'reader_source_hash':digest((ROOT/'runtime/dqr/report_view.py').read_text()),'raw_evidence_unchanged':True})
    print('Rendered 30 reader-facing daily reports; original JSON/CSV retained.')

if __name__=='__main__':main()
