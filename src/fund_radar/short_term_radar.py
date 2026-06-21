from __future__ import annotations

import argparse
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .data_loader import DataLoader
from .holdings import fetch_watch_holdings
from .metrics import forward_return, future_max_drawdown
from .pipeline import build_candidate_pool
from .report import bar_chart, write_excel, write_markdown
from .scoring import heat_label
from .theme_analysis import analyze_themes, load_theme_keywords
from .utils import ensure_dir, load_config, normalize_code, project_path, setup_logging, today_str


LOOKBACK_DAYS = {
    "1d": 1,
    "2d": 2,
    "3d": 3,
    "5d": 5,
    "10d": 10,
    "1w": 7,
    "1m": 30,
}

VERIFY_DAYS = {
    "1w": ("1周", 7),
    "2w": ("2周", 14),
    "1m": ("1月", 30),
    "3m": ("3月", 91),
}

SHORT_TERM_SCHEMES = {
    "方案A_短期动量版": {
        "近1周排名分": 0.45,
        "近1月排名分": 0.20,
        "排名提升分": 0.20,
        "加速分": 0.10,
        "未过热奖励": 0.05,
    },
    "方案B_新星版": {
        "近1周排名分": 0.25,
        "近1月排名分": 0.30,
        "排名提升分": 0.30,
        "加速分": 0.05,
        "未过热奖励": 0.10,
    },
    "方案C_防追高版": {
        "近1周排名分": 0.25,
        "近1月排名分": 0.25,
        "排名提升分": 0.15,
        "加速分": 0.10,
        "未过热奖励": 0.25,
    },
    "方案D_主题扩散版": {
        "近1周排名分": 0.30,
        "近1月排名分": 0.25,
        "排名提升分": 0.20,
        "加速分": 0.15,
        "未过热奖励": 0.10,
    },
}


def parse_lookbacks(text: str | None) -> dict[str, int]:
    if not text:
        return LOOKBACK_DAYS.copy()
    out = {}
    for token in text.split(","):
        key = token.strip().lower()
        if key in LOOKBACK_DAYS:
            out[key] = LOOKBACK_DAYS[key]
    return out or LOOKBACK_DAYS.copy()


def parse_verify_horizons(text: str | None) -> dict[str, int]:
    if not text:
        return {name: days for _, (name, days) in VERIFY_DAYS.items()}
    out = {}
    for token in text.split(","):
        key = token.strip().lower()
        if key in VERIFY_DAYS:
            name, days = VERIFY_DAYS[key]
            out[name] = days
    return out or {name: days for _, (name, days) in VERIFY_DAYS.items()}


def pct_score(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    score = x.rank(pct=True, method="average") * 100
    if not higher_is_better:
        score = (1 - x.rank(pct=True, method="average")) * 100
    return score.fillna(0)


def ordinal_rank(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rank(method="min", ascending=not higher_is_better)


def load_navs(pool: pd.DataFrame, loader: DataLoader, logger: logging.Logger) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    navs: dict[str, pd.DataFrame] = {}
    failures = []
    for _, fund in pool.iterrows():
        code = normalize_code(fund["基金代码"])
        try:
            navs[code] = loader.fetch_nav(code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("short radar nav failed %s: %s", code, exc)
            failures.append({"基金代码": code, "基金名称": fund.get("基金名称", ""), "错误": str(exc)})
    return navs, pd.DataFrame(failures)


def raw_short_features(pool: pd.DataFrame, navs: dict[str, pd.DataFrame], as_of: str, logger: logging.Logger) -> pd.DataFrame:
    rows = []
    periods = {
        "近1日收益率%": 1,
        "近2日收益率%": 2,
        "近3日收益率%": 3,
        "近5日收益率%": 5,
        "近10日收益率%": 10,
        "近1周收益率%": 7,
        "近1月收益率%": 30,
        "近3月收益率%": 91,
        "近6月收益率%": 182,
        "近1年收益率%": 365,
    }
    for _, fund in pool.iterrows():
        code = normalize_code(fund["基金代码"])
        nav = navs.get(code)
        if nav is None or nav.empty:
            continue
        try:
            calc = calc_short_returns(nav, as_of, periods)
            if not calc:
                continue
            row: dict[str, Any] = {
                "基金代码": code,
                "基金名称": fund.get("基金名称", ""),
                "基金类型": fund.get("基金类型", ""),
                "扫描日": pd.to_datetime(as_of).strftime("%Y-%m-%d"),
            }
            for col, days in periods.items():
                r = calc[col]
                row[col] = r["收益率%"]
                row[f"{col.replace('收益率%', '')}起始净值日期"] = r["起始净值日期"]
                row[f"{col.replace('收益率%', '')}结束净值日期"] = r["结束净值日期"]
            row["最新净值日期"] = calc["最新净值日期"]
            row["近1年最大回撤%"] = calc["近1年最大回撤%"]
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            logger.debug("short feature failed %s: %s", code, exc)
    return pd.DataFrame(rows)


def calc_short_returns(nav: pd.DataFrame, as_of: str | pd.Timestamp, periods: dict[str, int]) -> dict[str, Any]:
    df = nav.copy()
    df["净值日期"] = pd.to_datetime(df["净值日期"], errors="coerce")
    df["累计净值"] = pd.to_numeric(df["累计净值"], errors="coerce")
    df = df.dropna(subset=["净值日期", "累计净值"]).sort_values("净值日期").drop_duplicates("净值日期")
    df = df[df["净值日期"] <= pd.to_datetime(as_of)]
    if df.empty:
        return {}
    dates = df["净值日期"].to_numpy()
    values = df["累计净值"].astype(float).to_numpy()
    end_date = pd.Timestamp(df["净值日期"].iloc[-1])
    end_value = float(values[-1])
    out: dict[str, Any] = {"最新净值日期": end_date.strftime("%Y-%m-%d")}
    for col, days in periods.items():
        target = np.datetime64(end_date - timedelta(days=int(days)))
        idx = int(np.searchsorted(dates, target, side="right") - 1)
        if idx < 0:
            idx = 0
        start_value = float(values[idx])
        ret = (end_value / start_value - 1.0) * 100 if start_value > 0 else np.nan
        out[col] = {
            "收益率%": ret,
            "起始净值日期": pd.Timestamp(dates[idx]).strftime("%Y-%m-%d"),
            "结束净值日期": end_date.strftime("%Y-%m-%d"),
        }
    start_1y = np.datetime64(end_date - timedelta(days=365))
    start_idx = int(np.searchsorted(dates, start_1y, side="left"))
    win = values[start_idx:]
    if len(win) >= 2:
        dd = win / np.maximum.accumulate(win) - 1.0
        out["近1年最大回撤%"] = float(np.nanmin(dd) * 100)
    else:
        out["近1年最大回撤%"] = np.nan
    return out


def score_short_features(
    current: pd.DataFrame,
    previous: pd.DataFrame | None,
    config: dict,
    previous_top50: set[str] | None = None,
    new_watch_codes: set[str] | None = None,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    if current.empty:
        return current
    cfg = config.get("short_term_radar", {})
    weights = weights or cfg.get("score_weights", {})
    penalties = cfg.get("penalties", {})
    out = current.copy()
    out["近1周排名"] = ordinal_rank(out["近1周收益率%"])
    out["近1月排名"] = ordinal_rank(out["近1月收益率%"])
    out["近1周排名分"] = pct_score(out["近1周收益率%"])
    out["近1月排名分"] = pct_score(out["近1月收益率%"])

    if previous is not None and not previous.empty:
        prev = previous[["基金代码", "近1周排名分", "近1月排名分", "近1周排名", "近1月排名"]].rename(
            columns={
                "近1周排名分": "上期近1周排名分",
                "近1月排名分": "上期近1月排名分",
                "近1周排名": "上期近1周排名",
                "近1月排名": "上期近1月排名",
            }
        )
        out = out.merge(prev, on="基金代码", how="left")
    else:
        out["上期近1周排名分"] = pd.NA
        out["上期近1月排名分"] = pd.NA
        out["上期近1周排名"] = pd.NA
        out["上期近1月排名"] = pd.NA

    out["近1周排名提升"] = pd.to_numeric(out["近1周排名分"], errors="coerce") - pd.to_numeric(out["上期近1周排名分"], errors="coerce")
    out["近1月排名提升"] = pd.to_numeric(out["近1月排名分"], errors="coerce") - pd.to_numeric(out["上期近1月排名分"], errors="coerce")
    out["排名提升分"] = pct_score(out[["近1周排名提升", "近1月排名提升"]].mean(axis=1))

    m1w = pd.to_numeric(out["近1周收益率%"], errors="coerce")
    m1m = pd.to_numeric(out["近1月收益率%"], errors="coerce")
    m3m = pd.to_numeric(out["近3月收益率%"], errors="coerce")
    accel_raw = (m1w - m1m / 30 * 7) + (m1m - m3m / 91 * 30) * 0.5
    out["加速分"] = pct_score(accel_raw)
    out["是否短期加速"] = np.where(accel_raw > 0, "是", "否")

    one_year = pd.to_numeric(out["近1年收益率%"], errors="coerce")
    three_month = pd.to_numeric(out["近3月收益率%"], errors="coerce")
    drawdown = pd.to_numeric(out["近1年最大回撤%"], errors="coerce")
    out["未过热奖励"] = np.select([one_year < 80, one_year < 150], [100, 70], default=0)
    out["极热惩罚"] = 0.0
    out.loc[one_year > 150, "极热惩罚"] += float(penalties.get("one_year_hot_150", 8))
    out.loc[one_year > 250, "极热惩罚"] += float(penalties.get("one_year_hot_250", 15))
    out.loc[three_month > 100, "极热惩罚"] += float(penalties.get("three_month_hot_100", 8))
    out["回撤风险惩罚"] = 0.0
    out.loc[drawdown < -30, "回撤风险惩罚"] += float(penalties.get("drawdown_30", 5))
    out.loc[drawdown < -45, "回撤风险惩罚"] += float(penalties.get("drawdown_45", 10))
    heat_thresholds = config.get("scoring", {}).get("overheat_thresholds", {})
    out["热度提示"] = one_year.apply(lambda x: heat_label(x, heat_thresholds))

    score = pd.Series(0.0, index=out.index)
    for col, weight in weights.items():
        if col not in out.columns:
            out[col] = 0.0
        score += pd.to_numeric(out[col], errors="coerce").fillna(0) * float(weight)
    out["短期异动分"] = score - out["极热惩罚"] - out["回撤风险惩罚"]
    out = out.sort_values("短期异动分", ascending=False).reset_index(drop=True)
    out["短期异动排名"] = range(1, len(out) + 1)

    if previous_top50 is None:
        out["是否首次进入Top50"] = "暂无历史短期报告，无法判断"
    else:
        out["是否首次进入Top50"] = np.where((out["短期异动排名"] <= 50) & ~out["基金代码"].isin(previous_top50), "是", "否")
    if new_watch_codes is None:
        out["是否首次进入观察池"] = "暂无历史快照，无法判断新进"
    else:
        out["是否首次进入观察池"] = np.where(out["基金代码"].isin(new_watch_codes), "是", "否")
    return out


def latest_previous_short_report(current_out_dir: Path) -> Path | None:
    files = sorted(project_path("reports").rglob("短期异动雷达.xlsx"), key=lambda p: p.stat().st_mtime)
    files = [p for p in files if current_out_dir not in p.parents]
    return files[-1] if files else None


def previous_short_top50(current_out_dir: Path) -> set[str] | None:
    path = latest_previous_short_report(current_out_dir)
    if path is None:
        return None
    try:
        df = pd.read_excel(path, sheet_name="短期异动总榜", dtype={"基金代码": str})
        return set(df.head(50)["基金代码"].map(normalize_code))
    except Exception:
        return None


def latest_v1_scan_report() -> Path | None:
    files = [p for p in project_path("reports").rglob("基金雷达扫描结果.xlsx") if "time_machine" not in str(p)]
    files = sorted(files, key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def build_new_watchlist_sheet(scored: pd.DataFrame) -> tuple[pd.DataFrame, set[str] | None]:
    current = latest_v1_scan_report()
    if current is None:
        return pd.DataFrame([{"说明": "暂无当前V1报告，无法判断新进观察池"}]), None
    try:
        xls = pd.ExcelFile(current)
        sheet_map = {
            "当前实用观察池": "当前实用观察池Top10",
            "精选观察池": "精选观察池",
            "分散观察池": "分散观察池",
        }
        current_codes = []
        rows = []
        for label, sheet in sheet_map.items():
            if sheet not in xls.sheet_names:
                continue
            df = pd.read_excel(current, sheet_name=sheet, dtype={"基金代码": str})
            for _, row in df.iterrows():
                code = normalize_code(row.get("基金代码"))
                current_codes.append((label, code, row.get("基金名称", ""), row.get("最终分", pd.NA)))
        previous_snapshot_files = sorted(project_path("data", "snapshots").glob("*/snapshot.xlsx"), key=lambda p: p.stat().st_mtime)
        prev_codes: set[tuple[str, str]] = set()
        if previous_snapshot_files:
            prev = previous_snapshot_files[-1]
            for label, sheet in sheet_map.items():
                try:
                    df = pd.read_excel(prev, sheet_name=sheet, dtype={"基金代码": str})
                    prev_codes |= {(label, normalize_code(c)) for c in df.get("基金代码", [])}
                except Exception:
                    continue
        if not prev_codes:
            return pd.DataFrame([{"说明": "暂无历史快照，无法判断新进"}]), None
        new_codes = set()
        for label, code, name, score in current_codes:
            is_new = (label, code) not in prev_codes
            if is_new:
                new_codes.add(code)
            rows.append({"观察池类型": label, "基金代码": code, "基金名称": name, "最终分": score, "是否新进": "是" if is_new else "否"})
        return pd.DataFrame(rows), new_codes
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame([{"说明": f"观察池新进判断失败: {exc}"}]), None


def short_but_not_extreme(scored: pd.DataFrame, config: dict) -> pd.DataFrame:
    if scored.empty:
        return scored
    cfg = config.get("short_term_radar", {}).get("new_star", {})
    max_1y = float(cfg.get("max_one_year_return", 150))
    max_3m = float(cfg.get("max_three_month_return", 100))
    min_3m = float(cfg.get("min_three_month_return", 10))
    df = scored.copy()
    mask = (
        ((df["近1周排名"] <= 100) | (df["近1月排名"] <= 100))
        & (pd.to_numeric(df["近3月收益率%"], errors="coerce") >= min_3m)
        & (pd.to_numeric(df["近3月收益率%"], errors="coerce") <= max_3m)
        & (pd.to_numeric(df["近1年收益率%"], errors="coerce") <= max_1y)
    )
    out = df[mask].copy()
    out["观察提示"] = "短期强但未极热，可能刚冒头；仅作观察，不构成买卖建议"
    return out.sort_values("短期异动分", ascending=False).reset_index(drop=True)


def theme_movement(top_df: pd.DataFrame, loader: DataLoader, config: dict, logger: logging.Logger) -> tuple[pd.DataFrame, pd.DataFrame]:
    if top_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    codes = top_df["基金代码"].map(normalize_code).tolist()
    detail, failures = fetch_watch_holdings(codes, loader, logger)
    if detail.empty:
        return pd.DataFrame([{"说明": "短期异动榜持仓数据为空，无法做主题异动"}]), failures
    names = top_df[["基金代码", "基金名称"]].copy()
    detail = detail.merge(names, on="基金代码", how="left")
    tagged, _ = analyze_themes(detail, top_df["基金代码"].nunique(), load_theme_keywords())
    if tagged.empty:
        return pd.DataFrame([{"说明": "未识别到主题关键词"}]), failures
    rows = []
    for theme, g in tagged[tagged["主题"] != "未归类"].groupby("主题"):
        fund_count = g["基金代码"].nunique()
        total_weight = pd.to_numeric(g["持仓占比%"], errors="coerce").fillna(0).sum()
        stock_weight = g.groupby("股票名称")["持仓占比%"].sum().sort_values(ascending=False)
        fund_names = g[["基金代码", "基金名称"]].drop_duplicates()["基金名称"].dropna().astype(str).head(5).tolist()
        status = "扩散中" if fund_count >= 5 and total_weight >= 50 else ("短期异动" if fund_count >= 2 else "暂无明显证据")
        rows.append(
            {
                "主题名称": theme,
                "涉及基金数量": fund_count,
                "出现次数": len(g),
                "合计持仓占比": total_weight,
                "代表基金": "、".join(fund_names),
                "代表重仓股": "、".join(stock_weight.head(8).index.astype(str).tolist()),
                "主题状态": status,
            }
        )
    out = pd.DataFrame(rows).sort_values(["涉及基金数量", "合计持仓占比"], ascending=False).reset_index(drop=True)
    return out, failures


def verification_scan_dates(latest_date: str, max_horizon_days: int, periods: int) -> list[pd.Timestamp]:
    latest = pd.to_datetime(latest_date)
    end = latest - timedelta(days=max_horizon_days)
    return list(pd.date_range(end=end, periods=periods, freq="7D"))


def evaluate_group(
    group_name: str,
    selected: pd.DataFrame,
    universe: pd.DataFrame,
    navs: dict[str, pd.DataFrame],
    scan_date: pd.Timestamp,
    horizons: dict[str, int],
) -> list[dict[str, Any]]:
    rows = []
    if selected.empty:
        return rows
    for h_name, days in horizons.items():
        pool_returns = []
        for code in universe["基金代码"].map(normalize_code):
            nav = navs.get(code)
            if nav is None:
                continue
            fr = forward_return(nav, scan_date, days)
            if fr.get("是否完整验证"):
                pool_returns.append(fr["未来收益率%"])
        pool_mean = pd.Series(pool_returns, dtype="float64").dropna().mean()
        sel_returns = []
        sel_dd = []
        for code in selected["基金代码"].map(normalize_code):
            nav = navs.get(code)
            if nav is None:
                continue
            fr = forward_return(nav, scan_date, days)
            if fr.get("是否完整验证"):
                sel_returns.append(fr["未来收益率%"])
                sel_dd.append(future_max_drawdown(nav, scan_date, days))
        sel = pd.Series(sel_returns, dtype="float64").dropna()
        if sel.empty or pd.isna(pool_mean):
            continue
        rows.append(
            {
                "扫描日": pd.to_datetime(scan_date).strftime("%Y-%m-%d"),
                "验证对象": group_name,
                "horizon": h_name,
                "未来平均收益%": sel.mean(),
                "全候选池同期平均收益%": pool_mean,
                "平均超额%": sel.mean() - pool_mean,
                "超额是否为正": sel.mean() - pool_mean > 0,
                "胜率%": (sel > pool_mean).mean() * 100,
                "平均最大回撤%": pd.Series(sel_dd, dtype="float64").dropna().mean(),
                "最差最大回撤%": pd.Series(sel_dd, dtype="float64").dropna().min(),
                "样本数量": len(sel),
                "是否完整到期": True,
            }
        )
    return rows


def build_future_maps(
    universe: pd.DataFrame,
    navs: dict[str, pd.DataFrame],
    scan_date: pd.Timestamp,
    horizons: dict[str, int],
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    future_maps: dict[str, dict[str, float]] = {}
    pool_means: dict[str, float] = {}
    codes = universe["基金代码"].map(normalize_code).tolist()
    for h_name, days in horizons.items():
        ret_map: dict[str, float] = {}
        for code in codes:
            nav = navs.get(code)
            if nav is None:
                continue
            fr = forward_return(nav, scan_date, days)
            if fr.get("是否完整验证") and pd.notna(fr.get("未来收益率%")):
                ret_map[code] = float(fr["未来收益率%"])
        future_maps[h_name] = ret_map
        pool_means[h_name] = pd.Series(list(ret_map.values()), dtype="float64").dropna().mean()
    return future_maps, pool_means


def evaluate_group_fast(
    group_name: str,
    selected: pd.DataFrame,
    navs: dict[str, pd.DataFrame],
    scan_date: pd.Timestamp,
    horizons: dict[str, int],
    future_maps: dict[str, dict[str, float]],
    pool_means: dict[str, float],
) -> list[dict[str, Any]]:
    rows = []
    if selected.empty:
        return rows
    selected_codes = selected["基金代码"].map(normalize_code).tolist()
    for h_name, days in horizons.items():
        ret_map = future_maps.get(h_name, {})
        pool_mean = pool_means.get(h_name, np.nan)
        sel_returns = [ret_map[c] for c in selected_codes if c in ret_map]
        sel = pd.Series(sel_returns, dtype="float64").dropna()
        if sel.empty or pd.isna(pool_mean):
            continue
        dd_values = []
        for code in selected_codes:
            if code not in ret_map:
                continue
            nav = navs.get(code)
            if nav is not None:
                dd_values.append(future_max_drawdown(nav, scan_date, days))
        dd = pd.Series(dd_values, dtype="float64").dropna()
        rows.append(
            {
                "扫描日": pd.to_datetime(scan_date).strftime("%Y-%m-%d"),
                "验证对象": group_name,
                "horizon": h_name,
                "未来平均收益%": sel.mean(),
                "全候选池同期平均收益%": pool_mean,
                "平均超额%": sel.mean() - pool_mean,
                "超额是否为正": sel.mean() - pool_mean > 0,
                "胜率%": (sel > pool_mean).mean() * 100,
                "平均最大回撤%": dd.mean() if not dd.empty else pd.NA,
                "最差最大回撤%": dd.min() if not dd.empty else pd.NA,
                "样本数量": len(sel),
                "是否完整到期": True,
            }
        )
    return rows


def verify_short_signal(
    pool: pd.DataFrame,
    navs: dict[str, pd.DataFrame],
    config: dict,
    latest_date: str,
    horizons: dict[str, int],
    logger: logging.Logger,
    weights: dict[str, float] | None = None,
    feature_cache: dict[pd.Timestamp, tuple[pd.DataFrame, pd.DataFrame]] | None = None,
) -> pd.DataFrame:
    periods = int(config.get("short_term_radar", {}).get("verification_periods", 12))
    dates = verification_scan_dates(latest_date, max(horizons.values()), periods)
    all_rows = []
    for scan_date in dates:
        prev_date = scan_date - timedelta(days=7)
        if feature_cache is not None and scan_date in feature_cache:
            raw, prev_raw = feature_cache[scan_date]
        else:
            raw = raw_short_features(pool, navs, scan_date.strftime("%Y-%m-%d"), logger)
            prev_raw = raw_short_features(pool, navs, prev_date.strftime("%Y-%m-%d"), logger)
        if raw.empty:
            continue
        prev_scored = score_short_features(prev_raw, None, config, weights=weights) if not prev_raw.empty else pd.DataFrame()
        scored = score_short_features(raw, prev_scored, config, weights=weights)
        strong_not_hot = short_but_not_extreme(scored, config)
        future_maps, pool_means = build_future_maps(scored, navs, scan_date, horizons)
        groups: list[tuple[str, pd.DataFrame]] = []
        for n in (10, 20, 50):
            groups.append((f"短期异动总榜Top{n}", scored.head(n)))
            groups.append((f"近1周强势榜Top{n}", scored.sort_values("近1周收益率%", ascending=False).head(n)))
        for n in (10, 20):
            groups.append((f"短期强但未极热榜Top{n}", strong_not_hot.head(n)))
        new_strong = scored[(scored["短期异动排名"] <= 50) & (pd.to_numeric(scored["上期近1周排名"], errors="coerce") > 50)]
        groups.append(("本期新进强势榜", new_strong))
        for group_name, selected in groups:
            all_rows.extend(evaluate_group_fast(group_name, selected, navs, scan_date, horizons, future_maps, pool_means))
    detail = pd.DataFrame(all_rows)
    if detail.empty:
        return pd.DataFrame([{"说明": "样本不足，仅流程验证"}])
    summary = (
        detail.groupby(["验证对象", "horizon"], dropna=False)
        .agg(
            未来平均收益=("未来平均收益%", "mean"),
            全候选池同期平均收益=("全候选池同期平均收益%", "mean"),
            平均超额=("平均超额%", "mean"),
            超额为正比例=("超额是否为正", "mean"),
            平均胜率=("胜率%", "mean"),
            平均最大回撤=("平均最大回撤%", "mean"),
            最差最大回撤=("最差最大回撤%", "min"),
            样本数量=("样本数量", "sum"),
            回测期数=("扫描日", "nunique"),
        )
        .reset_index()
    )
    summary["超额为正比例"] = summary["超额为正比例"] * 100
    summary["是否完整到期"] = True
    summary["样本判断"] = np.where(summary["回测期数"] < 6, "样本不足，仅流程验证", "可作为短期信号复核样本")
    return summary


def parameter_sheet(config: dict, lookbacks: dict[str, int], horizons: dict[str, int]) -> pd.DataFrame:
    cfg = config.get("short_term_radar", {})
    rows = []
    for k, v in cfg.get("score_weights", {}).items():
        rows.append({"类别": "短期异动分权重", "参数": k, "值": v})
    for k, v in cfg.get("penalties", {}).items():
        rows.append({"类别": "惩罚项", "参数": k, "值": v})
    for k, v in lookbacks.items():
        rows.append({"类别": "lookback", "参数": k, "值": v})
    for k, v in horizons.items():
        rows.append({"类别": "verify_horizon", "参数": k, "值": v})
    rows.append({"类别": "说明", "参数": "用途", "值": "短期异动雷达只用于发现近期刚变强的观察线索，不构成买卖建议。"})
    return pd.DataFrame(rows)


def run_short_term_radar(
    config: dict[str, Any] | None = None,
    limit: int | None = None,
    top_n: int | None = None,
    lookback_text: str | None = None,
    verify_horizon_text: str | None = None,
    as_of: str | None = None,
    output_dir: str | Path | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    logger = logger or setup_logging(log_dir=config.get("project", {}).get("log_root", "data/reports"))
    loader = DataLoader(config, logger)
    as_of = as_of or today_str()
    top_n = int(top_n or config.get("short_term_radar", {}).get("top_n", 50))
    lookbacks = parse_lookbacks(lookback_text)
    horizons = parse_verify_horizons(verify_horizon_text)
    out_dir = ensure_dir(output_dir or project_path("reports", as_of))
    chart_dir = ensure_dir(out_dir / "charts")

    pool = build_candidate_pool(config, loader, logger, limit=limit)
    logger.info("short-term candidate pool: %s", len(pool))
    navs, nav_failures = load_navs(pool, loader, logger)
    raw = raw_short_features(pool, navs, as_of, logger)
    latest_date = raw["最新净值日期"].dropna().max() if not raw.empty else as_of
    prev_raw = raw_short_features(pool, navs, (pd.to_datetime(as_of) - timedelta(days=7)).strftime("%Y-%m-%d"), logger)
    prev_scored = score_short_features(prev_raw, None, config) if not prev_raw.empty else pd.DataFrame()
    prev_top50 = previous_short_top50(out_dir)
    new_watch_sheet, new_watch_codes = build_new_watchlist_sheet(raw)
    scored = score_short_features(raw, prev_scored, config, previous_top50=prev_top50, new_watch_codes=new_watch_codes)

    total = scored.copy()
    weekly = scored.sort_values("近1周收益率%", ascending=False).reset_index(drop=True)
    five_day = scored.sort_values("近5日收益率%", ascending=False).reset_index(drop=True)
    ten_day = scored.sort_values("近10日收益率%", ascending=False).reset_index(drop=True)
    one_month_new = short_but_not_extreme(scored, config).sort_values(["近1月收益率%", "短期异动分"], ascending=False).reset_index(drop=True)
    strong_not_hot = short_but_not_extreme(scored, config)
    new_strong = scored[scored["是否首次进入Top50"].eq("是")].reset_index(drop=True)
    theme_df, holding_failures = theme_movement(scored.head(top_n), loader, config, logger)
    verification = verify_short_signal(pool, navs, config, latest_date, horizons, logger)
    params = parameter_sheet(config, lookbacks, horizons)

    sheets = {
        "短期异动总榜": total,
        "近1周强势榜": weekly,
        "近5日异动榜": five_day,
        "近10日异动榜": ten_day,
        "近1月新星榜": one_month_new,
        "短期强但未极热榜": strong_not_hot,
        "本期新进强势榜": new_strong if not new_strong.empty else pd.DataFrame([{"说明": "暂无历史短期报告或本期无新进Top50"}]),
        "本期新进观察池": new_watch_sheet,
        "主题异动榜": theme_df,
        "短期异动验证": verification,
        "参数说明": params,
        "净值失败记录": nav_failures,
        "持仓失败记录": holding_failures,
    }
    excel_path = write_excel(out_dir / "短期异动雷达.xlsx", sheets)
    if not total.empty:
        bar_chart(total.head(30), "基金名称", "短期异动分", "短期异动总榜Top30", chart_dir / "短期异动总榜Top30.png", config=config)
        bar_chart(weekly.head(30), "基金名称", "近1周收益率%", "近1周强势榜Top30", chart_dir / "近1周强势榜Top30.png", config=config)
    write_markdown(
        out_dir / "短期异动雷达摘要.md",
        f"短期异动雷达摘要 {as_of}",
        {
            "定位": "短期异动雷达用于发现最近刚开始变强的基金和主题，不替代V1精选观察池，也不构成买卖建议。",
            "近1周最强基金": weekly[["基金代码", "基金名称", "近1周收益率%", "近1月收益率%", "近1年收益率%", "热度提示"]].head(10),
            "近1月新星基金": one_month_new[["基金代码", "基金名称", "近1月收益率%", "近3月收益率%", "近1年收益率%", "短期异动分", "观察提示"]].head(10) if not one_month_new.empty else pd.DataFrame(),
            "短期强但未极热": strong_not_hot[["基金代码", "基金名称", "近1周收益率%", "近1月收益率%", "近3月收益率%", "近1年收益率%", "短期异动分"]].head(10) if not strong_not_hot.empty else pd.DataFrame(),
            "主题异动": theme_df.head(10) if not theme_df.empty else "暂无主题证据。",
            "验证说明": "短期验证只使用历史扫描日前数据打分，未来收益只用于验证；未到期horizon不计算，样本不足时只标记流程验证。",
        },
    )
    return {
        "output_dir": out_dir,
        "excel_path": excel_path,
        "scored": scored,
        "weekly": weekly,
        "one_month_new": one_month_new,
        "strong_not_hot": strong_not_hot,
        "theme": theme_df,
        "verification": verification,
    }


def run_short_term_weight_search(
    config: dict[str, Any] | None = None,
    limit: int | None = None,
    verify_horizon_text: str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    logger = logger or setup_logging(log_dir=config.get("project", {}).get("log_root", "data/reports"))
    loader = DataLoader(config, logger)
    pool = build_candidate_pool(config, loader, logger, limit=limit)
    navs, nav_failures = load_navs(pool, loader, logger)
    latest = None
    for nav in navs.values():
        if nav is not None and not nav.empty:
            dt = pd.to_datetime(nav["净值日期"]).max()
            latest = dt if latest is None or dt > latest else latest
    latest_date = latest.strftime("%Y-%m-%d") if latest is not None else today_str()
    horizons = parse_verify_horizons(verify_horizon_text)
    periods = int(config.get("short_term_radar", {}).get("verification_periods", 12))
    dates = verification_scan_dates(latest_date, max(horizons.values()), periods)
    feature_cache: dict[pd.Timestamp, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for scan_date in dates:
        prev_date = scan_date - timedelta(days=7)
        feature_cache[scan_date] = (
            raw_short_features(pool, navs, scan_date.strftime("%Y-%m-%d"), logger),
            raw_short_features(pool, navs, prev_date.strftime("%Y-%m-%d"), logger),
        )
    rows = []
    for scheme_name, weights in SHORT_TERM_SCHEMES.items():
        res = verify_short_signal(pool, navs, config, latest_date, horizons, logger, weights=weights, feature_cache=feature_cache)
        if res.empty or "验证对象" not in res.columns:
            continue
        tmp = res.copy()
        tmp["方案"] = scheme_name
        rows.append(tmp)
    result = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame([{"说明": "样本不足，仅流程验证"}])
    if "平均超额" in result.columns:
        rank = (
            result.groupby("方案", dropna=False)
            .agg(平均超额=("平均超额", "mean"), 平均胜率=("平均胜率", "mean"), 平均期数=("回测期数", "mean"))
            .reset_index()
            .sort_values("平均超额", ascending=False)
        )
        rank["样本判断"] = np.where(rank["平均期数"] < 6, "样本不足，仅流程验证", "可作为短期规则复核样本")
    else:
        rank = pd.DataFrame()
    out_dir = ensure_dir(project_path("reports", "short_term_weight_search"))
    excel_path = write_excel(out_dir / "短期权重搜索结果.xlsx", {"方案排名": rank, "明细": result, "净值失败记录": nav_failures})
    return {"output_dir": out_dir, "excel_path": excel_path, "rank": rank, "detail": result}
