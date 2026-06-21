from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..report import write_excel, write_markdown
from ..utils import ensure_dir, project_path
from .display_utils import deduplicate_fund_display, format_fund_codes
from .signal_aggregator import DailySignals
from .trend_summary import build_morning_brief, build_structural_notes


def _sheet(df: pd.DataFrame, dedup: bool = False) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame([{"说明": "暂无数据"}])
    return deduplicate_fund_display(df) if dedup else format_fund_codes(df)


def build_daily_excel(signals: DailySignals, output_dir: str | Path) -> Path:
    out_dir = ensure_dir(output_dir)
    brief = build_morning_brief(signals)
    notes = build_structural_notes(signals)
    sheets = {
        "晨报摘要": brief,
        "主线状态": _sheet(signals.core_themes),
        "次级扩散方向": _sheet(signals.secondary_themes),
        "拥挤风险": _sheet(signals.crowding_high),
        "中拥挤主题": _sheet(signals.crowding_mid),
        "新星基金Top10": _sheet(signals.new_star_top, dedup=True),
        "短期异动Top10": _sheet(signals.short_term_top, dedup=True),
        "短期主题异动": _sheet(signals.short_term_theme),
        "V1精选观察池": _sheet(signals.selected_pool),
        "V1分散观察池": _sheet(signals.diversified_pool),
        "V3仓位建议": _sheet(signals.v3_allocation, dedup=True),
        "V3_DCA计划": _sheet(signals.v3_dca, dedup=True),
        "V3退出计划": _sheet(signals.v3_exit, dedup=True),
        "V3_tracker主题变化": _sheet(signals.tracker_theme_change),
        "V4轮动状态": _sheet(signals.rotation),
        "V2_lite参考": _sheet(signals.v2_lite),
        "未映射主题仓位": _sheet(signals.unmapped_exposure),
        "口径说明": notes,
        "数据来源": signals.sources,
    }
    return write_excel(out_dir / "daily_report.xlsx", sheets)


def build_daily_markdown(signals: DailySignals, output_dir: str | Path) -> Path:
    out_dir = ensure_dir(output_dir)
    brief = build_morning_brief(signals)
    notes = build_structural_notes(signals)
    sections = {
        "定位": "V4.1 是只读晨报整合层，不预测收益，不是荐基工具，不提供买卖建议，不重新计算评分，不接新外部数据源。",
        "晨报摘要": brief,
        "当前核心主线": _sheet(signals.core_themes),
        "次级扩散方向": _sheet(signals.secondary_themes),
        "拥挤风险": _sheet(signals.crowding_high),
        "新星基金Top10": _sheet(signals.new_star_top, dedup=True),
        "短期异动Top10": _sheet(signals.short_term_top, dedup=True),
        "V3资金配置建议": _sheet(signals.v3_allocation, dedup=True),
        "DCA计划": _sheet(signals.v3_dca, dedup=True),
        "退出/止盈提示": _sheet(signals.v3_exit, dedup=True),
        "V3_tracker主题变化": _sheet(signals.tracker_theme_change),
        "V4轮动状态": _sheet(signals.rotation),
        "口径说明": notes,
        "数据来源": signals.sources,
    }
    return write_markdown(out_dir / "daily_report.md", f"FundRadar Daily Report {signals.as_of}", sections)


def output_dir_for_date(as_of: str) -> Path:
    return project_path("reports", "daily", as_of)
