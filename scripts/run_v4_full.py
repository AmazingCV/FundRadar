from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.v4.v4_radar import run_v4_full
from fund_radar.utils import project_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FundRadar V4 theme exposure and crowding layer")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--date", default=None, help="output data date, e.g. 2026-06-22")
    args = parser.parse_args()
    output_dir = project_path("reports", "v4", args.date) if args.date else None
    result = run_v4_full(limit=args.limit, output_dir=output_dir)
    print(f"V4 report directory: {result['output_dir']}")


if __name__ == "__main__":
    main()

