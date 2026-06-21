from __future__ import annotations

import pandas as pd

from .config_v4 import V4Config, default_v4_config, valid_theme_mask


def _rank_score(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").rank(pct=True).fillna(0) * 100


def build_crowding_report(features: pd.DataFrame, config: V4Config | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    config = config or default_v4_config()
    if features.empty:
        empty = pd.DataFrame()
        return empty, empty, empty
    df = features[valid_theme_mask(features)].copy()
    if df.empty:
        empty = pd.DataFrame()
        return empty, empty, empty
    df["拥挤度分"] = (
        _rank_score(df["V3主题权重%"]) * 0.35
        + _rank_score(df["合计持仓占比%"]) * 0.30
        + _rank_score(df["涉及基金数量"]) * 0.20
        + _rank_score(df["主题覆盖率%"]) * 0.15
    )
    df["拥挤状态"] = pd.cut(
        df["拥挤度分"],
        bins=[-1, config.mid_crowding_threshold, config.high_crowding_threshold, 101],
        labels=["低拥挤机会", "中拥挤", "高拥挤风险"],
    ).astype(str)
    df.loc[df["V3主题权重%"] > config.max_theme_weight, "拥挤状态"] = "高拥挤风险"
    df["拥挤度口径"] = "基金主题暴露、主题集中度、覆盖基金数量等代理指标；不是ETF真实资金流"
    df["风险说明"] = df["拥挤状态"].map(
        {
            "高拥挤风险": "主题暴露集中，若主线退潮可能带来组合层面同步回撤",
            "中拥挤": "主题已有一定集中度，继续观察扩散和回撤变化",
            "低拥挤机会": "当前暴露不集中，仅作为低拥挤观察，不代表买入机会",
        }
    ).fillna("仅作主题暴露观察")
    high = df[df["拥挤状态"].eq("高拥挤风险")].sort_values("拥挤度分", ascending=False).head(config.top_n).reset_index(drop=True)
    mid = df[df["拥挤状态"].eq("中拥挤")].sort_values("拥挤度分", ascending=False).head(config.top_n).reset_index(drop=True)
    low = df[df["拥挤状态"].eq("低拥挤机会")].sort_values("主题强度分", ascending=False).head(config.top_n).reset_index(drop=True)
    return high, mid, low
