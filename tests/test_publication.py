import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
from dqr.publication import report_routes,report_folder
from dqr.storage import read,write
spec=importlib.util.spec_from_file_location('publisher',ROOT/'scripts/publish-product.py');publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)

class PublicationTests(unittest.TestCase):
    def test_published_history_keeps_original_report_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);old='a'*64;new='b'*64
            write(base/'published.json',{'replay_id':new,'report_runs':{'daily':{'2026-10-22':old,'2026-10-23':new},'weekly':{'2026-10-18':old}}})
            routes=report_routes(base)
            self.assertEqual(report_folder(base,routes['daily']['2026-10-22']),base/'runs'/old)
            self.assertEqual(report_folder(base,routes['daily']['2026-10-23']),base/'runs'/new)
            self.assertNotIn('2026-10-23',routes['weekly'])
            with self.assertRaises(ValueError):report_folder(base,'../outside')

    def test_incomplete_model_proof_cannot_replace_previous_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=root/'data/product';identity='a'*64;folder=base/'runs'/identity
            original={'replay_id':'b'*64,'latest_date':'2026-10-21'};write(base/'published.json',original)
            write(folder/'manifest.json',{'dataset_id':'c'*64,'report_days':['2026-10-22','2026-10-23'],'weekly_dates':[]})
            write(folder/'calculation-proof.json',{'status':'verified','dataset_id':'c'*64})
            write(folder/'model-proof.json',{'status':'verified','sessions':[{'kind':'daily','day':'2026-10-23'}]})
            with self.assertRaisesRegex(ValueError,'scope'):publisher.publish(root,identity)
            self.assertEqual(read(base/'published.json'),original)
            self.assertFalse((folder/'publication-proof.json').exists())

if __name__=='__main__':unittest.main()
