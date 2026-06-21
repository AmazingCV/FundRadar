from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.health_check import run_health_check


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FundRadar local data health check")
    parser.add_argument("--date", default=None, help="Report date, default today")
    args = parser.parse_args()
    result = run_health_check(as_of=args.date)
    print(f"Health report directory: {result.output_dir}")
    print(f"Markdown: {result.markdown}")
    print(f"Excel: {result.excel}")


if __name__ == "__main__":
    main()

