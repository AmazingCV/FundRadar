from __future__ import annotations

import pandas as pd

from .config_v3 import V3Config, default_v3_config


def apply_fund_caps(allocation: pd.DataFrame, config: V3Config | None = None) -> pd.DataFrame:
    config = config or default_v3_config()
    if allocation.empty:
        return allocation
    out = allocation.copy()
    weights = pd.to_numeric(out["目标权重"], errors="coerce").fillna(0)
    excess = weights.sub(config.max_single_fund).clip(lower=0).sum()
    out["目标权重"] = weights.clip(upper=config.max_single_fund)
    under = out["目标权重"] < config.max_single_fund
    if excess > 0 and under.any():
        room = (config.max_single_fund - out.loc[under, "目标权重"]).clip(lower=0)
        room_sum = room.sum()
        if room_sum > 0:
            out.loc[under, "目标权重"] += room / room_sum * min(excess, room_sum)
    return out


def apply_theme_caps(allocation: pd.DataFrame, config: V3Config | None = None) -> pd.DataFrame:
    config = config or default_v3_config()
    if allocation.empty or "主题" not in allocation.columns:
        return allocation
    out = allocation.copy()
    out["主题"] = out["主题"].fillna("未归因")
    scale = pd.Series(1.0, index=out.index)
    for theme, g in out.groupby("主题"):
        total = pd.to_numeric(g["目标权重"], errors="coerce").sum()
        if theme != "未归因" and total > config.max_single_theme:
            scale.loc[g.index] = config.max_single_theme / total
    out["主题集中度调整前权重"] = out["目标权重"]
    out["目标权重"] = pd.to_numeric(out["目标权重"], errors="coerce").fillna(0) * scale
    return out


def risk_flags(allocation: pd.DataFrame, config: V3Config | None = None) -> pd.DataFrame:
    config = config or default_v3_config()
    if allocation.empty:
        return allocation
    out = allocation.copy()
    dd = pd.to_numeric(out.get("近1年最大回撤%", 0), errors="coerce").fillna(0)
    vol = pd.to_numeric(out.get("近1年波动率%", 0), errors="coerce").fillna(0)
    flags = []
    for i in out.index:
        parts = []
        if dd.loc[i] <= config.drawdown_clear:
            parts.append("回撤超过清仓线")
        elif dd.loc[i] <= config.drawdown_reduce:
            parts.append("回撤超过降仓线")
        if vol.loc[i] >= 50:
            parts.append("波动率过高")
        if pd.to_numeric(out.loc[i, "目标权重"], errors="coerce") >= config.max_single_fund:
            parts.append("接近单基金上限")
        flags.append("；".join(parts) if parts else "正常")
    out["风险提示"] = flags
    return out

