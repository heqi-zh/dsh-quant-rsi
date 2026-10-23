import copy
from datetime import date,timedelta
from pathlib import Path
import unittest
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))

from dqr.screening import calculate,daily_report,weekly_report,signal_feedback,GROUPS
from dqr.storage import read

class ScreeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program=read(ROOT/'strategies/screening-current.json')
        funds=[{'code':f'{g}{i:05}', 'name':f'{g}-{i}', 'category':category,'group':group}
               for g,(group,category) in enumerate(GROUPS.items(),1) for i in range(3)]
        days=[];d=date(2026,1,1)
        while d<=date(2026,9,30):
            if d.weekday()<5: days.append(d.isoformat())
            d+=timedelta(days=1)
        rows=[{'code':f['code'],'date':d,'nav':1+(n*.0002*(i+1))+((n%7)-3)*.0003,
               'dividend':0,'purchase_status':'开放申购'} for i,f in enumerate(funds) for n,d in enumerate(days)]
        cls.dataset={'funds':funds,'rows':rows,'calendar':days}
        cls.values,cls.prices,_=calculate(cls.dataset,cls.program)

    def test_five_picks_from_all_categories_and_score_sum(self):
        report,ranked=daily_report(self.dataset,self.program,self.values,'2026-09-10')
        self.assertEqual(len(report['recommendations']),5)
        self.assertEqual(len(ranked),12)
        for pick in report['recommendations']:
            self.assertEqual(pick['peer_count'],3)
            self.assertAlmostEqual(pick['values']['score'],sum(v for k,v in pick['values'].items() if k.endswith('_contribution')))

    def test_future_perturbation_does_not_change_earlier_report(self):
        changed=copy.deepcopy(self.dataset)
        for r in changed['rows']:
            if r['date']>='2026-09-10': r['nav']*=3
        values,_,_=calculate(changed,self.program)
        a,_=daily_report(self.dataset,self.program,self.values,'2026-09-10')
        b,_=daily_report(changed,self.program,values,'2026-09-10')
        self.assertEqual(a,b)
        prefix,_,_=calculate(self.dataset,self.program,before='2026-09-10')
        c,_=daily_report(self.dataset,self.program,prefix,'2026-09-10')
        self.assertEqual(a,c)

    def test_missing_nav_does_not_drop_other_funds_or_forward_fill(self):
        values=copy.deepcopy(self.values)
        del values['2026-09-09']['100000']
        report,ranked=daily_report(self.dataset,self.program,values,'2026-09-10')
        self.assertEqual(len(ranked),11)
        self.assertIn({'code':'100000','reason':'missing_latest_nav'},report['exclusions'])

    def test_suspended_fund_is_not_recommended(self):
        dataset=copy.deepcopy(self.dataset)
        for r in dataset['rows']:
            if r['code'].startswith('1'): r['purchase_status']='暂停申购'
        report,_=daily_report(dataset,self.program,self.values,'2026-09-10')
        self.assertEqual(len(report['recommendations']),4)
        self.assertFalse(any(p['group']=='stock' for p in report['recommendations']))

    def test_weekend_reuses_list_without_new_signal(self):
        sat,_=daily_report(self.dataset,self.program,self.values,'2026-09-12')
        sun,_=daily_report(self.dataset,self.program,self.values,'2026-09-13',sat)
        self.assertFalse(sun['data_updated'])
        self.assertEqual(sat['recommendations'],sun['recommendations'])

    def test_feedback_uses_next_valuation_and_only_matured_outcomes(self):
        reports=[]; previous=None
        for n in range(1,14):
            r,p=daily_report(self.dataset,self.program,self.values,f'2026-09-{n:02}',previous)
            reports.append((r,p));previous=r
        weekly=weekly_report(reports,self.prices,self.dataset['calendar'],'2026-09-13')
        self.assertEqual(weekly['candidate_runs'],0)
        for result in weekly['feedback'].values():
            for s in result['samples']:
                self.assertGreater(s['end_nav_date'],s['start_nav_date'])
                self.assertGreaterEqual(s['start_nav_date'],s['signal_date'])
                self.assertLessEqual(s['end_nav_date'],weekly['nav_cutoff'])
                price=self.prices[s['code']]
                self.assertAlmostEqual(s['gross_return'],price[s['end_nav_date']]/price[s['start_nav_date']]-1)
        changed=copy.deepcopy(self.prices)
        for p in changed.values():
            for day in p:
                if day>weekly['nav_cutoff']: p[day]*=4
        self.assertEqual(weekly,weekly_report(reports,changed,self.dataset['calendar'],'2026-09-13'))

if __name__=='__main__': unittest.main()
