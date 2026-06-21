from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.v3.run import run_v3_full


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FundRadar V3 capital decision layer")
    parser.add_argument("--limit", type=int, default=None, help="optional limit for displayed allocation rows")
    args = parser.parse_args()
    result = run_v3_full(limit=args.limit)
    print(f"V3 report directory: {result['output_dir']}")


if __name__ == "__main__":
    main()

