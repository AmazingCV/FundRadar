from __future__ import annotations

import pandas as pd

from ..utils import normalize_code
from .config_v3 import V3Config, default_v3_config
from .risk_engine import apply_fund_caps, apply_theme_caps, risk_flags
from .signal_adapter import V3Signals


def _take(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.head(n).copy() if df is not None and not df.empty else pd.DataFrame()


def _bucket_rows(df: pd.DataFrame, bucket: str, bucket_weight: float, n: int) -> pd.DataFrame:
    if df.empty or "基金代码" not in df.columns:
        return pd.DataFrame()
    out = _take(df, n)
    out["基金代码"] = out["基金代码"].map(normalize_code)
    out["来源池"] = bucket
    out["桶权重"] = bucket_weight
    out["基础权重"] = bucket_weight / max(len(out), 1)
    return out


def _dynamic_multiplier(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    r1m = pd.to_numeric(df.get("近1月收益率%", 0), errors="coerce").fillna(0)
    r3m = pd.to_numeric(df.get("近3月收益率%", 0), errors="coerce").fillna(0)
    dd = pd.to_numeric(df.get("近1年最大回撤%", 0), errors="coerce").fillna(0)
    vol = pd.to_numeric(df.get("近1年波动率%", 0), errors="coerce").fillna(0)
    m = pd.Series(1.0, index=df.index)
    m += r1m.rank(pct=True).fillna(0) * 0.20
    m += r3m.rank(pct=True).fillna(0) * 0.15
    m -= (dd.abs() > 15).astype(float) * 0.15
    m -= (dd.abs() > 25).astype(float) * 0.25
    m -= (vol > 50).astype(float) * 0.15
    return m.clip(lower=0.25)


def build_portfolio_allocation(signals: V3Signals, config: V3Config | None = None) -> pd.DataFrame:
    config = config or default_v3_config()
    pieces = [
        _bucket_rows(signals.selected, "精选池", config.selected_bucket, config.top_selected),
        _bucket_rows(signals.diversified, "分散池", config.diversified_bucket, config.top_diversified),
        _bucket_rows(signals.short_newstars, "新星池", config.newstar_bucket, config.top_newstar),
    ]
    raw = pd.concat([p for p in pieces if not p.empty], ignore_index=True) if any(not p.empty for p in pieces) else pd.DataFrame()
    if raw.empty:
        return pd.DataFrame(columns=["基金代码", "基金名称", "目标权重"])
    raw["动态乘数"] = _dynamic_multiplier(raw)
    raw["候选权重"] = pd.to_numeric(raw["基础权重"], errors="coerce").fillna(0) * raw["动态乘数"]
    grouped_cols = ["基金代码"]
    agg = {
        "基金名称": "first",
        "来源池": lambda x: "、".join(dict.fromkeys(map(str, x))),
        "候选权重": "sum",
        "近1周收益率%": "first",
        "近1月收益率%": "first",
        "近3月收益率%": "first",
        "近6月收益率%": "first",
        "近1年收益率%": "first",
        "近1年最大回撤%": "first",
        "近1年波动率%": "first",
        "热度提示": "first",
    }
    present_agg = {k: v for k, v in agg.items() if k in raw.columns}
    out = raw.groupby(grouped_cols, as_index=False).agg(present_agg)
    theme = signals.fund_theme[["基金代码", "主题", "主题持仓占比%"]] if not signals.fund_theme.empty else pd.DataFrame(columns=["基金代码", "主题", "主题持仓占比%"])
    out = out.merge(theme, on="基金代码", how="left")
    total = pd.to_numeric(out["候选权重"], errors="coerce").sum()
    invest_weight = 1.0 - config.cash_bucket
    out["目标权重"] = out["候选权重"] / total * invest_weight if total > 0 else 0
    out = apply_fund_caps(out, config)
    out = apply_theme_caps(out, config)
    total_after = pd.to_numeric(out["目标权重"], errors="coerce").sum()
    if total_after > 0:
        out["目标权重"] = out["目标权重"] / total_after * invest_weight
    out["目标权重%"] = out["目标权重"] * 100
    out["信号来源"] = out["来源池"]
    out["风险调整后权重%"] = out["目标权重%"]
    out["最终权重%"] = out["目标权重%"]
    out["现金保留%"] = config.cash_bucket * 100
    out = risk_flags(out, config)
    return out.sort_values("目标权重", ascending=False).reset_index(drop=True)


def allocation_summary(allocation: pd.DataFrame, config: V3Config | None = None) -> pd.DataFrame:
    config = config or default_v3_config()
    if allocation.empty:
        return pd.DataFrame()
    rows = [
        {"项目": "基金目标仓位合计%", "数值": float(pd.to_numeric(allocation["目标权重%"], errors="coerce").sum())},
        {"项目": "现金保留%", "数值": config.cash_bucket * 100},
        {"项目": "基金数量", "数值": len(allocation)},
        {"项目": "最大单基金权重%", "数值": float(pd.to_numeric(allocation["目标权重%"], errors="coerce").max())},
    ]
    if "主题" in allocation.columns:
        top_theme = allocation.groupby("主题")["目标权重%"].sum().sort_values(ascending=False)
        if not top_theme.empty:
            rows.append({"项目": f"最大主题暴露%：{top_theme.index[0]}", "数值": float(top_theme.iloc[0])})
    return pd.DataFrame(rows)
