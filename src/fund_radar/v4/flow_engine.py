from __future__ import annotations

import pandas as pd

from .config_v4 import V4Config, default_v4_config, has_theme_flow_change, valid_theme_mask


def _rank_score(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").rank(pct=True).fillna(0) * 100


def build_flow_report(features: pd.DataFrame, config: V4Config | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config or default_v4_config()
    if features.empty:
        return pd.DataFrame(), pd.DataFrame()
    df = features[valid_theme_mask(features)].copy()
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    if not has_theme_flow_change(df):
        df["主题强度基准分"] = _rank_score(df["主题强度分"])
        df["榜单口径"] = "首期基准快照：暂无历史主题暴露变化，不计算流入/流出"
        baseline = df.sort_values("主题强度基准分", ascending=False).head(config.top_n).reset_index(drop=True)
        outflow = pd.DataFrame(columns=["说明"])
        return baseline, outflow
    df["主题暴露流入分"] = (
        _rank_score(df["主题权重变化%"]) * config.flow_change_weight
        + _rank_score(df["V3主题权重%"]) * config.current_weight_weight
        + _rank_score(df["基金数量变化"]) * config.fund_count_weight
        + _rank_score(df["主题强度分"]) * config.theme_strength_weight
    )
    df["主题暴露流出分"] = (
        _rank_score(-df["主题权重变化%"]) * config.flow_change_weight
        + _rank_score(-df["V3主题权重%"]) * 0.20
        + _rank_score(-df["基金数量变化"]) * config.fund_count_weight
        + _rank_score(df["主题强度分"]) * 0.25
    )
    df["主题暴露口径"] = "主题暴露迁移代理，不是ETF真实资金流"
    inflow = df[df["主题权重变化%"].gt(0) | df["基金数量变化"].gt(0)].sort_values("主题暴露流入分", ascending=False).head(config.top_n).reset_index(drop=True)
    outflow = df[df["主题权重变化%"].lt(0) | df["基金数量变化"].lt(0)].sort_values("主题暴露流出分", ascending=False).head(config.top_n).reset_index(drop=True)
    return inflow, outflow
