from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.v3_tracker.tracker import run_v3_tracker


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FundRadar V3 paper tracking mode")
    parser.add_argument("--date", default="today", help="record date, e.g. today or 2026-06-21")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--actual-csv", default=None, help="optional actual execution csv/xlsx")
    args = parser.parse_args()
    result = run_v3_tracker(run_date=args.date, limit=args.limit, actual_csv=args.actual_csv)
    print(f"V3 tracker output directory: {result.output_dir}")
    print(f"Daily log: {result.daily_log_path}")
    print(f"Performance summary: {result.performance_path}")
    print(f"Deviation report: {result.deviation_path}")


if __name__ == "__main__":
    main()
