from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd


def prepare_nav(nav: pd.DataFrame, as_of: str | datetime | None = None) -> pd.DataFrame:
    df = nav.copy()
    df["净值日期"] = pd.to_datetime(df["净值日期"])
    df["累计净值"] = pd.to_numeric(df["累计净值"], errors="coerce")
    df = df.dropna(subset=["净值日期", "累计净值"]).sort_values("净值日期")
    if as_of is not None:
        as_dt = pd.to_datetime(as_of)
        df = df[df["净值日期"] <= as_dt]
    return df.drop_duplicates("净值日期").reset_index(drop=True)


def pick_on_or_before(nav: pd.DataFrame, target_date: str | datetime) -> pd.Series | None:
    df = prepare_nav(nav)
    target = pd.to_datetime(target_date)
    sub = df[df["净值日期"] <= target]
    if sub.empty:
        return None
    return sub.iloc[-1]


def pick_on_or_after(nav: pd.DataFrame, target_date: str | datetime) -> pd.Series | None:
    df = prepare_nav(nav)
    target = pd.to_datetime(target_date)
    sub = df[df["净值日期"] >= target]
    if sub.empty:
        return None
    return sub.iloc[0]


def period_return(nav: pd.DataFrame, end_date: str | datetime, days: int) -> dict[str, Any]:
    df = prepare_nav(nav, end_date)
    if df.empty:
        return {"收益率%": np.nan, "起始净值日期": None, "结束净值日期": None, "起始累计净值": np.nan, "结束累计净值": np.nan}
    end_row = df.iloc[-1]
    target_start = pd.to_datetime(end_row["净值日期"]) - timedelta(days=int(days))
    start_row = pick_on_or_before(df, target_start)
    if start_row is None:
        start_row = df.iloc[0]
    start_val = float(start_row["累计净值"])
    end_val = float(end_row["累计净值"])
    ret = (end_val / start_val - 1.0) * 100 if start_val > 0 else np.nan
    return {
        "收益率%": ret,
        "起始净值日期": pd.to_datetime(start_row["净值日期"]).strftime("%Y-%m-%d"),
        "结束净值日期": pd.to_datetime(end_row["净值日期"]).strftime("%Y-%m-%d"),
        "起始累计净值": start_val,
        "结束累计净值": end_val,
    }


def forward_return(nav: pd.DataFrame, buy_date: str | datetime, days: int) -> dict[str, Any]:
    df = prepare_nav(nav)
    target_dt = pd.to_datetime(buy_date) + timedelta(days=int(days))
    latest_dt = df["净值日期"].max() if not df.empty else pd.NaT
    base = {
        "目标验证日期": target_dt.strftime("%Y-%m-%d"),
        "最新可用净值日期": latest_dt.strftime("%Y-%m-%d") if pd.notna(latest_dt) else None,
        "horizon是否到期": bool(pd.notna(latest_dt) and latest_dt >= target_dt),
        "是否完整验证": False,
        "验证状态": "未到期/不可验证" if pd.isna(latest_dt) or latest_dt < target_dt else "可验证",
    }
    buy_row = pick_on_or_after(df, buy_date)
    if buy_row is None:
        return {**base, "未来收益率%": np.nan, "买入净值日期": None, "卖出净值日期": None}
    if not base["horizon是否到期"]:
        return {
            **base,
            "未来收益率%": np.nan,
            "买入净值日期": pd.to_datetime(buy_row["净值日期"]).strftime("%Y-%m-%d"),
            "卖出净值日期": None,
        }
    sell_row = pick_on_or_before(df, target_dt)
    if sell_row is None or pd.to_datetime(sell_row["净值日期"]) <= pd.to_datetime(buy_row["净值日期"]):
        return {
            **base,
            "未来收益率%": np.nan,
            "买入净值日期": pd.to_datetime(buy_row["净值日期"]).strftime("%Y-%m-%d"),
            "卖出净值日期": None,
            "验证状态": "净值区间不足",
        }
    buy_val = float(buy_row["累计净值"])
    sell_val = float(sell_row["累计净值"])
    ret = (sell_val / buy_val - 1.0) * 100 if buy_val > 0 else np.nan
    return {
        **base,
        "未来收益率%": ret,
        "买入净值日期": pd.to_datetime(buy_row["净值日期"]).strftime("%Y-%m-%d"),
        "卖出净值日期": pd.to_datetime(sell_row["净值日期"]).strftime("%Y-%m-%d"),
        "买入累计净值": buy_val,
        "卖出累计净值": sell_val,
        "是否完整验证": True,
        "验证状态": "完整验证",
    }


def max_drawdown(nav: pd.DataFrame, end_date: str | datetime, days: int = 365) -> float:
    df = prepare_nav(nav, end_date)
    if df.empty:
        return np.nan
    end = df["净值日期"].max()
    start = end - timedelta(days=int(days))
    win = df[df["净值日期"] >= start]
    if len(win) < 2:
        return np.nan
    values = win["累计净值"].astype(float)
    running_max = values.cummax()
    dd = values / running_max - 1.0
    return float(dd.min() * 100)


def annualized_volatility(nav: pd.DataFrame, end_date: str | datetime, days: int = 365) -> float:
    df = prepare_nav(nav, end_date)
    if df.empty:
        return np.nan
    end = df["净值日期"].max()
    start = end - timedelta(days=int(days))
    win = df[df["净值日期"] >= start]
    if len(win) < 20:
        return np.nan
    ret = win["累计净值"].astype(float).pct_change().dropna()
    return float(ret.std() * np.sqrt(252) * 100)


def future_max_drawdown(nav: pd.DataFrame, start_date: str | datetime, days: int) -> float:
    df = prepare_nav(nav)
    start_row = pick_on_or_after(df, start_date)
    if start_row is None:
        return np.nan
    end_dt = pd.to_datetime(start_date) + timedelta(days=int(days))
    if df["净值日期"].max() < end_dt:
        return np.nan
    win = df[(df["净值日期"] >= pd.to_datetime(start_row["净值日期"])) & (df["净值日期"] <= end_dt)]
    if len(win) < 2:
        return np.nan
    values = win["累计净值"].astype(float)
    dd = values / values.cummax() - 1.0
    return float(dd.min() * 100)


def compute_feature_row(nav: pd.DataFrame, as_of: str | datetime, periods: dict[str, int]) -> dict[str, Any]:
    df = prepare_nav(nav, as_of)
    if df.empty:
        raise RuntimeError("as_of 前无可用净值")
    row: dict[str, Any] = {
        "扫描日": pd.to_datetime(as_of).strftime("%Y-%m-%d"),
        "最新净值日期": df["净值日期"].iloc[-1].strftime("%Y-%m-%d"),
        "数据起始日": df["净值日期"].iloc[0].strftime("%Y-%m-%d"),
        "净值样本数": len(df),
    }
    for name, days in periods.items():
        r = period_return(df, as_of, days)
        row[f"{name}收益率%"] = r["收益率%"]
        row[f"{name}起始净值日期"] = r["起始净值日期"]
        row[f"{name}结束净值日期"] = r["结束净值日期"]
    row["近1年最大回撤%"] = max_drawdown(df, as_of, 365)
    row["近1年波动率%"] = annualized_volatility(df, as_of, 365)
    return row
