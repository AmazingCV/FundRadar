from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.short_term_radar import run_short_term_weight_search
from fund_radar.utils import load_config


parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=None)
parser.add_argument("--verify-horizon", default=None)
args = parser.parse_args()

run_short_term_weight_search(config=load_config(), limit=args.limit, verify_horizon_text=args.verify_horizon)
