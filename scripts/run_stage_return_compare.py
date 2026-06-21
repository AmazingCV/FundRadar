from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401
from fund_radar.pipeline import load_watchlist, stage_return_compare
from fund_radar.utils import load_config


parser = argparse.ArgumentParser()
parser.add_argument("--codes", default="")
parser.add_argument("--as-of", default=None)
args = parser.parse_args()
cfg = load_config()
codes = [c.strip() for c in args.codes.replace("，", ",").split(",") if c.strip()] or load_watchlist()["基金代码"].tolist()
stage_return_compare(codes, config=cfg, as_of=args.as_of)
