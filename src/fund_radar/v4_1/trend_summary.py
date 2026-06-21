from __future__ import annotations

import pandas as pd

from .display_utils import FUND_CODE_COL, FUND_NAME_COL, deduplicate_fund_display
from .signal_aggregator import DailySignals


def _first_value(df: pd.DataFrame, columns: list[str], default: str = "暂无") -> str:
    if df.empty:
        return default
    for col in columns:
        if col in df.columns:
            values = df[col].dropna().astype(str)
            if not values.empty:
                return values.iloc[0]
    return default


def _theme_list(df: pd.DataFrame, n: int = 5) -> str:
    if df.empty or "主题" not in df.columns:
        return "暂无"
    values = [str(x) for x in df["主题"].dropna().head(n).tolist()]
    return "、".join(values) if values else "暂无"


def _fund_list(df: pd.DataFrame, n: int = 5) -> str:
    if df.empty:
        return "暂无"
    display = deduplicate_fund_display(df)
    name_col = FUND_NAME_COL if FUND_NAME_COL in display.columns else None
    code_col = FUND_CODE_COL if FUND_CODE_COL in display.columns else None
    rows = []
    for _, row in display.head(n).iterrows():
        name = str(row.get(name_col, "")) if name_col else ""
        code = str(row.get(code_col, "")) if code_col else ""
        label = f"{code} {name}".strip()
        if label:
            rows.append(label)
    return "、".join(rows) if rows else "暂无"


def build_morning_brief(signals: DailySignals) -> pd.DataFrame:
    rotation_note = _first_value(signals.rotation, ["说明", "迁移证据", "口径说明"], "暂无明确轮动路径")
    tracker_note = _first_value(signals.tracker_theme_change, ["趋势判断", "说明"], "暂无 V3_tracker 趋势")
    rows = [
        {"项目": "报告日期", "摘要": signals.as_of},
        {"项目": "当前核心主线", "摘要": _theme_list(signals.core_themes)},
        {"项目": "次级扩散方向", "摘要": _theme_list(signals.secondary_themes)},
        {"项目": "高拥挤风险", "摘要": _theme_list(signals.crowding_high)},
        {"项目": "中拥挤方向", "摘要": _theme_list(signals.crowding_mid)},
        {"项目": "新星基金Top样本", "摘要": _fund_list(signals.new_star_top)},
        {"项目": "短期异动Top样本", "摘要": _fund_list(signals.short_term_top)},
        {"项目": "V3当前配置Top样本", "摘要": _fund_list(signals.v3_allocation)},
        {"项目": "V3_tracker趋势", "摘要": tracker_note},
        {"项目": "主线迁移", "摘要": rotation_note},
        {"项目": "系统定位", "摘要": "只读信息整合；不预测收益；不是荐基工具；不提供买卖建议"},
    ]
    return pd.DataFrame(rows)


def build_structural_notes(signals: DailySignals) -> pd.DataFrame:
    notes = []
    if not signals.unmapped_exposure.empty and "V3主题权重%" in signals.unmapped_exposure.columns:
        weight = pd.to_numeric(signals.unmapped_exposure["V3主题权重%"], errors="coerce").fillna(0).sum()
        notes.append({"事项": "未映射主题仓位", "说明": f"当前约 {weight:.2f}% V3 仓位未映射到明确主题，不参与主线和轮动判断"})
    if signals.rotation.empty:
        notes.append({"事项": "轮动证据", "说明": "暂无明确轮动路径"})
    elif "说明" in signals.rotation.columns:
        notes.append({"事项": "轮动证据", "说明": str(signals.rotation["说明"].dropna().iloc[0]) if not signals.rotation["说明"].dropna().empty else "暂无明确轮动路径"})
    else:
        notes.append({"事项": "轮动证据", "说明": "存在 V4 输出的主题暴露迁移路径，需人工复核"})
    notes.append({"事项": "日报展示去重", "说明": "日报展示层已对 A/C 等不同份额做合并展示，底层原始报告仍保留全部份额。"})
    notes.append({"事项": "数据口径", "说明": "全部来自已有 V1/V1.1/V2-lite/V3/V3_tracker/V4 报告；不重新计算评分；不接新数据源"})
    return pd.DataFrame(notes)
