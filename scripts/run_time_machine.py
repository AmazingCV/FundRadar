from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401
from fund_radar.__main__ import parse_horizons
from fund_radar.time_machine import run_time_machine
from fund_radar.utils import load_config


parser = argparse.ArgumentParser()
parser.add_argument("--as-of", required=True)
parser.add_argument("--horizon", default=None)
parser.add_argument("--top-n", type=int, default=None)
parser.add_argument("--limit", type=int, default=None)
args = parser.parse_args()
cfg = load_config()
run_time_machine(args.as_of, config=cfg, horizons=parse_horizons(args.horizon, cfg.get("time_machine", {}).get("horizons", {})), top_n=args.top_n, limit=args.limit)
