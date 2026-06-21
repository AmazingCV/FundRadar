from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401
from fund_radar.backtest import run_backtest
from fund_radar.utils import load_config


parser = argparse.ArgumentParser()
parser.add_argument("--start", default=None)
parser.add_argument("--end", default=None)
parser.add_argument("--top-n", type=int, default=None)
parser.add_argument("--limit", type=int, default=None)
args = parser.parse_args()
run_backtest(config=load_config(), start=args.start, end=args.end, top_n=args.top_n, limit=args.limit)
