from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .backtest import evaluate_selection, features_at_date, load_nav_cache, month_end_dates
from .data_loader import DataLoader
from .fund_filter import dedupe_ac
from .metrics import compute_feature_row
from .pipeline import build_candidate_pool
from .report import write_excel, write_markdown
from .scoring import score_funds
from .utils import ensure_dir, load_config, project_path, setup_logging, today_str


WEIGHT_SCHEMES: dict[str, dict[str, float]] = {
    "原始版": {"近1月收益率%": 0.20, "近3月收益率%": 0.30, "近6月收益率%": 0.25, "近1年收益率%": 0.15, "近1年最大回撤%": 0.10},
    "稳健趋势版": {"近1月收益率%": 0.10, "近3月收益率%": 0.25, "近6月收益率%": 0.30, "近1年收益率%": 0.20, "近1年最大回撤%": 0.15},
    "中期动量版": {"近1月收益率%": 0.15, "近3月收益率%": 0.40, "近6月收益率%": 0.30, "近1年收益率%": 0.10, "近1年最大回撤%": 0.05},
    "防追高版": {"近1月收益率%": 0.10, "近3月收益率%": 0.25, "近6月收益率%": 0.25, "近1年收益率%": 0.10, "近1年最大回撤%": 0.30},
    "长趋势版": {"近1月收益率%": 0.05, "近3月收益率%": 0.20, "近6月收益率%": 0.30, "近1年收益率%": 0.35, "近1年最大回撤%": 0.10},
    "低回撤优先版": {"近1月收益率%": 0.05, "近3月收益率%": 0.15, "近6月收益率%": 0.20, "近1年收益率%": 0.10, "近1年最大回撤%": 0.50},
}


def config_with_scheme(config: dict, scheme: dict[str, float], overheat_penalty: bool) -> dict:
    cfg = copy.deepcopy(config)
    cfg.setdefault("scoring", {})["weights"] = scheme
    cfg["scoring"]["overheat_penalty"] = overheat_penalty
    return cfg


def run_scheme(
    scheme_name: str,
    scheme: dict[str, float],
    config: dict,
    pool: pd.DataFrame,
    navs: dict[str, pd.DataFrame],
    scan_dates: list[pd.Timestamp],
    horizons: dict[str, int],
    top_n: int,
    overheat_penalty: bool,
    dedupe: bool,
    feature_cache: dict[pd.Timestamp, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    cfg = config_with_scheme(config, scheme, overheat_penalty)
    rows = []
    for scan_date in scan_dates:
        if feature_cache is None:
            scored = features_at_date(scan_date, pool, navs, cfg, use_overheat_penalty=overheat_penalty, dedupe=dedupe)
        else:
            raw = feature_cache.get(scan_date, pd.DataFrame())
            scored = score_funds(raw, cfg, use_overheat_penalty=overheat_penalty) if not raw.empty else raw
            if dedupe and not scored.empty:
                scored = dedupe_ac(scored, "最终分")
        if scored.empty:
            continue
        selected = scored.head(top_n)
        _, summary = evaluate_selection(scan_date, selected, scored, navs, horizons)
        rows.append(summary)
    df = pd.DataFrame(rows)
    result: dict[str, Any] = {
        "方案": scheme_name,
        "TopN": top_n,
        "过热惩罚": overheat_penalty,
        "AC去重": dedupe,
        "期数": len(df),
    }
    scores = []
    for name in horizons:
        ex = pd.to_numeric(df.get(f"平均超额{name}%"), errors="coerce").dropna()
        result[f"{name}平均超额收益%"] = ex.mean()
        result[f"{name}超额为正期数占比%"] = (ex > 0).mean() * 100 if len(ex) else pd.NA
        if len(ex):
            scores.append(ex.mean() * 0.7 + ((ex > 0).mean() * 100 - 50) * 0.1)
    result["策略评价分"] = sum(scores) / len(scores) if scores else pd.NA
    return result


def precompute_feature_cache(pool: pd.DataFrame, navs: dict[str, pd.DataFrame], scan_dates: list[pd.Timestamp], config: dict) -> dict[pd.Timestamp, pd.DataFrame]:
    periods = {k: v for k, v in config.get("periods", {}).items() if k != "近3年"}
    cache: dict[pd.Timestamp, pd.DataFrame] = {}
    for scan_date in scan_dates:
        rows = []
        for _, fund in pool.iterrows():
            code = str(fund["基金代码"]).zfill(6)
            nav = navs.get(code)
            if nav is None:
                continue
            try:
                row = compute_feature_row(nav, scan_date, periods)
                row.update({"基金代码": code, "基金名称": fund.get("基金名称", ""), "基金类型": fund.get("基金类型", "")})
                rows.append(row)
            except Exception:
                continue
        cache[scan_date] = pd.DataFrame(rows)
    return cache


def run_weight_search(
    config: dict[str, Any] | None = None,
    train_start: str = "2023-01-01",
    train_end: str = "2025-06-18",
    valid_start: str = "2025-06-18",
    valid_end: str | None = None,
    limit: int | None = None,
    output_dir: str | Path | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    logger = logger or setup_logging(log_dir=config.get("project", {}).get("log_root", "data/reports"))
    valid_end = valid_end or today_str()
    out_dir = ensure_dir(output_dir or project_path("reports", "weight_search", f"{train_start}_{valid_end}"))
    loader = DataLoader(config, logger)
    pool = build_candidate_pool(config, loader, logger, limit=limit)
    navs, failures = load_nav_cache(pool, loader, logger, int(config.get("data", {}).get("min_history_days", 120)))
    horizons = config.get("backtest", {}).get("horizons", {"3月": 91, "6月": 182, "12月": 365})
    train_dates = month_end_dates(train_start, train_end)
    valid_dates = month_end_dates(valid_start, valid_end)
    train_cache = precompute_feature_cache(pool, navs, train_dates, config)
    valid_cache = precompute_feature_cache(pool, navs, valid_dates, config)
    top_ns = [10, 20, 30]
    rows_train = []
    rows_valid = []
    for scheme_name, scheme in WEIGHT_SCHEMES.items():
        for top_n in top_ns:
            for overheat in [False, True]:
                for dedupe in [False, True]:
                    train = run_scheme(scheme_name, scheme, config, pool, navs, train_dates, horizons, top_n, overheat, dedupe, feature_cache=train_cache)
                    valid = run_scheme(scheme_name, scheme, config, pool, navs, valid_dates, horizons, top_n, overheat, dedupe, feature_cache=valid_cache)
                    rows_train.append(train)
                    rows_valid.append(valid)
    train_df = pd.DataFrame(rows_train).sort_values("策略评价分", ascending=False)
    valid_df = pd.DataFrame(rows_valid).sort_values("策略评价分", ascending=False)
    train_df["样本判断"] = train_df["期数"].apply(lambda n: "样本不足，仅流程验证" if int(n or 0) < 12 else "训练期样本数满足最低要求")
    valid_df["样本判断"] = valid_df["期数"].apply(lambda n: "样本不足，仅流程验证" if int(n or 0) < 6 else "验证期样本数满足最低要求")
    merged = train_df.merge(valid_df, on=["方案", "TopN", "过热惩罚", "AC去重"], suffixes=("_训练", "_验证"))
    merged["样本外退化分"] = pd.to_numeric(merged["策略评价分_训练"], errors="coerce") - pd.to_numeric(merged["策略评价分_验证"], errors="coerce")
    merged["结论状态"] = merged.apply(
        lambda r: "样本不足，仅流程验证"
        if int(r.get("期数_训练", 0) or 0) < 12 or int(r.get("期数_验证", 0) or 0) < 6
        else ("疑似过拟合" if pd.notna(r.get("样本外退化分")) and r.get("样本外退化分") > 5 else "可进入候选规则复核"),
        axis=1,
    )
    merged["过拟合提示"] = merged["结论状态"]
    excel_path = write_excel(out_dir / "权重搜索结果.xlsx", {"训练区间排名": train_df, "验证区间排名": valid_df, "训练验证对比": merged, "净值失败记录": failures})
    best = merged.sort_values("策略评价分_验证", ascending=False).head(10)
    write_markdown(
        out_dir / "权重搜索摘要.md",
        "规则自我修正与留出验证摘要",
        {
            "区间": f"训练/调参区间：{train_start} 至 {train_end}；留出验证区间：{valid_start} 至 {valid_end}。验证区间不参与调参。",
            "验证区间Top方案": best,
            "结论口径": "训练期数少于12或验证期数少于6时，只标记为“样本不足，仅流程验证”，不输出样本外有效或无过拟合结论。样本满足最低要求后，才优先选择样本外策略评价分高且样本内外差距不大的规则。",
        },
    )
    return {"output_dir": out_dir, "excel_path": excel_path, "train": train_df, "valid": valid_df, "compare": merged}
