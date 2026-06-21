from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .data_loader import DataLoader
from .diversification import build_diversified_watchlist
from .metrics import forward_return, future_max_drawdown
from .pipeline import market_scan
from .report import bar_chart, write_excel, write_markdown
from .utils import ensure_dir, load_config, normalize_code, project_path, setup_logging


def selection_reason(row: pd.Series) -> str:
    parts = []
    for col in ["近1月收益率%", "近3月收益率%", "近6月收益率%", "近1年收益率%"]:
        val = row.get(col)
        if pd.notna(val):
            parts.append(f"{col.replace('收益率%', '')}{float(val):.1f}%")
    dd = row.get("近1年最大回撤%")
    heat = row.get("热度提示", "")
    risk = row.get("风险提示", "")
    if pd.notna(dd):
        parts.append(f"近1年最大回撤{float(dd):.1f}%")
    if heat:
        parts.append(f"热度={heat}")
    if risk:
        parts.append(str(risk))
    return "；".join(parts)


def benchmark_returns(loader: DataLoader, as_of: str, horizons: dict[str, int], logger: logging.Logger) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        nav = loader.fetch_index_nav("sh000300")
        for name, days in horizons.items():
            fr = forward_return(nav, as_of, days)
            out[f"沪深300未来{name}收益%"] = fr["未来收益率%"]
            out[f"沪深300未来{name}是否完整验证"] = fr["是否完整验证"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("benchmark unavailable: %s", exc)
        for name in horizons:
            out[f"沪深300未来{name}收益%"] = pd.NA
            out[f"沪深300未来{name}是否完整验证"] = False
    return out


def validate_future(
    as_of: str,
    selected: pd.DataFrame,
    universe: pd.DataFrame,
    loader: DataLoader,
    horizons: dict[str, int],
    logger: logging.Logger,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    universe_returns: dict[str, list[float]] = {name: [] for name in horizons}
    universe_meta: dict[str, list[dict[str, Any]]] = {name: [] for name in horizons}
    universe_codes = universe["基金代码"].map(normalize_code).tolist() if not universe.empty else []
    nav_cache: dict[str, pd.DataFrame] = {}
    for code in set(universe_codes + selected["基金代码"].map(normalize_code).tolist()):
        try:
            nav_cache[code] = loader.fetch_nav(code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("time machine future nav failed %s: %s", code, exc)
    for code in universe_codes:
        nav = nav_cache.get(code)
        if nav is None:
            continue
        for name, days in horizons.items():
            fr = forward_return(nav, as_of, days)
            if fr["是否完整验证"]:
                universe_returns[name].append(fr["未来收益率%"])
            universe_meta[name].append(fr)
    for _, fund in selected.iterrows():
        code = normalize_code(fund["基金代码"])
        nav = nav_cache.get(code)
        row = {
            "基金代码": code,
            "基金名称": fund.get("基金名称", ""),
            "选择分": fund.get("最终分"),
            "选择理由": selection_reason(fund),
        }
        if nav is not None:
            for name, days in horizons.items():
                fr = forward_return(nav, as_of, days)
                row[f"未来{name}收益%"] = fr["未来收益率%"]
                row[f"未来{name}目标验证日期"] = fr["目标验证日期"]
                row[f"未来{name}最新可用净值日期"] = fr["最新可用净值日期"]
                row[f"未来{name}horizon是否到期"] = fr["horizon是否到期"]
                row[f"未来{name}实际卖出净值日期"] = fr["卖出净值日期"]
                row[f"未来{name}是否完整验证"] = fr["是否完整验证"]
                row[f"未来{name}验证状态"] = fr["验证状态"]
                row[f"未来{name}最大回撤%"] = future_max_drawdown(nav, as_of, days)
                pool_mean = pd.Series(universe_returns[name], dtype="float64").dropna().mean()
                row[f"相对全候选{name}超额%"] = row[f"未来{name}收益%"] - pool_mean if pd.notna(pool_mean) else pd.NA
        rows.append(row)
    fund_future = pd.DataFrame(rows)
    bench = benchmark_returns(loader, as_of, horizons, logger)
    summary = {"模拟日期": as_of, "组合基金数": len(selected)}
    for name in horizons:
        ret_col = f"未来{name}收益%"
        complete_col = f"未来{name}是否完整验证"
        complete_mask = fund_future.get(complete_col, pd.Series(False, index=fund_future.index)).fillna(False).astype(bool) if not fund_future.empty else pd.Series(dtype=bool)
        completed = fund_future[complete_mask] if not fund_future.empty else fund_future
        pool_mean = pd.Series(universe_returns[name], dtype="float64").dropna().mean()
        combo = pd.to_numeric(completed.get(ret_col), errors="coerce").mean() if not completed.empty else pd.NA
        target_dates = completed.get(f"未来{name}目标验证日期", pd.Series(dtype=object)).dropna().unique().tolist()
        sell_dates = completed.get(f"未来{name}实际卖出净值日期", pd.Series(dtype=object)).dropna().unique().tolist()
        latest_dates = fund_future.get(f"未来{name}最新可用净值日期", pd.Series(dtype=object)).dropna().unique().tolist() if not fund_future.empty else []
        horizon_due = bool(complete_mask.any()) and len(completed) == len(selected)
        complete_verify = horizon_due and pd.notna(pool_mean)
        summary[f"组合未来{name}收益%"] = combo
        summary[f"全候选平均未来{name}收益%"] = pool_mean
        summary[f"相对全候选{name}超额%"] = combo - pool_mean if pd.notna(combo) and pd.notna(pool_mean) else pd.NA
        summary[f"沪深300未来{name}收益%"] = bench.get(f"沪深300未来{name}收益%")
        summary[f"相对沪深300{name}超额%"] = combo - bench.get(f"沪深300未来{name}收益%") if pd.notna(combo) and pd.notna(bench.get(f"沪深300未来{name}收益%")) else pd.NA
        summary[f"{name}最新可用净值日期"] = max(latest_dates) if latest_dates else None
        summary[f"{name}目标验证日期"] = target_dates[0] if target_dates else (universe_meta[name][0].get("目标验证日期") if universe_meta[name] else None)
        summary[f"{name}horizon是否到期"] = horizon_due
        summary[f"{name}实际卖出净值日期"] = " / ".join(sorted(map(str, sell_dates))) if sell_dates else None
        summary[f"{name}是否完整验证"] = complete_verify
        summary[f"{name}完整验证基金数"] = int(complete_mask.sum()) if not fund_future.empty else 0
        summary[f"{name}全候选完整验证数量"] = len(universe_returns[name])
    horizon_rows = []
    for name in horizons:
        horizon_rows.append(
            {
                "模拟日期": as_of,
                "horizon": name,
                "最新可用净值日期": summary.get(f"{name}最新可用净值日期"),
                "目标验证日期": summary.get(f"{name}目标验证日期"),
                "horizon是否到期": summary.get(f"{name}horizon是否到期"),
                "实际卖出净值日期": summary.get(f"{name}实际卖出净值日期"),
                "是否完整验证": summary.get(f"{name}是否完整验证"),
                "完整验证基金数": summary.get(f"{name}完整验证基金数"),
                "全候选完整验证数量": summary.get(f"{name}全候选完整验证数量"),
                "组合未来收益%": summary.get(f"组合未来{name}收益%"),
                "全候选平均未来收益%": summary.get(f"全候选平均未来{name}收益%"),
                "相对全候选超额%": summary.get(f"相对全候选{name}超额%"),
                "沪深300未来收益%": summary.get(f"沪深300未来{name}收益%"),
                "相对沪深300超额%": summary.get(f"相对沪深300{name}超额%"),
            }
        )
    return fund_future, pd.DataFrame([summary]), pd.DataFrame(horizon_rows)


def run_time_machine(
    as_of: str,
    config: dict[str, Any] | None = None,
    horizons: dict[str, int] | None = None,
    top_n: int | None = None,
    limit: int | None = None,
    output_dir: str | Path | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    logger = logger or setup_logging(log_dir=config.get("project", {}).get("log_root", "data/reports"))
    horizons = horizons or config.get("time_machine", {}).get("horizons", {"1月": 30, "3月": 91, "6月": 182, "12月": 365})
    top_n = int(top_n or config.get("scoring", {}).get("top_n", {}).get("practical", 10))
    out_dir = ensure_dir(output_dir or project_path("reports", "time_machine", as_of))
    scan = market_scan(config=config, as_of=as_of, output_dir=out_dir, limit=limit, with_holdings=True, logger=logger)
    scored = scan["scored"]
    selected = scored.head(top_n).reset_index(drop=True) if not scored.empty else scored
    loader = DataLoader(config, logger)
    div_cfg = config.get("scoring", {}).get("diversification", {})
    diversified = build_diversified_watchlist(
        scored,
        loader,
        target_n=top_n,
        source_top_n=max(int(div_cfg.get("source_top_n", top_n)), top_n),
        max_per_company=int(div_cfg.get("max_per_company", 2)),
        max_per_manager=int(div_cfg.get("max_per_manager", 2)),
        logger=logger,
    ) if not scored.empty else pd.DataFrame()
    fund_future, portfolio_summary, horizon_status = validate_future(as_of, selected, scored, loader, horizons, logger)
    theme_stats = scan.get("theme_stats", pd.DataFrame())
    theme_validation = theme_stats.copy()
    if not theme_validation.empty:
        matured = horizon_status[horizon_status["是否完整验证"].fillna(False)] if not horizon_status.empty else pd.DataFrame()
        mid = matured[matured["horizon"].isin(["3月", "6月", "12月"])] if not matured.empty else pd.DataFrame()
        avg_excess = pd.to_numeric(mid.get("相对全候选超额%"), errors="coerce").mean() if not mid.empty else pd.NA
        theme_validation["组合后验表现支持"] = "支持" if pd.notna(avg_excess) and avg_excess > 0 else "不支持/样本不足"
        theme_validation["后验验证口径"] = "这不是未来持仓验证，也不是主题本身的独立收益验证；仅表示当时识别出该主题的精选组合，在后续已到期窗口中是否跑赢全候选池或基准。"
    sheets = {
        "历史时点观察池": scored,
        "历史时点精选基金": selected,
        "历史时点分散观察池": diversified,
        "模拟组合验证": fund_future,
        "组合汇总": portfolio_summary,
        "horizon验证状态": horizon_status,
        "主线验证": theme_validation,
        "重仓明细": scan.get("holding_detail", pd.DataFrame()),
        "主题统计": theme_stats,
    }
    excel_path = write_excel(out_dir / "历史时点观察池.xlsx", sheets)
    if not fund_future.empty:
        for name in horizons:
            col = f"未来{name}收益%"
            if col in fund_future:
                bar_chart(fund_future.sort_values(col, ascending=False), "基金名称", col, f"{as_of}精选基金未来{name}收益", out_dir / "charts" / f"未来{name}收益.png", top_n=top_n, config=config)
    conclusion = build_time_machine_conclusion(as_of, selected, fund_future, portfolio_summary, theme_stats)
    write_markdown(
        out_dir / "历史时点分析报告.md",
        f"历史时点模拟报告 {as_of}",
        {
            "当时识别出的主线": theme_stats.head(10) if not theme_stats.empty else "未取得可用持仓主题数据，主线判断降级为净值趋势信号。",
            "当时模拟观察组合": selected[["基金代码", "基金名称", "最终分", "近1月收益率%", "近3月收益率%", "近6月收益率%", "近1年收益率%", "热度提示", "风险提示"]].head(top_n) if not selected.empty else pd.DataFrame(),
            "当时分散观察池": diversified[["分散池排名", "基金代码", "基金名称", "基金公司", "基金经理", "最终分", "分散池说明"]] if not diversified.empty else pd.DataFrame(),
            "分散池说明": f"分散观察池目标 {top_n} 只，实际 {len(diversified)} 只。" + ("因分散约束未填满。" if len(diversified) < top_n else ""),
            "选择理由": fund_future[["基金代码", "基金名称", "选择理由"]] if not fund_future.empty else pd.DataFrame(),
            "后验验证结果": portfolio_summary,
            "horizon到期状态": horizon_status,
            "判断质量总结": conclusion,
            "严格性说明": "净值类信号严格按 as_of 截断。持仓主题信号依赖公开持仓披露和 AKShare 返回字段；组合后验表现支持不是未来持仓验证，也不是主题本身的独立收益验证，只能作为后验支持信号。",
        },
    )
    return {"output_dir": out_dir, "excel_path": excel_path, "selected": selected, "diversified": diversified, "fund_future": fund_future, "portfolio_summary": portfolio_summary, "horizon_status": horizon_status, "theme_stats": theme_stats}


def build_time_machine_conclusion(as_of: str, selected: pd.DataFrame, future: pd.DataFrame, summary: pd.DataFrame, theme_stats: pd.DataFrame) -> str:
    lines = []
    if not theme_stats.empty:
        top_theme = theme_stats.iloc[0]
        lines.append(f"{as_of} 当时最强主题线索为 {top_theme.get('主题')}，主线判断为 {top_theme.get('主线判断')}，状态为 {top_theme.get('主线状态')}。")
    else:
        lines.append(f"{as_of} 当时未形成可靠持仓主题判断。")
    if not summary.empty:
        s = summary.iloc[0]
        checks = []
        for col in summary.columns:
            if col.startswith("相对全候选") and col.endswith("超额%") and pd.notna(s[col]):
                checks.append(f"{col.replace('相对全候选', '')}: {float(s[col]):.2f}%")
        if checks:
            lines.append("组合相对全候选池超额收益：" + "，".join(checks) + "。")
    if future.empty:
        lines.append("未来验证数据不足，不能判断信号质量。")
    else:
        one_cols = [c for c in future.columns if c.startswith("相对全候选") and c.endswith("超额%")]
        positives = sum(pd.to_numeric(future[c], errors="coerce").mean() > 0 for c in one_cols)
        lines.append(f"在 {len(one_cols)} 个验证窗口中，组合平均超额为正的窗口数为 {positives}。这只能说明历史时点信号是否有观察价值，不代表可预测未来收益。")
    return "\n\n".join(lines)


def run_time_machine_batch(
    dates: list[str],
    config: dict[str, Any] | None = None,
    top_n: int | None = None,
    limit: int | None = None,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    config = config or load_config()
    logger = logger or setup_logging(log_dir=config.get("project", {}).get("log_root", "data/reports"))
    rows = []
    long_rows = []
    for as_of in dates:
        result = run_time_machine(as_of, config=config, top_n=top_n, limit=limit, logger=logger)
        s = result["portfolio_summary"].iloc[0].to_dict() if not result["portfolio_summary"].empty else {"模拟日期": as_of}
        s["报告目录"] = str(result["output_dir"])
        rows.append(s)
        if not result.get("horizon_status", pd.DataFrame()).empty:
            h = result["horizon_status"].copy()
            h["报告目录"] = str(result["output_dir"])
            long_rows.append(h)
    out = pd.DataFrame(rows)
    long_df = pd.concat(long_rows, ignore_index=True) if long_rows else pd.DataFrame()
    batch_dir = ensure_dir(project_path("reports", "time_machine"))
    write_excel(batch_dir / "时间机器批量汇总.xlsx", {"批量汇总": out, "horizon长表": long_df})
    return out
