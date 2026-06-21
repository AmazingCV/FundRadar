from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401
from fund_radar.tracking import run_tracking
from fund_radar.utils import load_config


parser = argparse.ArgumentParser()
parser.add_argument("--as-of", default=None)
parser.add_argument("--limit", type=int, default=None)
args = parser.parse_args()
run_tracking(config=load_config(), as_of=args.as_of, limit=args.limit)
