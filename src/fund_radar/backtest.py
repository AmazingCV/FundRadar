from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .data_loader import DataLoader
from .fund_filter import dedupe_ac
from .metrics import compute_feature_row, forward_return
from .pipeline import build_candidate_pool
from .report import bar_chart, line_chart, write_excel, write_markdown
from .scoring import score_funds
from .utils import ensure_dir, load_config, normalize_code, project_path, setup_logging, today_str


def month_end_dates(start: str, end: str) -> list[pd.Timestamp]:
    dates = pd.date_range(start=start, end=end, freq="ME")
    return list(dates)


def load_nav_cache(pool: pd.DataFrame, loader: DataLoader, logger: logging.Logger, min_days: int = 120) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    navs: dict[str, pd.DataFrame] = {}
    failures = []
    for _, fund in pool.iterrows():
        code = normalize_code(fund["基金代码"])
        try:
            nav = loader.fetch_nav(code)
            if len(nav) < min_days:
                raise RuntimeError(f"历史净值天数不足: {len(nav)}")
            navs[code] = nav
        except Exception as exc:  # noqa: BLE001
            logger.warning("backtest nav failed %s: %s", code, exc)
            failures.append({"基金代码": code, "基金名称": fund.get("基金名称", ""), "错误": str(exc)})
    return navs, pd.DataFrame(failures)


def features_at_date(
    scan_date: str | datetime,
    pool: pd.DataFrame,
    navs: dict[str, pd.DataFrame],
    config: dict,
    use_overheat_penalty: bool | None = None,
    dedupe: bool = True,
) -> pd.DataFrame:
    periods = {k: v for k, v in config.get("periods", {}).items() if k != "近3年"}
    rows = []
    for _, fund in pool.iterrows():
        code = normalize_code(fund["基金代码"])
        nav = navs.get(code)
        if nav is None:
            continue
        try:
            row = compute_feature_row(nav, scan_date, periods)
            row.update({"基金代码": code, "基金名称": fund.get("基金名称", ""), "基金类型": fund.get("基金类型", "")})
            rows.append(row)
        except Exception:
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    scored = score_funds(df, config, use_overheat_penalty=use_overheat_penalty)
    if dedupe:
        scored = dedupe_ac(scored, "最终分")
    return scored


def evaluate_selection(
    scan_date: str | datetime,
    selected: pd.DataFrame,
    universe: pd.DataFrame,
    navs: dict[str, pd.DataFrame],
    horizons: dict[str, int],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    for _, fund in selected.iterrows():
        code = normalize_code(fund["基金代码"])
        nav = navs.get(code)
        row = {"扫描日": pd.to_datetime(scan_date).strftime("%Y-%m-%d"), "基金代码": code, "基金名称": fund.get("基金名称", ""), "选择分": fund.get("最终分")}
        if nav is not None:
            for name, days in horizons.items():
                fr = forward_return(nav, scan_date, days)
                row[f"未来{name}收益%"] = fr["未来收益率%"]
                row[f"未来{name}买入日"] = fr.get("买入净值日期")
                row[f"未来{name}卖出日"] = fr.get("卖出净值日期")
                row[f"未来{name}目标验证日期"] = fr.get("目标验证日期")
                row[f"未来{name}是否完整验证"] = fr.get("是否完整验证")
                row[f"未来{name}验证状态"] = fr.get("验证状态")
        rows.append(row)
    selected_future = pd.DataFrame(rows)

    summary: dict[str, Any] = {"扫描日": pd.to_datetime(scan_date).strftime("%Y-%m-%d"), "选中数量": len(selected)}
    for name, days in horizons.items():
        universe_returns = []
        for code in universe["基金代码"].map(normalize_code):
            nav = navs.get(code)
            if nav is None:
                continue
            fr = forward_return(nav, scan_date, days)
            if fr.get("是否完整验证"):
                universe_returns.append(fr["未来收益率%"])
        top_col = f"未来{name}收益%"
        complete_col = f"未来{name}是否完整验证"
        complete_mask = selected_future.get(complete_col, pd.Series(False, index=selected_future.index)).fillna(False).astype(bool)
        complete_future = selected_future[complete_mask]
        top_mean = pd.to_numeric(complete_future.get(top_col), errors="coerce").mean() if not complete_future.empty else pd.NA
        uni = pd.Series(universe_returns, dtype="float64").dropna()
        uni_mean = uni.mean()
        summary[f"TopN平均未来{name}收益%"] = top_mean
        summary[f"全候选平均未来{name}收益%"] = uni_mean
        summary[f"平均超额{name}%"] = top_mean - uni_mean if pd.notna(top_mean) and pd.notna(uni_mean) else pd.NA
        summary[f"TopN胜率{name}%"] = (pd.to_numeric(complete_future.get(top_col), errors="coerce") > uni_mean).mean() * 100 if pd.notna(uni_mean) and not complete_future.empty else pd.NA
        summary[f"TopN完整验证数量{name}"] = int(complete_mask.sum())
        summary[f"全候选完整验证数量{name}"] = len(uni)
    return selected_future, summary


def run_backtest(
    config: dict[str, Any] | None = None,
    start: str | None = None,
    end: str | None = None,
    top_n: int | None = None,
    limit: int | None = None,
    output_dir: str | Path | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    logger = logger or setup_logging(log_dir=config.get("project", {}).get("log_root", "data/reports"))
    loader = DataLoader(config, logger)
    bt_conf = config.get("backtest", {})
    start = start or bt_conf.get("start", "2023-01-01")
    end = end or bt_conf.get("end") or today_str()
    top_n = int(top_n or bt_conf.get("top_n", 10))
    horizons = bt_conf.get("horizons", {"3月": 91, "6月": 182, "12月": 365})
    out_dir = ensure_dir(output_dir or project_path("reports", "backtest", f"{start}_{end}"))
    pool = build_candidate_pool(config, loader, logger, limit=limit)
    navs, nav_failures = load_nav_cache(pool, loader, logger, int(config.get("data", {}).get("min_history_days", 120)))
    scan_dates = month_end_dates(start, end)
    selected_rows = []
    summary_rows = []
    for scan_date in scan_dates:
        scored = features_at_date(scan_date, pool, navs, config, dedupe=config.get("fund_filter", {}).get("dedupe_ac", True))
        if scored.empty:
            continue
        selected = scored.head(top_n)
        selected_future, summary = evaluate_selection(scan_date, selected, scored, navs, horizons)
        selected_rows.append(selected_future)
        summary_rows.append(summary)
    selected_df = pd.concat(selected_rows, ignore_index=True) if selected_rows else pd.DataFrame()
    summary_df = pd.DataFrame(summary_rows)
    overall = summarize_backtest(summary_df, horizons)
    sheets = {"总体统计": overall, "每期汇总": summary_df, "每期选中基金": selected_df, "净值失败记录": nav_failures}
    excel_path = write_excel(out_dir / "基金雷达历史回测结果.xlsx", sheets)
    if not summary_df.empty:
        for name in horizons:
            col = f"平均超额{name}%"
            if col in summary_df:
                line_chart(summary_df, "扫描日", [col], f"Top{top_n} {name}平均超额收益", out_dir / "charts" / f"{name}超额收益.png", config)
    write_markdown(
        out_dir / "回测摘要.md",
        "基金雷达历史回测摘要",
        {
            "区间": f"{start} 至 {end}，Top{top_n}，扫描期数 {len(summary_df)}。",
            "总体统计": overall,
            "方法说明": "每个扫描日只使用当日及以前净值计算信号；未来收益买入用扫描日后第一个可用净值，卖出用目标日前最近可用净值。当前公开接口无法完全还原历史基金存续池，仍有幸存者偏差。",
        },
    )
    return {"output_dir": out_dir, "excel_path": excel_path, "overall": overall, "summary": summary_df, "selected": selected_df, "pool": pool}


def summarize_backtest(summary_df: pd.DataFrame, horizons: dict[str, int]) -> pd.DataFrame:
    rows = []
    for name in horizons:
        excess_col = f"平均超额{name}%"
        top_col = f"TopN平均未来{name}收益%"
        pool_col = f"全候选平均未来{name}收益%"
        if excess_col not in summary_df:
            continue
        excess = pd.to_numeric(summary_df[excess_col], errors="coerce").dropna()
        rows.append(
            {
                "观察周期": name,
                "回测期数": len(excess),
                "TopN平均未来收益%": pd.to_numeric(summary_df.get(top_col), errors="coerce").mean(),
                "全候选平均未来收益%": pd.to_numeric(summary_df.get(pool_col), errors="coerce").mean(),
                "平均超额收益%": excess.mean(),
                "超额为正期数占比%": (excess > 0).mean() * 100 if len(excess) else pd.NA,
                "最差一期超额%": excess.min() if len(excess) else pd.NA,
                "最好一期超额%": excess.max() if len(excess) else pd.NA,
            }
        )
    return pd.DataFrame(rows)
