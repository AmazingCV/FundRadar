from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.short_term_radar import run_short_term_radar
from fund_radar.utils import load_config


parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=None)
parser.add_argument("--top-n", type=int, default=None)
parser.add_argument("--lookback", default=None)
parser.add_argument("--verify-horizon", default=None)
parser.add_argument("--as-of", default=None)
args = parser.parse_args()

run_short_term_radar(
    config=load_config(),
    limit=args.limit,
    top_n=args.top_n,
    lookback_text=args.lookback,
    verify_horizon_text=args.verify_horizon,
    as_of=args.as_of,
)
