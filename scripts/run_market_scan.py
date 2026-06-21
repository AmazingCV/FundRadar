from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401
from fund_radar.pipeline import market_scan
from fund_radar.utils import load_config


parser = argparse.ArgumentParser()
parser.add_argument("--as-of", default=None)
parser.add_argument("--limit", type=int, default=None)
parser.add_argument("--no-holdings", action="store_true")
args = parser.parse_args()
market_scan(config=load_config(), as_of=args.as_of, limit=args.limit, with_holdings=not args.no_holdings)
