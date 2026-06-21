from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.v2_lite_validation import run_v2_lite_validation


def main() -> None:
    parser = argparse.ArgumentParser(description="V2-lite walk-forward validation")
    parser.add_argument("--limit", type=int, default=None, help="maximum cached active-equity funds to use")
    parser.add_argument("--scan-dates", default=None, help="comma separated scan dates, e.g. 2025-06-18,2025-09-30")
    args = parser.parse_args()
    dates = [x.strip() for x in args.scan_dates.split(",") if x.strip()] if args.scan_dates else None
    result = run_v2_lite_validation(limit=args.limit, scan_dates=dates)
    print(f"V2-lite validation report: {result.excel_path}")


if __name__ == "__main__":
    main()
