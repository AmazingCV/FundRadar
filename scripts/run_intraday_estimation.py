from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.intraday_estimation import DEFAULT_CATEGORIES, run_intraday_estimation


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FundRadar intraday fund value estimation observer")
    parser.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES), help="AKShare categories, comma separated")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    categories = [x.strip() for x in str(args.categories).split(",") if x.strip()]
    result = run_intraday_estimation(categories=categories, as_of=args.date, top_n=args.top_n)
    print(f"Intraday report directory: {result.output_dir}")
    print(f"Markdown: {result.markdown}")
    print(f"Excel: {result.excel}")
    print(f"Success: {result.success}")


if __name__ == "__main__":
    main()

