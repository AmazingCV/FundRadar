from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..utils import parse_date, project_path, today_str


@dataclass
class DailySignals:
    as_of: str
    core_themes: pd.DataFrame
    secondary_themes: pd.DataFrame
    crowding_high: pd.DataFrame
    crowding_mid: pd.DataFrame
    rotation: pd.DataFrame
    short_term_top: pd.DataFrame
    new_star_top: pd.DataFrame
    short_term_theme: pd.DataFrame
    selected_pool: pd.DataFrame
    diversified_pool: pd.DataFrame
    v3_allocation: pd.DataFrame
    v3_dca: pd.DataFrame
    v3_exit: pd.DataFrame
    tracker_theme_change: pd.DataFrame
    v2_lite: pd.DataFrame
    unmapped_exposure: pd.DataFrame
    sources: pd.DataFrame


def normalize_report_date(value: str | date | datetime | None = None) -> str:
    if value is None or str(value).lower() == "today":
        return today_str()
    parsed = parse_date(value)
    if parsed is None:
        return today_str()
    return parsed.strftime("%Y-%m-%d")


def _latest(paths: list[Path], as_of: str | None = None) -> Path | None:
    valid = [p for p in paths if p.exists() and not p.name.startswith("~$")]
    if as_of:
        target = parse_date(as_of)
        if target is not None:
            dated = []
            for p in valid:
                dt = _date_from_parts(p)
                if dt is None or dt <= target:
                    dated.append(p)
            valid = dated
    return max(valid, key=lambda p: p.stat().st_mtime) if valid else None


def _date_from_parts(path: Path) -> datetime | None:
    for part in reversed(path.parts):
        try:
            return datetime.strptime(part[:10], "%Y-%m-%d")
        except ValueError:
            continue
    return None


def _report_file_by_name(root: Path, filename: str, as_of: str) -> Path | None:
    return _latest([p for p in root.rglob(filename) if "time_machine" not in p.parts], as_of=as_of)


def _dated_dir(root: Path, as_of: str) -> Path | None:
    if not root.exists():
        return None
    exact = root / as_of
    if exact.exists():
        return exact
    dirs = [p for p in root.glob("20*") if p.is_dir()]
    return _latest(dirs, as_of=as_of)


def _monthly_dir(root: Path, as_of: str) -> Path | None:
    if not root.exists():
        return None
    parsed = parse_date(as_of)
    if parsed is None:
        return None
    exact = root / f"{parsed:%Y-%m}"
    if exact.exists():
        return exact
    dirs = [p for p in root.glob("20*") if p.is_dir()]
    return _latest(dirs, as_of=as_of)


def _read_sheet(path: Path | None, sheet: str | int = 0) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(path, sheet_name=sheet)
    except Exception:
        return pd.DataFrame()


def _read_first_existing(path: Path | None, names: list[str]) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        xf = pd.ExcelFile(path)
    except Exception:
        return pd.DataFrame()
    for name in names:
        if name in xf.sheet_names:
            return _read_sheet(path, name)
    return pd.DataFrame()


def _head(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.head(n).copy() if df is not None and not df.empty else pd.DataFrame()


def _source_row(name: str, path: Path | None, note: str = "") -> dict[str, Any]:
    return {"来源": name, "路径": str(path) if path else "", "说明": note}


def _theme_from_v4_flow(flow_report: Path | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    theme = _read_sheet(flow_report, "主题特征")
    if theme.empty or "主题" not in theme.columns:
        return pd.DataFrame(), pd.DataFrame()
    state = theme.copy()
    main_col = "主线判断" if "主线判断" in state.columns else None
    status_col = "主线状态" if "主线状态" in state.columns else None
    if main_col:
        core = state[state[main_col].astype(str).str.contains("核心|强主线", na=False)]
        secondary = state[state[main_col].astype(str).str.contains("次强", na=False)]
    elif status_col:
        core = state[state[status_col].astype(str).str.contains("核心|强主线", na=False)]
        secondary = state[state[status_col].astype(str).str.contains("次强|扩散", na=False)]
    else:
        core = state.head(0)
        secondary = state.head(0)
    return core.reset_index(drop=True), secondary.reset_index(drop=True)


def _tracker_theme_change(tracker_log: pd.DataFrame) -> pd.DataFrame:
    if tracker_log.empty or "记录日期" not in tracker_log.columns or "主题" not in tracker_log.columns:
        return pd.DataFrame([{"说明": "暂无 V3_tracker 历史记录，无法判断主题权重变化"}])
    weight_col = "最终权重%" if "最终权重%" in tracker_log.columns else ("目标权重%" if "目标权重%" in tracker_log.columns else None)
    if weight_col is None:
        return pd.DataFrame([{"说明": "V3_tracker 缺少权重列，无法判断主题权重变化"}])
    df = tracker_log.copy()
    df["记录日期"] = pd.to_datetime(df["记录日期"], errors="coerce")
    df["主题"] = df["主题"].fillna("未归因")
    df[weight_col] = pd.to_numeric(df[weight_col], errors="coerce").fillna(0)
    by_date = sorted(df["记录日期"].dropna().unique())
    if not by_date:
        return pd.DataFrame([{"说明": "V3_tracker 记录日期为空，无法判断主题权重变化"}])
    cur_date = by_date[-1]
    current = df[df["记录日期"].eq(cur_date)].groupby("主题", as_index=False)[weight_col].sum().rename(columns={weight_col: "本期主题权重%"})
    if len(by_date) < 2:
        current["上期主题权重%"] = current["本期主题权重%"]
        current["主题权重变化%"] = 0.0
        current["趋势判断"] = "首期记录，暂无趋势"
        return current
    prev_date = by_date[-2]
    previous = df[df["记录日期"].eq(prev_date)].groupby("主题", as_index=False)[weight_col].sum().rename(columns={weight_col: "上期主题权重%"})
    out = current.merge(previous, on="主题", how="outer").fillna(0)
    out["主题权重变化%"] = out["本期主题权重%"] - out["上期主题权重%"]
    out["趋势判断"] = out["主题权重变化%"].map(lambda x: "上升" if x > 0 else ("下降" if x < 0 else "持平"))
    return out.sort_values("主题权重变化%", ascending=False).reset_index(drop=True)


def aggregate_daily_signals(as_of: str | date | datetime | None = None, top_n: int = 10) -> DailySignals:
    date_text = normalize_report_date(as_of)
    reports = project_path("reports")

    v1_report = _report_file_by_name(reports, "基金雷达扫描结果.xlsx", date_text)
    short_report = _report_file_by_name(reports, "短期异动雷达.xlsx", date_text)
    v2_dir = _dated_dir(reports / "v2_lite", date_text)
    v2_report = v2_dir / "V2验证报告.xlsx" if v2_dir else None
    v3_dir = _dated_dir(reports / "v3", date_text)
    tracker_dir = _monthly_dir(reports / "v3_tracker", date_text)
    v4_dir = _dated_dir(reports / "v4", date_text)

    v4_flow = v4_dir / "flow_report.xlsx" if v4_dir else None
    v4_crowding = v4_dir / "crowding_report.xlsx" if v4_dir else None
    v4_rotation = v4_dir / "rotation_report.xlsx" if v4_dir else None

    core, secondary = _theme_from_v4_flow(v4_flow)
    crowding_high = _read_sheet(v4_crowding, "高拥挤风险榜")
    crowding_mid = _read_sheet(v4_crowding, "中拥挤榜")
    rotation = _read_sheet(v4_rotation, "轮动机会榜")
    unmapped = _read_first_existing(v4_flow, ["unmapped_exposure"])

    short_top = _read_first_existing(short_report, ["短期异动总榜"])
    new_star = _read_first_existing(short_report, ["近1月新星榜", "本期新进强势榜"])
    short_theme = _read_first_existing(short_report, ["主题异动榜"])

    selected = _read_first_existing(v1_report, ["精选观察池"])
    diversified = _read_first_existing(v1_report, ["分散观察池"])
    allocation = _read_sheet(v3_dir / "portfolio_allocation.xlsx" if v3_dir else None, 0)
    dca = _read_first_existing(v3_dir / "dca_plan.xlsx" if v3_dir else None, ["DCA计划"])
    exit_plan = _read_first_existing(v3_dir / "exit_plan.xlsx" if v3_dir else None, ["止盈退出计划"])
    tracker_log = _read_first_existing(tracker_dir / "daily_log.xlsx" if tracker_dir else None, ["portfolio_log"])
    tracker_change = _tracker_theme_change(tracker_log)
    v2_lite = _read_sheet(v2_report, 0)

    sources = pd.DataFrame(
        [
            _source_row("V1精选观察池", v1_report, "只读基金雷达扫描结果"),
            _source_row("V1.1短期异动", short_report, "只读短期异动雷达"),
            _source_row("V2-lite验证", v2_report, "如存在则只读验证结果"),
            _source_row("V3仓位/DCA/退出", v3_dir, "只读资金建议输出"),
            _source_row("V3_tracker", tracker_dir, "只读历史记录"),
            _source_row("V4 flow", v4_flow, "只读主题暴露迁移代理"),
            _source_row("V4 crowding", v4_crowding, "只读拥挤度输出"),
            _source_row("V4 rotation", v4_rotation, "只读轮动路径输出"),
        ]
    )

    return DailySignals(
        as_of=date_text,
        core_themes=_head(core, top_n),
        secondary_themes=_head(secondary, top_n),
        crowding_high=_head(crowding_high, top_n),
        crowding_mid=_head(crowding_mid, top_n),
        rotation=_head(rotation, top_n),
        short_term_top=_head(short_top, top_n),
        new_star_top=_head(new_star, top_n),
        short_term_theme=_head(short_theme, top_n),
        selected_pool=_head(selected, top_n),
        diversified_pool=_head(diversified, top_n),
        v3_allocation=_head(allocation, top_n),
        v3_dca=_head(dca, top_n),
        v3_exit=_head(exit_plan, top_n),
        tracker_theme_change=_head(tracker_change, top_n),
        v2_lite=_head(v2_lite, top_n),
        unmapped_exposure=unmapped,
        sources=sources,
    )

