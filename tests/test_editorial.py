import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from dqr.editorial import validate_fund_percentages

class QuotedDataTests(unittest.TestCase):
    def setUp(self):
        self.picks=[{'code':'001001','group':'stock','values':{'return_20':-.012345,'downside_volatility':.004321}}]

    def test_rounded_losses_and_volatility_are_supported(self):
        validate_fund_percentages('001001：近20期下跌1.23%，下行波动0.43%。',self.picks)
        validate_fund_percentages('001001：近20期收益-1.23%。',self.picks)

    def test_unknown_percentages_and_explicit_wrong_sign_are_rejected(self):
        for text in ['001001：近20期收益+1.23%。','001001：下行波动2.31%。']:
            with self.assertRaises(ValueError):validate_fund_percentages(text,self.picks)

    def test_same_category_median_must_be_grounded_and_identified(self):
        categories={'stock':{'median_return_20':-.07691}}
        validate_fund_percentages('001001：同类中位数下跌7.69%。',self.picks,categories)
        with self.assertRaises(ValueError):validate_fund_percentages('001001：下跌7.69%。',self.picks,categories)

if __name__=='__main__':unittest.main()

class WeeklyProseTests(unittest.TestCase):
    def test_formula_constants_are_preserved_in_proposal_fields(self):
        from dqr.editorial import validate_weekly_prose
        proposals=[{'expression':'return_20 / greater(volatility, 0.001)','reason':'下行风险需要另行检验。'}]
        validate_weekly_prose('本周平均超额1.10%，建议检验风险约束。',proposals)
        for text in ['平均超额0.011031。','return_20提供主要支撑。']:
            with self.assertRaises(ValueError):validate_weekly_prose(text,proposals)
