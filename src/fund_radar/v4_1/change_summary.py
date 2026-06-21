from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..utils import project_path
from .display_utils import FUND_CODE_COL, FUND_NAME_COL, format_fund_codes
from .signal_aggregator import DailySignals


def _previous_daily_excel(as_of: str) -> Path | None:
    root = project_path("reports", "daily")
    if not root.exists():
        return None
    candidates = []
    for path in root.glob("20*/daily_report.xlsx"):
        date_text = path.parent.name[:10]
        if date_text < as_of:
            candidates.append(path)
    return max(candidates, key=lambda p: p.parent.name) if candidates else None


def _read_sheet(path: Path | None, sheet: str) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(path, sheet_name=sheet)
    except Exception:
        return pd.DataFrame()


def _fund_key_set(df: pd.DataFrame) -> set[str]:
    if df.empty:
        return set()
    df = format_fund_codes(df)
    if FUND_CODE_COL in df.columns:
        return set(df[FUND_CODE_COL].dropna().astype(str).str.zfill(6))
    if FUND_NAME_COL in df.columns:
        return set(df[FUND_NAME_COL].dropna().astype(str))
    return set()


def _fund_names(df: pd.DataFrame, codes: set[str], limit: int = 8) -> str:
    if not codes:
        return "无"
    df = format_fund_codes(df)
    if FUND_CODE_COL not in df.columns:
        return "、".join(sorted(codes)[:limit])
    rows = df[df[FUND_CODE_COL].astype(str).isin(codes)].copy()
    labels = []
    for _, row in rows.head(limit).iterrows():
        code = str(row.get(FUND_CODE_COL, ""))
        name = str(row.get(FUND_NAME_COL, "")) if FUND_NAME_COL in rows.columns else ""
        labels.append(f"{code} {name}".strip())
    return "、".join(labels) if labels else "、".join(sorted(codes)[:limit])


def _theme_text(df: pd.DataFrame, limit: int = 5) -> str:
    if df.empty or "主题" not in df.columns:
        return "暂无"
    return "、".join(df["主题"].dropna().astype(str).head(limit).tolist()) or "暂无"


def _max_crowding(df: pd.DataFrame) -> str:
    if df.empty:
        return "暂无"
    theme = str(df.iloc[0].get("主题", ""))
    score = df.iloc[0].get("拥挤度分", "")
    return f"{theme}({score})" if theme else "暂无"


def _weight_summary(df: pd.DataFrame, limit: int = 5) -> str:
    if df.empty:
        return "暂无"
    df = format_fund_codes(df)
    weight_col = "最终权重%" if "最终权重%" in df.columns else ("目标权重%" if "目标权重%" in df.columns else None)
    rows = []
    for _, row in df.head(limit).iterrows():
        code = str(row.get(FUND_CODE_COL, ""))
        name = str(row.get(FUND_NAME_COL, ""))
        weight = row.get(weight_col, "") if weight_col else ""
        rows.append(f"{code} {name} {weight}".strip())
    return "、".join(rows) if rows else "暂无"


def _failure_count_from_sources(sources: pd.DataFrame) -> str:
    if sources.empty or "路径" not in sources.columns:
        return "暂无数据源记录"
    total_fail = 0
    details = []
    for _, row in sources.iterrows():
        path = Path(str(row.get("路径", "")))
        if path.suffix.lower() != ".xlsx" or not path.exists():
            continue
        try:
            xf = pd.ExcelFile(path)
        except Exception:
            continue
        for sheet in xf.sheet_names:
            if "失败" not in sheet:
                continue
            df = _read_sheet(path, sheet)
            count = len(df) if not df.empty else 0
            total_fail += count
            if count:
                details.append(f"{path.name}:{sheet}={count}")
    return f"失败记录合计 {total_fail}；" + ("；".join(details) if details else "暂无失败明细")


def build_change_summary(signals: DailySignals) -> pd.DataFrame:
    previous = _previous_daily_excel(signals.as_of)
    prev_selected = _read_sheet(previous, "V1精选观察池")
    prev_short = _read_sheet(previous, "短期异动Top10")
    prev_core = _read_sheet(previous, "主线状态")
    prev_crowding = _read_sheet(previous, "拥挤风险")
    prev_v3 = _read_sheet(previous, "V3仓位建议")

    selected_now = signals.selected_pool
    selected_new = _fund_key_set(selected_now) - _fund_key_set(prev_selected)
    selected_drop = _fund_key_set(prev_selected) - _fund_key_set(selected_now)
    short_new = _fund_key_set(signals.short_term_top) - _fund_key_set(prev_short)

    rows = [
        {
            "项目": "今日新增精选基金",
            "状态": "有变化" if selected_new else "无变化",
            "变化摘要": _fund_names(selected_now, selected_new),
            "当前": str(len(_fund_key_set(selected_now))),
            "上期": str(len(_fund_key_set(prev_selected))) if previous else "无上期日报",
        },
        {
            "项目": "今日掉出精选基金",
            "状态": "有变化" if selected_drop else "无变化",
            "变化摘要": _fund_names(prev_selected, selected_drop),
            "当前": str(len(_fund_key_set(selected_now))),
            "上期": str(len(_fund_key_set(prev_selected))) if previous else "无上期日报",
        },
        {
            "项目": "主题强度变化",
            "状态": "观察",
            "变化摘要": f"当前核心主线：{_theme_text(signals.core_themes)}；上期：{_theme_text(prev_core)}",
            "当前": _theme_text(signals.core_themes),
            "上期": _theme_text(prev_core) if previous else "无上期日报",
        },
        {
            "项目": "拥挤度变化",
            "状态": "观察",
            "变化摘要": f"当前高拥挤：{_max_crowding(signals.crowding_high)}；上期：{_max_crowding(prev_crowding)}",
            "当前": _max_crowding(signals.crowding_high),
            "上期": _max_crowding(prev_crowding) if previous else "无上期日报",
        },
        {
            "项目": "V3仓位变化",
            "状态": "观察",
            "变化摘要": f"当前Top：{_weight_summary(signals.v3_allocation)}；上期Top：{_weight_summary(prev_v3)}",
            "当前": _weight_summary(signals.v3_allocation),
            "上期": _weight_summary(prev_v3) if previous else "无上期日报",
        },
        {
            "项目": "短期异动新增基金",
            "状态": "有变化" if short_new else "无变化",
            "变化摘要": _fund_names(signals.short_term_top, short_new),
            "当前": str(len(_fund_key_set(signals.short_term_top))),
            "上期": str(len(_fund_key_set(prev_short))) if previous else "无上期日报",
        },
        {
            "项目": "接口失败/数据缺失摘要",
            "状态": "检查",
            "变化摘要": _failure_count_from_sources(signals.sources),
            "当前": "见数据来源与失败记录",
            "上期": "",
        },
    ]
    return pd.DataFrame(rows)

