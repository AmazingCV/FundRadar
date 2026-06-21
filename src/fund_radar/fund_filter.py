from __future__ import annotations

import pandas as pd

from .utils import normalize_code, normalize_name_for_ac


def active_equity_filter(fund_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    df = fund_df.copy()
    if "基金代码" in df:
        df["基金代码"] = df["基金代码"].map(normalize_code)
    for col in ("基金名称", "基金类型"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)
    fconf = config.get("fund_filter", {})
    include_types = fconf.get("include_types", ["股票型", "混合型"])
    exclude_keywords = fconf.get("exclude_keywords", [])
    text = df["基金名称"] + " " + df["基金类型"]
    include_mask = text.apply(lambda s: any(k in s for k in include_types))
    exclude_mask = text.apply(lambda s: any(k.lower() in s.lower() for k in exclude_keywords))
    out = df[include_mask & ~exclude_mask].copy()
    out = out.drop_duplicates("基金代码")
    return out.reset_index(drop=True)


def dedupe_ac(df: pd.DataFrame, score_col: str = "最终分") -> pd.DataFrame:
    if df.empty or "基金名称" not in df.columns:
        return df
    tmp = df.copy()
    tmp["_ac_key"] = tmp["基金名称"].map(normalize_name_for_ac)
    sort_cols = [score_col] if score_col in tmp.columns else []
    sort_cols += ["基金代码"]
    asc = [False] * (len(sort_cols) - 1) + [True] if sort_cols else True
    tmp = tmp.sort_values(sort_cols, ascending=asc) if sort_cols else tmp
    tmp = tmp.drop_duplicates("_ac_key", keep="first").drop(columns="_ac_key")
    return tmp.reset_index(drop=True)


def force_include(df: pd.DataFrame, watchlist: pd.DataFrame) -> pd.DataFrame:
    if watchlist is None or watchlist.empty:
        return df
    base = df.copy()
    watch = watchlist.copy()
    watch["基金代码"] = watch["基金代码"].map(normalize_code)
    if "基金名称" not in watch:
        watch["基金名称"] = ""
    if "基金类型" not in watch:
        watch["基金类型"] = "观察池强制加入"
    out = pd.concat([base, watch[["基金代码", "基金名称", "基金类型"]]], ignore_index=True)
    return out.drop_duplicates("基金代码", keep="first").reset_index(drop=True)
