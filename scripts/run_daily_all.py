from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.daily_runner.daily_all import run_daily_all


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FundRadar daily all-in-one workflow")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="force full rerun even if guard says today is done")
    parser.add_argument("--report-only", action="store_true", help="only rebuild V4.1 daily report")
    parser.add_argument("--status", action="store_true", help="show step-level daily runner status without running")
    parser.add_argument(
        "--step",
        choices=["market_scan", "short_term_radar", "v3_full", "v3_tracker", "v4_full", "daily_report"],
        default=None,
        help="run a single guarded step",
    )
    args = parser.parse_args()
    run_daily_all(limit=args.limit, force=args.force, report_only=args.report_only, status=args.status, step=args.step)


if __name__ == "__main__":
    main()
