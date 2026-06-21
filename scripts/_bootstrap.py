from __future__ import annotations

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DEPS = ROOT / ".deps"
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "data" / "cache" / "matplotlib"))
(ROOT / "data" / "cache" / "matplotlib").mkdir(parents=True, exist_ok=True)
for path in (DEPS, SRC):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))
