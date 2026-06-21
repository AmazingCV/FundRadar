from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .data_loader import DataLoader
from .utils import normalize_code


def fetch_watch_holdings(codes: list[str], loader: DataLoader, logger: logging.Logger | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    failures = []
    log = logger or logging.getLogger("fund_radar")
    for code in codes:
        code = normalize_code(code)
        try:
            df = loader.fetch_holdings(code)
            if df.empty:
                failures.append({"基金代码": code, "错误": "持仓为空"})
                continue
            latest_period = df["报告期"].dropna().astype(str).max() if "报告期" in df.columns else ""
            if latest_period:
                df = df[df["报告期"].astype(str) == latest_period]
            rows.append(df.assign(基金代码=code))
        except Exception as exc:  # noqa: BLE001
            log.warning("holding failed %s: %s", code, exc)
            failures.append({"基金代码": code, "错误": str(exc)})
    detail = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["基金代码", "报告期", "股票代码", "股票名称", "持仓占比%"])
    return detail, pd.DataFrame(failures)


def holding_stock_stats(detail: pd.DataFrame, fund_names: pd.DataFrame | None = None) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(columns=["股票名称", "出现次数", "涉及基金数量", "合计持仓占比%"])
    df = detail.copy()
    df["持仓占比%"] = pd.to_numeric(df["持仓占比%"], errors="coerce").fillna(0)
    g = df.groupby("股票名称", dropna=False).agg(
        出现次数=("股票名称", "size"),
        涉及基金数量=("基金代码", "nunique"),
        合计持仓占比=("持仓占比%", "sum"),
    )
    out = g.reset_index().sort_values(["合计持仓占比", "出现次数"], ascending=False)
    return out.rename(columns={"合计持仓占比": "合计持仓占比%"})
