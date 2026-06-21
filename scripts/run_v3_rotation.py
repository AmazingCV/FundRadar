from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

from fund_radar.v3.run import run_v3_full


if __name__ == "__main__":
    result = run_v3_full()
    print(result["rotation_path"])
