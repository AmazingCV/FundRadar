from __future__ import annotations

import numpy as np
import pandas as pd


def percentile_score(s: pd.Series, higher_is_better: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    rank = x.rank(pct=True, method="average")
    if not higher_is_better:
        rank = 1 - rank
    return rank.fillna(0.0) * 100


def heat_label(one_year_return: float, thresholds: dict) -> str:
    if pd.isna(one_year_return):
        return "未知"
    if one_year_return >= thresholds.get("extreme", 150):
        return "极热"
    if one_year_return >= thresholds.get("hot", 100):
        return "很热"
    if one_year_return >= thresholds.get("warm", 60):
        return "偏热"
    return "正常"


def score_funds(df: pd.DataFrame, config: dict, use_overheat_penalty: bool | None = None) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    scoring = config.get("scoring", {})
    weights = scoring.get("weights", {})
    thresholds = scoring.get("overheat_thresholds", {})
    penalty_enabled = scoring.get("overheat_penalty", True) if use_overheat_penalty is None else use_overheat_penalty
    out = df.copy()
    total = pd.Series(0.0, index=out.index)
    for col, weight in weights.items():
        if col not in out.columns:
            out[col] = np.nan
        higher = "回撤" not in col
        total += percentile_score(out[col], higher_is_better=higher) * float(weight)

    # 加速信号：短中期动量明显强于长期动量时加分。
    m1 = pd.to_numeric(out.get("近1月收益率%", np.nan), errors="coerce")
    m3 = pd.to_numeric(out.get("近3月收益率%", np.nan), errors="coerce")
    m6 = pd.to_numeric(out.get("近6月收益率%", np.nan), errors="coerce")
    accel_raw = m1 * 3 + m3 - m6 * 0.5
    out["加速分"] = percentile_score(accel_raw)
    total += out["加速分"] * float(scoring.get("acceleration_weight", 0.0))

    one_year = pd.to_numeric(out.get("近1年收益率%", np.nan), errors="coerce")
    out["热度提示"] = one_year.apply(lambda x: heat_label(x, thresholds))
    penalty = pd.Series(0.0, index=out.index)
    if penalty_enabled:
        penalty += np.where(one_year >= thresholds.get("warm", 60), 3.0, 0.0)
        penalty += np.where(one_year >= thresholds.get("hot", 100), 5.0, 0.0)
        penalty += np.where(one_year >= thresholds.get("extreme", 150), 8.0, 0.0)
    out["过热惩罚"] = penalty
    out["最终分"] = total - penalty

    conditions = [
        out["热度提示"].eq("极热"),
        out["热度提示"].eq("很热"),
        out["热度提示"].eq("偏热"),
    ]
    choices = ["收益已极端，观察为主，避免把趋势信号误读为低风险", "趋势很强但拥挤风险高", "趋势偏热，需配合回撤和主题拥挤度跟踪"]
    out["风险提示"] = np.select(conditions, choices, default="趋势信号正常，仍需关注回撤和主题切换")
    return out.sort_values("最终分", ascending=False).reset_index(drop=True)


def build_rankings(scored: pd.DataFrame, top_n: int = 50) -> dict[str, pd.DataFrame]:
    if scored.empty:
        return {}
    rankings = {
        "综合强势榜": scored.sort_values("最终分", ascending=False).head(top_n),
        "近一月强势榜": scored.sort_values("近1月收益率%", ascending=False).head(top_n),
        "近三月强势榜": scored.sort_values("近3月收益率%", ascending=False).head(top_n),
        "近六月强势榜": scored.sort_values("近6月收益率%", ascending=False).head(top_n),
        "近一年强势榜": scored.sort_values("近1年收益率%", ascending=False).head(top_n),
        "低回撤强势榜": scored.sort_values(["近1年最大回撤%", "近3月收益率%"], ascending=[False, False]).head(top_n),
        "加速变强榜": scored.sort_values("加速分", ascending=False).head(top_n),
    }
    return {k: v.reset_index(drop=True) for k, v in rankings.items()}
