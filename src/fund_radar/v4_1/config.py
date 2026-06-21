from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DailyReportConfig:
    top_n: int = 10
    output_root: str = "reports/daily"
    stale_days_warning: int = 7


def default_daily_report_config() -> DailyReportConfig:
    return DailyReportConfig()

