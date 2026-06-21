from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import DailyReportConfig, default_daily_report_config
from .report_builder import build_daily_excel, build_daily_markdown, output_dir_for_date
from .signal_aggregator import aggregate_daily_signals, normalize_report_date


def run_daily_report(
    as_of: str | None = None,
    output_dir: str | Path | None = None,
    config: DailyReportConfig | None = None,
) -> dict[str, Path | pd.DataFrame]:
    cfg = config or default_daily_report_config()
    date_text = normalize_report_date(as_of)
    signals = aggregate_daily_signals(date_text, top_n=cfg.top_n)
    out_dir = Path(output_dir) if output_dir else output_dir_for_date(date_text)
    excel_path = build_daily_excel(signals, out_dir)
    markdown_path = build_daily_markdown(signals, out_dir)
    return {
        "output_dir": out_dir,
        "excel": excel_path,
        "markdown": markdown_path,
        "sources": signals.sources,
    }

