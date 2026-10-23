import copy
from collections import Counter
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from dqr.product import calculate,daily_report,program_from
from dqr.storage import read
from dqr.editorial import validate_copy
import test_screening as fixtures

class ProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ScreeningTests.setUpClass()
        cls.dataset=copy.deepcopy(fixtures.ScreeningTests.dataset)
        cls.dataset['themes']=[{'id':'t'+str(i),'name':'主题'+str(i),'family':'大类'+str(i//2),'pattern':''} for i in range(8)]
        for i,f in enumerate(cls.dataset['funds']):
            f['market']='domestic';f['themes']=['t'+str(i%8)]
        cls.program=program_from(read(ROOT/'strategies/screening-current.json'))
        cls.values,cls.prices,_=calculate(cls.dataset,cls.program)

    def test_mature_peers_only_and_exact_contributions(self):
        self.assertFalse(any(self.values.get(d) for d in self.dataset['calendar'][:99]))
        report,ranked=daily_report(self.dataset,self.program,self.values,'2026-09-10')
        self.assertEqual(len(ranked),12)
        self.assertEqual(len(report['recommendations']),5)
        for p in ranked:
            self.assertGreaterEqual(p['values']['observations'],100)
            self.assertAlmostEqual(p['values']['score'],sum(v for k,v in p['values'].items() if k.endswith('_contribution')))
        self.assertLessEqual(max(Counter(p['primary_theme'] for p in report['recommendations']).values()),1)
        self.assertLessEqual(max(Counter(p['theme_family'] for p in report['recommendations']).values()),2)

    def test_short_history_does_not_change_peer_ranks(self):
        changed=copy.deepcopy(self.dataset)
        new={**changed['funds'][0],'code':'new'};changed['funds'].append(new)
        # Copy an actual peer's tail; this fund lacks the required 100 observations.
        changed['rows']=[r for r in changed['rows'] if r['code']!='new']+[{**r,'code':'new'} for r in self.dataset['rows'] if r['code']==self.dataset['funds'][0]['code'] and r['date']>='2026-08-01']
        values,_,_=calculate(changed,self.program)
        for code,v in self.values['2026-09-09'].items():self.assertEqual(v,values['2026-09-09'][code])

    def test_future_changes_and_prefix_leave_report_unchanged(self):
        expected,_=daily_report(self.dataset,self.program,self.values,'2026-09-10')
        changed=copy.deepcopy(self.dataset)
        for r in changed['rows']:
            if r['date']>='2026-09-10':r['nav']*=3
        values,_,_=calculate(changed,self.program)
        actual,_=daily_report(changed,self.program,values,'2026-09-10')
        self.assertEqual(expected,actual)
        prefix,_,_=calculate(self.dataset,self.program,before='2026-09-10')
        self.assertEqual(expected,daily_report(self.dataset,self.program,prefix,'2026-09-10')[0])

    def test_missing_data_and_closed_subscription_are_explicit(self):
        changed=copy.deepcopy(self.dataset)
        missing=changed['funds'][0]['code'];closed=changed['funds'][1]['code']
        changed['rows']=[r for r in changed['rows'] if not(r['code']==missing and r['date']=='2026-09-09')]
        for r in changed['rows']:
            if r['code']==closed:r['purchase_status']='暂停申购'
        values,_,_=calculate(changed,self.program)
        report,_=daily_report(changed,self.program,values,'2026-09-10')
        self.assertEqual(report['exclusion_counts']['missing_latest_nav'],1)
        self.assertFalse({missing,closed}&{p['code'] for p in report['recommendations']})
        self.assertEqual(sum(t['discovered'] for t in report['theme_coverage']),12)
        validate_copy('。'.join(report['limitations']))

    def test_editorial_rule(self):
        for text in ['这是评分，不是收益','并非推荐买入','不代表未来表现']:
            with self.assertRaises(ValueError):validate_copy(text)
        validate_copy('评分用于同类排序，后续收益需持续观察。')

if __name__=='__main__':unittest.main()

class SourceBoundaryTests(unittest.TestCase):
    def test_share_classes_and_commodity_market(self):
        from dqr.universe import discover,share_family
        self.assertEqual(share_family('国联中证煤炭指数(LOF)A'),share_family('国联中证煤炭指数C'))
        self.assertEqual(share_family('广发石油指数人民币A'),share_family('广发石油指数C人民币'))
        from dqr.product import group_of
        definitions={'tag_basis':'name','themes':[{'id':'technology','name':'科技','family':'科技','pattern':'科技'},{'id':'oil','name':'石油','family':'能源','pattern':'原油'}]}
        rows=[['01','','纳斯达克科技(QDII)A人民币','指数型-海外股票'],['02','','纳斯达克科技(QDII)C人民币','指数型-海外股票'],['03','','纳斯达克科技(QDII)A美元','指数型-海外股票'],['04','','原油A类人民币','QDII-商品'],['05','','原油C类人民币','QDII-商品']]
        result=discover(rows,definitions)
        self.assertEqual([f['code'] for f in result['funds']],['01','04'])
        self.assertEqual(result['funds'][0]['alternative_shares'],['02'])
        self.assertEqual(group_of(result['funds'][1]),'overseas_commodity')
        self.assertTrue(all(f['market']=='overseas' for f in result['funds']))

    def test_late_fractional_dividend_keeps_float_schema(self):
        from dqr.operators import frame_from_bars
        from datetime import date,timedelta
        bars=[{'date':(date(2026,1,1)+timedelta(days=i)).isoformat(),'funds':{'x':{'nav':1.,'dividend':0 if i<120 else .006196}}} for i in range(121)]
        frame=frame_from_bars(bars)
        self.assertAlmostEqual(frame[-1,'return_1'],.006196)
        self.assertAlmostEqual(frame[-1,'total_return_index'],1.006196)
