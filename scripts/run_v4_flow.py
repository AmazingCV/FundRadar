from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.v4.v4_radar import run_v4_full


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run FundRadar V4 theme exposure report")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    result = run_v4_full(limit=args.limit)
    print(result["flow_report"])
