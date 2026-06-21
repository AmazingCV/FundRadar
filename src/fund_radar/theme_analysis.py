from __future__ import annotations

from typing import Any

import pandas as pd

from .utils import load_yaml


def load_theme_keywords(path: str = "config/theme_keywords.yaml") -> dict[str, list[str]]:
    data = load_yaml(path)
    themes = data.get("themes", {})
    return {theme: list(body.get("keywords", [])) for theme, body in themes.items()}


def tag_stock_theme(stock_name: str, themes: dict[str, list[str]]) -> list[str]:
    s = str(stock_name)
    matched = []
    for theme, keywords in themes.items():
        if any(k and k in s for k in keywords):
            matched.append(theme)
    return matched


def analyze_themes(holdings: pd.DataFrame, selected_fund_count: int, themes: dict[str, list[str]] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    themes = themes or load_theme_keywords()
    if holdings.empty:
        return (
            pd.DataFrame(columns=["股票名称", "基金代码", "持仓占比%", "主题"]),
            pd.DataFrame(columns=["主题", "出现次数", "涉及基金数量", "合计持仓占比%", "主题覆盖率%", "主线判断", "主线状态"]),
        )
    rows = []
    df = holdings.copy()
    df["持仓占比%"] = pd.to_numeric(df["持仓占比%"], errors="coerce").fillna(0)
    for _, r in df.iterrows():
        matched = tag_stock_theme(r.get("股票名称", ""), themes)
        for theme in matched or ["未归类"]:
            rows.append({**r.to_dict(), "主题": theme})
    tagged = pd.DataFrame(rows)
    theme_rows = []
    valid = tagged[tagged["主题"] != "未归类"] if not tagged.empty else tagged
    for theme, g in valid.groupby("主题"):
        fund_n = g["基金代码"].nunique()
        total_weight = float(g["持仓占比%"].sum())
        coverage = fund_n / selected_fund_count * 100 if selected_fund_count else 0
        judgement = judge_theme_strength(coverage, total_weight)
        status = judge_theme_status(judgement, coverage, total_weight)
        theme_rows.append(
            {
                "主题": theme,
                "出现次数": len(g),
                "涉及基金数量": fund_n,
                "合计持仓占比%": total_weight,
                "主题覆盖率%": coverage,
                "主线判断": judgement,
                "主线状态": status,
            }
        )
    stats = pd.DataFrame(theme_rows).sort_values(["主线判断", "合计持仓占比%"], ascending=[True, False]) if theme_rows else pd.DataFrame()
    if not stats.empty:
        order = {"核心主线": 0, "强主线": 1, "次强方向": 2, "分散/弱方向": 3}
        stats["_order"] = stats["主线判断"].map(order).fillna(9)
        stats = stats.sort_values(["_order", "合计持仓占比%"], ascending=[True, False]).drop(columns="_order").reset_index(drop=True)
    return tagged, stats


def judge_theme_strength(coverage: float, total_weight: float) -> str:
    if coverage >= 80 and total_weight >= 100:
        return "核心主线"
    if coverage >= 60 and total_weight >= 50:
        return "强主线"
    if coverage >= 40 and total_weight >= 20:
        return "次强方向"
    return "分散/弱方向"


def judge_theme_status(judgement: str, coverage: float, total_weight: float, heat_label: str | None = None) -> str:
    if judgement == "核心主线":
        if total_weight >= 180 or heat_label in {"很热", "极热"}:
            return "核心主线，但明显偏热"
        return "核心主线，仍可持续跟踪"
    if judgement == "强主线":
        return "强主线，关注是否继续强化"
    if judgement == "次强方向":
        return "次强方向，观察是否扩散"
    return "分散方向，暂不作为主线"


def compare_theme_stats(current: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame:
    if previous is None or previous.empty:
        out = current.copy()
        out["覆盖率变化pct"] = pd.NA
        out["持仓占比变化pct"] = pd.NA
        out["状态变化"] = "首次记录"
        return out
    cur = current[["主题", "主题覆盖率%", "合计持仓占比%", "主线状态"]].copy()
    prev = previous[["主题", "主题覆盖率%", "合计持仓占比%", "主线状态"]].copy()
    merged = cur.merge(prev, on="主题", how="outer", suffixes=("_当前", "_上期"))
    merged["覆盖率变化pct"] = merged["主题覆盖率%_当前"].fillna(0) - merged["主题覆盖率%_上期"].fillna(0)
    merged["持仓占比变化pct"] = merged["合计持仓占比%_当前"].fillna(0) - merged["合计持仓占比%_上期"].fillna(0)
    merged["状态变化"] = merged.apply(_state_change, axis=1)
    return merged


def _state_change(row: pd.Series) -> str:
    if pd.isna(row.get("主题覆盖率%_上期")):
        return "新兴主线" if row.get("主题覆盖率%_当前", 0) >= 40 else "新出现方向"
    if pd.isna(row.get("主题覆盖率%_当前")):
        return "疑似退潮"
    if row.get("覆盖率变化pct", 0) > 10 and row.get("持仓占比变化pct", 0) > 10:
        return "强化"
    if row.get("覆盖率变化pct", 0) < -10 and row.get("持仓占比变化pct", 0) < -10:
        return "疑似退潮"
    if row.get("覆盖率变化pct", 0) > 10:
        return "扩散"
    return "延续"
