import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from dqr.report_view import pick_summary,render_daily
from dqr.analysis import context,save_analysis
from dqr.storage import read,write
import test_screening as fixtures
from dqr.screening import daily_report

class ReaderTests(unittest.TestCase):
    def test_relative_weakness_does_not_claim_absolute_bad_factor(self):
        pick={'values':{'momentum_contribution':.4,'trend_contribution':.24,'risk_contribution':.18,'drawdown_contribution':.14,
                        'return_20':-.023456789,'return_60':-.05,'ema_gap':-.01,'downside_volatility':.01,'drawdown_60':-.05}}
        summary=pick_summary(pick)
        self.assertEqual(summary['weak_label'],'相对弱项')
        self.assertIn('下跌 2.35%',summary['caution'])
        self.assertIn('下跌时的稳定性',summary['weakness'])

    def test_readable_save_keeps_exact_evidence_and_has_no_appendix(self):
        fixtures.ScreeningTests.setUpClass()
        data=fixtures.ScreeningTests.dataset;program=fixtures.ScreeningTests.program
        report,_=daily_report(data,program,fixtures.ScreeningTests.values,'2026-09-10')
        report['chart']='../charts/2026-09-10.png'
        with tempfile.TemporaryDirectory() as directory:
            rt=SimpleNamespace(directory=Path(directory));identity='a'*64
            folder=rt.directory/'screening/runs'/identity
            write(folder/'manifest.json',{'report_days':['2026-09-10'],'weekly_dates':[]})
            path=folder/'daily/2026-09-10.json';write(path,report)
            text='\n'.join(p['code']+'：短期走势提供一定支撑，但仍应结合下跌时的稳定性判断；这是当前规则下的相对选择，不能理解为未来必然上涨。' for p in report['recommendations'])
            with patch.dict(os.environ,{'DQR_READER_FORMAT':'fund-cards-v1'}):
                before=path.read_bytes();ctx=context(rt,identity,'daily','2026-09-10');self.assertEqual(before,path.read_bytes())
                evidence=[{'path':'/report/fund_count','value':12},{'path':'/report/date','value':'2026-09-10'},
                          {'path':'/report/recommendations/0/values/return_20','value':report['recommendations'][0]['values']['return_20']}]
                with self.assertRaisesRegex(ValueError,'decimal'):
                    save_analysis(rt,identity,'daily','2026-09-10',text.replace('短期','0.123456短期',1),evidence,[])
                save_analysis(rt,identity,'daily','2026-09-10',text,evidence,[])
            saved=read(path);self.assertEqual(saved['recommendations'],report['recommendations'])
            body=path.with_suffix('.md').read_text()
            self.assertNotIn('## 程序算子明细',body)
            self.assertNotIn('附录',body)
            self.assertNotIn('cs_rank',body)
            for line in text.splitlines(): self.assertIn(line,body)
            self.assertEqual(ctx,context(rt,identity,'daily','2026-09-10'))

    def test_zero_drawdown_tie_is_not_presented_as_a_risk_shortcoming(self):
        pick={'values':{'momentum_contribution':.4,'trend_contribution':.25,'risk_contribution':.07,'drawdown_contribution':.004,
                        'return_20':.0123,'return_60':.0269,'ema_gap':.001,'downside_volatility':.0007,'drawdown_60':0.}}
        summary=pick_summary(pick)
        self.assertIn('下跌时的稳定性',summary['weakness'])
        self.assertNotIn('高点',summary['weakness'])

if __name__=='__main__':unittest.main()
