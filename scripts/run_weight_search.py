from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401
from fund_radar.utils import load_config
from fund_radar.weight_search import run_weight_search


parser = argparse.ArgumentParser()
parser.add_argument("--train-start", default="2023-01-01")
parser.add_argument("--train-end", default="2025-06-18")
parser.add_argument("--valid-start", default="2025-06-18")
parser.add_argument("--valid-end", default=None)
parser.add_argument("--limit", type=int, default=None)
args = parser.parse_args()
run_weight_search(load_config(), args.train_start, args.train_end, args.valid_start, args.valid_end, limit=args.limit)
