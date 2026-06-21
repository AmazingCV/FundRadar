from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..theme_analysis import load_theme_keywords, tag_stock_theme
from ..utils import normalize_code, project_path


@dataclass
class V3Signals:
    as_of: str
    v1_report: Path | None
    short_report: Path | None
    v2_report: Path | None
    selected: pd.DataFrame
    diversified: pd.DataFrame
    user_watch: pd.DataFrame
    theme_stats: pd.DataFrame
    holdings: pd.DataFrame
    short_total: pd.DataFrame
    short_newstars: pd.DataFrame
    short_acceleration: pd.DataFrame
    v2_conclusion: pd.DataFrame
    fund_theme: pd.DataFrame


def _latest(paths: list[Path]) -> Path | None:
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def latest_v1_report() -> Path | None:
    root = project_path("reports")
    candidates = [p for p in root.glob("20*/20*/基金雷达扫描结果.xlsx") if "time_machine" not in p.parts]
    return _latest(candidates)


def latest_short_report() -> Path | None:
    return _latest(list(project_path("reports").glob("20*/短期异动雷达.xlsx")))


def latest_v2_report() -> Path | None:
    return _latest(list(project_path("reports", "v2_lite").glob("20*/V2验证报告.xlsx")))


def _read_sheet(path: Path | None, sheet: str) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(path, sheet_name=sheet)
    except Exception:
        return pd.DataFrame()


def _norm_code_col(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "基金代码" in out.columns:
        out["基金代码"] = out["基金代码"].map(normalize_code)
    return out


def _as_of_from_reports(v1: Path | None, short: Path | None) -> str:
    for p in [short, v1]:
        if p is None:
            continue
        for part in reversed(p.parts):
            if len(part) == 10 and part[:4].isdigit() and part[4] == "-":
                return part
    return pd.Timestamp.today().strftime("%Y-%m-%d")


def build_fund_theme(holdings: pd.DataFrame) -> pd.DataFrame:
    if holdings.empty or "股票名称" not in holdings.columns or "基金代码" not in holdings.columns:
        return pd.DataFrame(columns=["基金代码", "主题", "主题持仓占比%"])
    themes = load_theme_keywords()
    rows: list[dict[str, Any]] = []
    df = holdings.copy()
    df["基金代码"] = df["基金代码"].map(normalize_code)
    df["持仓占比%"] = pd.to_numeric(df.get("持仓占比%", 0), errors="coerce").fillna(0)
    for _, r in df.iterrows():
        matched = tag_stock_theme(str(r.get("股票名称", "")), themes)
        for theme in matched:
            rows.append({"基金代码": r["基金代码"], "主题": theme, "主题持仓占比%": float(r["持仓占比%"])})
    if not rows:
        return pd.DataFrame(columns=["基金代码", "主题", "主题持仓占比%"])
    exposure = pd.DataFrame(rows).groupby(["基金代码", "主题"], as_index=False)["主题持仓占比%"].sum()
    idx = exposure.groupby("基金代码")["主题持仓占比%"].idxmax()
    return exposure.loc[idx].reset_index(drop=True)


def load_v3_signals(v1_report: str | Path | None = None, short_report: str | Path | None = None, v2_report: str | Path | None = None) -> V3Signals:
    v1 = Path(v1_report) if v1_report else latest_v1_report()
    short = Path(short_report) if short_report else latest_short_report()
    v2 = Path(v2_report) if v2_report else latest_v2_report()

    selected = _norm_code_col(_read_sheet(v1, "精选观察池"))
    diversified = _norm_code_col(_read_sheet(v1, "分散观察池"))
    user_watch = _norm_code_col(_read_sheet(v1, "用户观察池表现"))
    theme_stats = _read_sheet(v1, "主题统计")
    holdings = _norm_code_col(_read_sheet(v1, "精选基金重仓明细"))

    short_total = _norm_code_col(_read_sheet(short, "短期异动总榜"))
    short_newstars = _norm_code_col(_read_sheet(short, "近1月新星榜"))
    short_acceleration = _norm_code_col(_read_sheet(short, "本期新进强势榜"))
    v2_conclusion = _read_sheet(v2, "模块结论")
    fund_theme = build_fund_theme(holdings)

    return V3Signals(
        as_of=_as_of_from_reports(v1, short),
        v1_report=v1,
        short_report=short,
        v2_report=v2,
        selected=selected,
        diversified=diversified,
        user_watch=user_watch,
        theme_stats=theme_stats,
        holdings=holdings,
        short_total=short_total,
        short_newstars=short_newstars,
        short_acceleration=short_acceleration,
        v2_conclusion=v2_conclusion,
        fund_theme=fund_theme,
    )

