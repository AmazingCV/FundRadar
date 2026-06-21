from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..utils import normalize_code, project_path
from .config_v3 import V3Config, default_v3_config
from .portfolio_engine import build_portfolio_allocation
from .signal_adapter import V3Signals, build_fund_theme


def _read(path: Path, sheet: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet)
    except Exception:
        return pd.DataFrame()


def _portfolio_ret(future: pd.DataFrame, weights: pd.DataFrame, horizon: str) -> float:
    if future.empty or weights.empty:
        return np.nan
    ret_col = f"未来{horizon}收益%"
    if ret_col not in future.columns:
        return np.nan
    f = future.copy()
    f["基金代码"] = f["基金代码"].map(normalize_code)
    w = weights[["基金代码", "目标权重"]].copy()
    w["基金代码"] = w["基金代码"].map(normalize_code)
    m = f.merge(w, on="基金代码", how="inner")
    if m.empty:
        return np.nan
    total_w = pd.to_numeric(m["目标权重"], errors="coerce").sum()
    if total_w <= 0:
        return np.nan
    return float((pd.to_numeric(m[ret_col], errors="coerce") * pd.to_numeric(m["目标权重"], errors="coerce")).sum() / total_w)


def _equal_ret(future: pd.DataFrame, codes: set[str], horizon: str) -> float:
    ret_col = f"未来{horizon}收益%"
    if future.empty or ret_col not in future.columns:
        return np.nan
    f = future.copy()
    f["基金代码"] = f["基金代码"].map(normalize_code)
    sub = f[f["基金代码"].isin(codes)]
    return float(pd.to_numeric(sub[ret_col], errors="coerce").mean()) if not sub.empty else np.nan


def _load_nav(code: str) -> pd.DataFrame:
    path = project_path("data", "cache", "nav", f"{normalize_code(code)}.csv")
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["净值日期"] = pd.to_datetime(df["净值日期"], errors="coerce")
    df["累计净值"] = pd.to_numeric(df["累计净值"], errors="coerce")
    return df.dropna(subset=["净值日期", "累计净值"]).sort_values("净值日期")


def _nav_forward_return(code: str, as_of: str, days: int) -> float:
    nav = _load_nav(code)
    if nav.empty:
        return np.nan
    start_dt = pd.to_datetime(as_of)
    target_dt = start_dt + pd.Timedelta(days=int(days))
    if nav["净值日期"].max() < target_dt:
        return np.nan
    buy = nav[nav["净值日期"] >= start_dt]
    sell = nav[nav["净值日期"] <= target_dt]
    if buy.empty or sell.empty:
        return np.nan
    buy_row = buy.iloc[0]
    sell_row = sell.iloc[-1]
    if sell_row["净值日期"] <= buy_row["净值日期"]:
        return np.nan
    buy_val = float(buy_row["累计净值"])
    sell_val = float(sell_row["累计净值"])
    return (sell_val / buy_val - 1) * 100 if buy_val > 0 else np.nan


def _portfolio_ret_from_nav(weights: pd.DataFrame, as_of: str, days: int) -> float:
    if weights.empty:
        return np.nan
    vals = []
    wts = []
    for _, r in weights.iterrows():
        ret = _nav_forward_return(r.get("基金代码"), as_of, days)
        wt = pd.to_numeric(r.get("目标权重"), errors="coerce")
        if pd.notna(ret) and pd.notna(wt) and wt > 0:
            vals.append(ret)
            wts.append(float(wt))
    if not vals:
        return np.nan
    w = np.array(wts, dtype=float)
    return float(np.dot(np.array(vals, dtype=float), w / w.sum()))


def _equal_ret_from_nav(codes: set[str], as_of: str, days: int) -> float:
    vals = [_nav_forward_return(code, as_of, days) for code in codes]
    vals = [v for v in vals if pd.notna(v)]
    return float(np.mean(vals)) if vals else np.nan


def _metrics(series: pd.Series) -> dict[str, float]:
    x = pd.to_numeric(series, errors="coerce").dropna()
    if x.empty:
        return {"累计收益%": np.nan, "平均单期收益%": np.nan, "最大回撤%": np.nan, "夏普比": np.nan, "胜率%": np.nan}
    curve = (1 + x / 100).cumprod()
    dd = curve / curve.cummax() - 1
    std = x.std()
    return {
        "累计收益%": float((curve.iloc[-1] - 1) * 100),
        "平均单期收益%": float(x.mean()),
        "最大回撤%": float(dd.min() * 100),
        "夏普比": float(x.mean() / std * np.sqrt(12)) if std and pd.notna(std) else np.nan,
        "胜率%": float((x > 0).mean() * 100),
    }


def _market_return(summary: pd.DataFrame, horizon: str) -> float:
    if summary.empty:
        return np.nan
    candidates = [
        f"全候选平均未来{horizon}收益%",
        f"全候选池平均未来{horizon}收益%",
        f"全候选平均未来{horizon}收益率%",
    ]
    for col in candidates:
        if col in summary.columns:
            return pd.to_numeric(summary[col], errors="coerce").iloc[0]
    for col in summary.columns:
        if f"未来{horizon}" in str(col) and "全候选" in str(col) and "收益" in str(col):
            return pd.to_numeric(summary[col], errors="coerce").iloc[0]
    return np.nan


def run_v3_backtest(config: V3Config | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config or default_v3_config()
    rows = []
    reports = sorted(project_path("reports").rglob("历史时点观察池.xlsx"))
    rng = np.random.default_rng(config.random_seed)
    for path in reports:
        as_of = path.parent.name
        observed = _read(path, "历史时点观察池")
        selected = _read(path, "历史时点精选基金")
        diversified = _read(path, "历史时点分散观察池")
        future = _read(path, "模拟组合验证")
        combo_summary = _read(path, "组合汇总")
        holdings = _read(path, "重仓明细")
        if observed.empty or future.empty:
            continue
        for df in [observed, selected, diversified, future, holdings]:
            if "基金代码" in df.columns:
                df["基金代码"] = df["基金代码"].map(normalize_code)
        signals = V3Signals(
            as_of=as_of,
            v1_report=path,
            short_report=None,
            v2_report=None,
            selected=selected,
            diversified=diversified,
            user_watch=pd.DataFrame(),
            theme_stats=_read(path, "主题统计"),
            holdings=holdings,
            short_total=pd.DataFrame(),
            short_newstars=observed.sort_values("近1周收益率%", ascending=False).head(config.top_newstar),
            short_acceleration=pd.DataFrame(),
            v2_conclusion=pd.DataFrame(),
            fund_theme=build_fund_theme(holdings),
        )
        allocation = build_portfolio_allocation(signals, config)
        selected_codes = set(selected["基金代码"].head(5)) if not selected.empty else set()
        all_codes = list(observed["基金代码"].dropna().map(normalize_code).unique())
        random_codes = set(rng.choice(all_codes, size=min(10, len(all_codes)), replace=False)) if all_codes else set()
        for horizon, days in config.backtest_horizons.items():
            rows.append(
                {
                    "扫描日": as_of,
                    "horizon": horizon,
                    "V3组合收益%": _portfolio_ret_from_nav(allocation, as_of, days),
                    "V1精选池收益%": _equal_ret_from_nav(selected_codes, as_of, days),
                    "全市场收益%": _market_return(combo_summary, horizon),
                    "随机组合收益%": _equal_ret_from_nav(random_codes, as_of, days),
                }
            )
    detail = pd.DataFrame(rows)
    summary_rows = []
    if not detail.empty:
        for horizon, g in detail.groupby("horizon"):
            for col in ["V3组合收益%", "V1精选池收益%", "全市场收益%", "随机组合收益%"]:
                m = _metrics(g[col])
                summary_rows.append({"对象": col.replace("收益%", ""), "horizon": horizon, **m})
    return detail, pd.DataFrame(summary_rows)
