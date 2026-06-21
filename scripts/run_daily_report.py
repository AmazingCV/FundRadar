from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.v4_1.daily_report import run_daily_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FundRadar V4.1 daily read-only report")
    parser.add_argument("--date", default="today", help="Report date, e.g. today or YYYY-MM-DD")
    args = parser.parse_args()
    result = run_daily_report(as_of=args.date)
    print(f"Daily report directory: {result['output_dir']}")
    print(f"Markdown: {result['markdown']}")
    print(f"Excel: {result['excel']}")


if __name__ == "__main__":
    main()

