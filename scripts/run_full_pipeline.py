from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401
from fund_radar.pipeline import load_watchlist, market_scan, stage_return_compare
from fund_radar.tracking import run_tracking
from fund_radar.utils import load_config


parser = argparse.ArgumentParser()
parser.add_argument("--as-of", default=None)
parser.add_argument("--limit", type=int, default=None)
args = parser.parse_args()
cfg = load_config()
stage_return_compare(load_watchlist()["基金代码"].tolist(), config=cfg, as_of=args.as_of)
market_scan(config=cfg, as_of=args.as_of, limit=args.limit)
run_tracking(config=cfg, as_of=args.as_of, limit=args.limit)
