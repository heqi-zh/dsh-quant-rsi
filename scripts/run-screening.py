"""Build 300-fund September screening reports from the prepared dataset."""
from pathlib import Path
import sys
import json
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from dqr.screening import build
from dqr.service import Runtime
if __name__ == '__main__': print(json.dumps(build(Runtime(ROOT)),ensure_ascii=False))
