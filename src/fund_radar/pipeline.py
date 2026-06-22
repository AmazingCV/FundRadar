from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .data_loader import DataLoader
from .diversification import build_diversified_watchlist
from .fund_filter import active_equity_filter, dedupe_ac
from .holdings import fetch_watch_holdings, holding_stock_stats
from .metrics import compute_feature_row
from .report import bar_chart, write_excel, write_markdown
from .scoring import build_rankings, score_funds
from .theme_analysis import analyze_themes, compare_theme_stats, load_theme_keywords
from .utils import ensure_dir, load_config, load_yaml, month_dir, normalize_code, project_path, setup_logging, today_str


def load_watchlist(path: str = "config/fund_list.yaml") -> pd.DataFrame:
    data = load_yaml(path)
    rows = data.get("watchlist", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["基金代码", "基金名称", "基金类型"])
    df = df.rename(columns={"code": "基金代码", "name": "基金名称"})
    df["基金代码"] = df["基金代码"].map(normalize_code)
    if "基金名称" not in df:
        df["基金名称"] = ""
    df["基金类型"] = "观察池强制加入"
    return df[["基金代码", "基金名称", "基金类型"]]


def enrich_fund_names(df: pd.DataFrame, loader: DataLoader, logger: logging.Logger | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    out["基金代码"] = out["基金代码"].map(normalize_code)
    if "基金名称" not in out.columns:
        out["基金名称"] = ""
    if "基金类型" not in out.columns:
        out["基金类型"] = ""
    try:
        base = loader.fetch_fund_list()[["基金代码", "基金名称", "基金类型"]].rename(
            columns={"基金名称": "_基础基金名称", "基金类型": "_基础基金类型"}
        )
        out = out.merge(base, on="基金代码", how="left")
        out["基金名称"] = out["基金名称"].fillna("").astype(str)
        out["_基础基金名称"] = out["_基础基金名称"].fillna("").astype(str)
        out["基金名称"] = out["基金名称"].where(out["基金名称"].str.strip().ne(""), out["_基础基金名称"])
        out["基金类型"] = out["基金类型"].fillna("").astype(str)
        out["_基础基金类型"] = out["_基础基金类型"].fillna("").astype(str)
        out["基金类型"] = out["基金类型"].where(out["基金类型"].str.strip().ne(""), out["_基础基金类型"])
        out = out.drop(columns=["_基础基金名称", "_基础基金类型"])
    except Exception as exc:  # noqa: BLE001
        if logger:
            logger.warning("fund name enrich failed: %s", exc)
    return out


def stage_return_compare(
    codes: list[str],
    config: dict[str, Any] | None = None,
    as_of: str | None = None,
    output_dir: str | Path | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    logger = logger or setup_logging(log_dir=config.get("project", {}).get("log_root", "data/reports"))
    loader = DataLoader(config, logger)
    periods = config.get("periods", {})
    as_of = as_of or today_str()
    out_dir = ensure_dir(output_dir or project_path("reports", "stage_return_compare", as_of))
    chart_dir = ensure_dir(out_dir / "charts")
    fund_list = loader.fetch_fund_list()
    name_map = dict(zip(fund_list["基金代码"], fund_list["基金名称"]))
    rows = []
    failures = []
    for code in [normalize_code(c) for c in codes]:
        try:
            nav = loader.fetch_nav(code)
            row = compute_feature_row(nav, as_of, periods)
            row.update({"基金代码": code, "基金名称": name_map.get(code, "")})
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            logger.warning("stage compare failed %s: %s", code, exc)
            failures.append({"基金代码": code, "错误": str(exc)})
    result = pd.DataFrame(rows)
    sheets: dict[str, pd.DataFrame] = {"汇总": result, "失败记录": pd.DataFrame(failures)}
    rankings = {}
    for name in periods:
        col = f"{name}收益率%"
        rank = result.sort_values(col, ascending=False).reset_index(drop=True) if col in result.columns else pd.DataFrame()
        rankings[name] = rank
        sheets[f"{name}排序"] = rank
        if not rank.empty:
            bar_chart(rank, "基金名称", col, f"{name}收益表现", chart_dir / f"{name}收益表现.png", top_n=30, config=config)
    excel_path = write_excel(out_dir / "阶段收益对比.xlsx", sheets)
    write_markdown(
        out_dir / "分析摘要.md",
        "阶段收益对比摘要",
        {
            "运行日期": f"as_of={as_of}，成功 {len(result)} 只，失败 {len(failures)} 只。",
            "近1月Top": rankings.get("近1月", pd.DataFrame()).head(10) if rankings else pd.DataFrame(),
            "风险说明": "本报告只展示历史阶段收益，不构成基金推荐；需要结合回撤、主题拥挤度和后续跟踪验证。",
        },
    )
    return {"output_dir": out_dir, "excel_path": excel_path, "result": result, "rankings": rankings, "failures": pd.DataFrame(failures)}


def build_candidate_pool(config: dict, loader: DataLoader, logger: logging.Logger | None = None, limit: int | None = None) -> pd.DataFrame:
    mode = config.get("data", {}).get("market_mode", "top_ranked")
    candidate_limit = int(limit or config.get("data", {}).get("candidate_limit", 800))
    if mode == "full":
        base = loader.fetch_fund_list()
    else:
        try:
            base = loader.fetch_rank_table()
        except Exception as exc:  # noqa: BLE001
            if logger:
                logger.warning("rank table unavailable, fallback fund list: %s", exc)
            base = loader.fetch_fund_list()
    base = enrich_fund_names(base, loader, logger)
    pool = active_equity_filter(base, config)
    if mode != "full" and candidate_limit:
        pool = pool.head(candidate_limit).copy()
    return pool.drop_duplicates("基金代码").reset_index(drop=True)


def compute_feature_table(
    pool: pd.DataFrame,
    loader: DataLoader,
    config: dict,
    as_of: str,
    logger: logging.Logger,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    periods = config.get("periods", {})
    rows = []
    failures = []
    min_days = int(config.get("data", {}).get("min_history_days", 120))
    iterator = pool.iterrows()
    try:
        from tqdm import tqdm

        iterator = tqdm(iterator, total=len(pool), desc="market_scan nav", unit="fund")
    except Exception:
        logger.info("market_scan nav progress: %s funds", len(pool))
    for _, fund in iterator:
        code = normalize_code(fund["基金代码"])
        try:
            nav = loader.fetch_nav(code)
            row = compute_feature_row(nav, as_of, periods)
            if int(row.get("净值样本数", 0)) < min_days:
                raise RuntimeError(f"历史净值天数不足: {row.get('净值样本数')}")
            row.update({"基金代码": code, "基金名称": fund.get("基金名称", ""), "基金类型": fund.get("基金类型", "")})
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            failures.append({"基金代码": code, "基金名称": fund.get("基金名称", ""), "错误": str(exc)})
            logger.warning("scan failed %s %s", code, exc)
    return pd.DataFrame(rows), pd.DataFrame(failures)


def market_scan(
    config: dict[str, Any] | None = None,
    as_of: str | None = None,
    output_dir: str | Path | None = None,
    limit: int | None = None,
    with_holdings: bool = True,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    logger = logger or setup_logging(log_dir=config.get("project", {}).get("log_root", "data/reports"))
    loader = DataLoader(config, logger)
    as_of = as_of or today_str()
    out_dir = ensure_dir(output_dir or project_path("reports", "v1_market", as_of))
    chart_dir = ensure_dir(out_dir / "charts")
    pool = build_candidate_pool(config, loader, logger, limit=limit)
    logger.info("natural candidate pool: %s", len(pool))
    feature_df, failures = compute_feature_table(pool, loader, config, as_of, logger)
    scored = score_funds(feature_df, config) if not feature_df.empty else feature_df
    if config.get("fund_filter", {}).get("dedupe_ac", True) and not scored.empty:
        scored = dedupe_ac(scored, "最终分")
    top_cfg = config.get("scoring", {}).get("top_n", {})
    div_cfg = config.get("scoring", {}).get("diversification", {})
    practical_n = int(top_cfg.get("practical", 10))
    selected_n = int(top_cfg.get("selected", 5))
    diversified_n = int(top_cfg.get("diversified", selected_n))
    practical = scored.head(practical_n).reset_index(drop=True) if not scored.empty else scored
    selected = scored.head(selected_n).reset_index(drop=True) if not scored.empty else scored
    diversified = build_diversified_watchlist(
        scored,
        loader,
        target_n=diversified_n,
        source_top_n=int(div_cfg.get("source_top_n", practical_n)),
        max_per_company=int(div_cfg.get("max_per_company", 2)),
        max_per_manager=int(div_cfg.get("max_per_manager", 2)),
        logger=logger,
    ) if not scored.empty else pd.DataFrame()
    rankings = build_rankings(scored, top_n=100)
    watch = enrich_fund_names(load_watchlist(), loader, logger)
    watch_features, watch_failures = compute_feature_table(watch, loader, config, as_of, logger) if not watch.empty else (pd.DataFrame(), pd.DataFrame())
    if not watch_features.empty and not scored.empty:
        natural_rank = scored[["基金代码", "最终分"]].copy()
        natural_rank["系统自然排名"] = range(1, len(natural_rank) + 1)
        watch_features = watch_features.merge(natural_rank, on="基金代码", how="left")
    rankings["用户观察池表现"] = watch_features
    rankings["当前实用观察池Top10"] = practical
    rankings["精选观察池"] = selected
    rankings["分散观察池"] = diversified

    holding_detail = pd.DataFrame()
    holding_stats = pd.DataFrame()
    tagged = pd.DataFrame()
    theme_stats = pd.DataFrame()
    holding_failures = pd.DataFrame()
    if with_holdings and not selected.empty:
        holding_detail, holding_failures = fetch_watch_holdings(selected["基金代码"].tolist(), loader, logger)
        name_cols = selected[["基金代码", "基金名称"]]
        if not holding_detail.empty:
            holding_detail = holding_detail.merge(name_cols, on="基金代码", how="left")
        holding_stats = holding_stock_stats(holding_detail)
        tagged, theme_stats = analyze_themes(holding_detail, len(selected), load_theme_keywords())

    all_failures = pd.concat([failures, watch_failures.assign(来源="用户观察池")], ignore_index=True) if not watch_failures.empty else failures
    sheets = {**rankings, "系统自然全量评分": scored, "失败记录": all_failures}
    sheets.update({"精选基金重仓明细": holding_detail, "重仓股统计": holding_stats, "主题统计": theme_stats, "持仓失败记录": holding_failures})
    excel_path = write_excel(out_dir / "基金雷达扫描结果.xlsx", sheets)
    for title, col, file in [
        ("综合强势榜Top30", "最终分", "综合强势榜Top30.png"),
        ("近一月强势榜Top30", "近1月收益率%", "近一月强势榜Top30.png"),
        ("近三月强势榜Top30", "近3月收益率%", "近三月强势榜Top30.png"),
        ("近六月强势榜Top30", "近6月收益率%", "近六月强势榜Top30.png"),
    ]:
        if not scored.empty and col in scored.columns:
            data = rankings.get(title.replace("Top30", ""), scored)
            bar_chart(data, "基金名称", col, title, chart_dir / file, top_n=30, config=config)
    if not theme_stats.empty:
        bar_chart(theme_stats, "主题", "合计持仓占比%", "精选观察池主题统计", chart_dir / "主题统计.png", top_n=20, config=config)
    summary_sections = {
        "本期核心主线": theme_stats.head(5) if not theme_stats.empty else "持仓归因未取得数据。",
        "精选观察池": selected[["基金代码", "基金名称", "最终分", "近1月收益率%", "近3月收益率%", "近6月收益率%", "近1年收益率%", "热度提示"]] if not selected.empty else pd.DataFrame(),
        "分散观察池": diversified[["分散池排名", "基金代码", "基金名称", "基金公司", "基金经理", "最终分", "分散池说明"]] if not diversified.empty else pd.DataFrame(),
        "分散池说明": f"分散观察池目标 {diversified_n} 只，实际 {len(diversified)} 只。" + ("因分散约束未填满。" if len(diversified) < diversified_n else ""),
        "运行质量": f"系统自然候选 {len(pool)} 只，成功评分 {len(scored)} 只，失败 {len(failures)} 只；用户观察池单独展示，不参与自然榜排名。",
        "说明": "基金雷达是信息发现和观察池生成工具，不是收益预测或买入建议。精选观察池反映最强信号，可能高度集中；分散观察池用于降低重复暴露，便于人工观察。用户指定观察池不强制进入系统自然筛选榜。",
    }
    summary_path = write_markdown(out_dir / "分析摘要.md", "基金雷达分析摘要", summary_sections)
    if out_dir.parent.name == as_of[:7]:
        write_markdown(out_dir.parent / "分析摘要.md", "基金雷达月度分析摘要", summary_sections)
    return {
        "output_dir": out_dir,
        "excel_path": excel_path,
        "pool": pool,
        "scored": scored,
        "rankings": rankings,
        "watchlist_performance": watch_features,
        "selected": selected,
        "diversified": diversified,
        "theme_stats": theme_stats,
        "holding_detail": holding_detail,
        "failures": pd.DataFrame(failures),
    }
