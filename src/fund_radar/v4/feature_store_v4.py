from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..utils import project_path, today_str


@dataclass
class V4FeatureStore:
    as_of: str
    v1_report: Path | None
    v3_dir: Path | None
    tracker_dir: Path | None
    theme_features: pd.DataFrame
    portfolio_log: pd.DataFrame
    source_note: str


def _latest(paths: list[Path]) -> Path | None:
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def latest_v1_report() -> Path | None:
    candidates = [p for p in project_path("reports").rglob("基金雷达扫描结果.xlsx") if "time_machine" not in p.parts and not p.name.startswith("~$")]
    return _latest(candidates)


def latest_v3_dir() -> Path | None:
    dirs = [p for p in project_path("reports", "v3").glob("20*") if p.is_dir()]
    return _latest(dirs)


def latest_tracker_dir() -> Path | None:
    dirs = [p for p in project_path("reports", "v3_tracker").glob("20*") if p.is_dir()]
    return _latest(dirs)


def _read_sheet(path: Path | None, sheet: str) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(path, sheet_name=sheet)
    except Exception:
        return pd.DataFrame()


def _read_first_sheet(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        xf = pd.ExcelFile(path)
        return pd.read_excel(path, sheet_name=xf.sheet_names[0])
    except Exception:
        return pd.DataFrame()


def _score_rank(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return x.rank(pct=True).fillna(0) * 100


def _theme_from_v1(v1_report: Path | None) -> pd.DataFrame:
    df = _read_sheet(v1_report, "主题统计")
    if df.empty:
        return pd.DataFrame(columns=["主题"])
    out = df.copy()
    for col in ["出现次数", "涉及基金数量", "合计持仓占比%", "主题覆盖率%"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    return out


def _theme_from_v3(v3_dir: Path | None) -> pd.DataFrame:
    if v3_dir is None:
        return pd.DataFrame(columns=["主题", "V3主题权重%"])
    alloc = _read_first_sheet(v3_dir / "portfolio_allocation.xlsx")
    if alloc.empty or "主题" not in alloc.columns:
        return pd.DataFrame(columns=["主题", "V3主题权重%"])
    weight_col = "最终权重%" if "最终权重%" in alloc.columns else ("目标权重%" if "目标权重%" in alloc.columns else None)
    if weight_col is None:
        return pd.DataFrame(columns=["主题", "V3主题权重%"])
    alloc["主题"] = alloc["主题"].fillna("未归因")
    alloc[weight_col] = pd.to_numeric(alloc[weight_col], errors="coerce").fillna(0)
    return alloc.groupby("主题", as_index=False)[weight_col].sum().rename(columns={weight_col: "V3主题权重%"})


def _portfolio_log(tracker_dir: Path | None) -> pd.DataFrame:
    if tracker_dir is None:
        return pd.DataFrame()
    return _read_sheet(tracker_dir / "daily_log.xlsx", "portfolio_log")


def _tracker_theme_delta(portfolio_log: pd.DataFrame) -> pd.DataFrame:
    if portfolio_log.empty or "主题" not in portfolio_log.columns or "记录日期" not in portfolio_log.columns:
        return pd.DataFrame(columns=["主题", "上期主题权重%", "本期主题权重%", "主题权重变化%", "基金数量变化", "是否首期记录"])
    weight_col = "最终权重%" if "最终权重%" in portfolio_log.columns else ("目标权重%" if "目标权重%" in portfolio_log.columns else None)
    if weight_col is None:
        return pd.DataFrame(columns=["主题", "上期主题权重%", "本期主题权重%", "主题权重变化%", "基金数量变化", "是否首期记录"])
    df = portfolio_log.copy()
    df["主题"] = df["主题"].fillna("未归因")
    df["记录日期"] = pd.to_datetime(df["记录日期"], errors="coerce")
    df[weight_col] = pd.to_numeric(df[weight_col], errors="coerce").fillna(0)
    by_date = sorted(df["记录日期"].dropna().unique())
    if not by_date:
        return pd.DataFrame(columns=["主题", "上期主题权重%", "本期主题权重%", "主题权重变化%", "基金数量变化", "是否首期记录"])
    cur_date = by_date[-1]
    prev_date = by_date[-2] if len(by_date) >= 2 else None
    cur = df[df["记录日期"].eq(cur_date)].groupby("主题").agg(本期主题权重=(weight_col, "sum"), 本期基金数量=("基金代码", "nunique")).reset_index()
    if prev_date is None:
        cur["上期主题权重%"] = cur["本期主题权重"]
        cur["上期基金数量"] = cur["本期基金数量"]
        cur["是否首期记录"] = True
    else:
        prev = df[df["记录日期"].eq(prev_date)].groupby("主题").agg(上期主题权重=(weight_col, "sum"), 上期基金数量=("基金代码", "nunique")).reset_index()
        cur = cur.merge(prev, on="主题", how="left")
        cur["上期主题权重%"] = cur["上期主题权重"].fillna(0)
        cur["上期基金数量"] = cur["上期基金数量"].fillna(0)
        cur["是否首期记录"] = False
    cur["本期主题权重%"] = cur["本期主题权重"]
    cur["主题权重变化%"] = cur["本期主题权重%"] - cur["上期主题权重%"]
    cur["基金数量变化"] = cur["本期基金数量"] - cur["上期基金数量"]
    return cur[["主题", "上期主题权重%", "本期主题权重%", "主题权重变化%", "基金数量变化", "是否首期记录"]]


def build_v4_feature_store() -> V4FeatureStore:
    v1 = latest_v1_report()
    v3 = latest_v3_dir()
    tracker = latest_tracker_dir()
    v1_theme = _theme_from_v1(v1)
    v3_theme = _theme_from_v3(v3)
    portfolio_log = _portfolio_log(tracker)
    delta = _tracker_theme_delta(portfolio_log)
    features = pd.DataFrame({"主题": sorted(set(v1_theme.get("主题", pd.Series(dtype=str)).dropna().astype(str)) | set(v3_theme.get("主题", pd.Series(dtype=str)).dropna().astype(str)) | set(delta.get("主题", pd.Series(dtype=str)).dropna().astype(str)))})
    if features.empty:
        features = pd.DataFrame({"主题": []})
    features = features.merge(v1_theme, on="主题", how="left")
    features = features.merge(v3_theme, on="主题", how="left")
    features = features.merge(delta, on="主题", how="left")
    for col in ["出现次数", "涉及基金数量", "合计持仓占比%", "主题覆盖率%", "V3主题权重%", "上期主题权重%", "本期主题权重%", "主题权重变化%", "基金数量变化"]:
        if col not in features.columns:
            features[col] = 0.0
        features[col] = pd.to_numeric(features[col], errors="coerce").fillna(0)
    features["主题强度分"] = (
        _score_rank(features["涉及基金数量"]) * 0.30
        + _score_rank(features["合计持仓占比%"]) * 0.30
        + _score_rank(features["主题覆盖率%"]) * 0.20
        + _score_rank(features["V3主题权重%"]) * 0.20
    )
    features["数据口径"] = "V1主题统计 + V3目标仓位 + V3_tracker历史记录；ETF资金流/成交额未直接接入，仅使用主题暴露迁移代理"
    return V4FeatureStore(
        as_of=today_str(),
        v1_report=v1,
        v3_dir=v3,
        tracker_dir=tracker,
        theme_features=features.sort_values("主题强度分", ascending=False).reset_index(drop=True),
        portfolio_log=portfolio_log,
        source_note="只读使用 V1/V3/V3_tracker 输出，不改上游逻辑；主题暴露变化为代理指标，不代表真实交易所资金流。",
    )
