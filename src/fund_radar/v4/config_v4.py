from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


INVALID_THEME_NAMES = {"", "未归因", "未知", "其他", "nan", "NaN", "NAN", "None", "none", "NONE", "null", "NULL"}


@dataclass(frozen=True)
class V4Config:
    top_n: int = 10
    high_crowding_threshold: float = 70.0
    mid_crowding_threshold: float = 45.0
    max_theme_weight: float = 60.0
    flow_change_weight: float = 0.40
    current_weight_weight: float = 0.30
    fund_count_weight: float = 0.15
    theme_strength_weight: float = 0.15


def default_v4_config() -> V4Config:
    return V4Config()


def valid_theme_mask(df: pd.DataFrame, theme_col: str = "主题") -> pd.Series:
    if df.empty or theme_col not in df.columns:
        return pd.Series(False, index=df.index)
    themes = df[theme_col].fillna("").astype(str).str.strip()
    return ~themes.isin(INVALID_THEME_NAMES)


def has_theme_flow_change(df: pd.DataFrame) -> bool:
    if df.empty:
        return False
    valid = df[valid_theme_mask(df)].copy()
    if valid.empty:
        return False
    change_cols = [col for col in ["主题权重变化%", "基金数量变化"] if col in valid.columns]
    if not change_cols:
        return False
    change_sum = 0.0
    for col in change_cols:
        change_sum += pd.to_numeric(valid[col], errors="coerce").fillna(0).abs().sum()
    return bool(change_sum > 1e-9)
