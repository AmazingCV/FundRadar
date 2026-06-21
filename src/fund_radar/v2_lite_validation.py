from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .metrics import future_max_drawdown
from .report import write_excel, write_markdown
from .scoring import score_funds
from .utils import ensure_dir, load_config, normalize_code, project_path, today_str


HORIZONS = {"1周": 7, "1月": 30, "3月": 91}
RETURN_PERIODS = {
    "近1周收益率%": 7,
    "近1月收益率%": 30,
    "近3月收益率%": 91,
    "近6月收益率%": 182,
    "近1年收益率%": 365,
}


@dataclass
class V2LiteResult:
    output_dir: Path
    excel_path: Path
    alpha_summary: pd.DataFrame
    lifecycle_summary: pd.DataFrame
    flow_summary: pd.DataFrame


def _pct_score(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    rank = x.rank(pct=True, method="average")
    if not higher_is_better:
        rank = 1 - rank
    return (rank.fillna(0) * 100).astype(float)


def _prepare_nav(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["基金代码"] = df.get("基金代码", path.stem).map(normalize_code)
    df["净值日期"] = pd.to_datetime(df["净值日期"], errors="coerce")
    df["累计净值"] = pd.to_numeric(df["累计净值"], errors="coerce")
    return df.dropna(subset=["净值日期", "累计净值"]).sort_values("净值日期").drop_duplicates("净值日期")


def _pick_on_or_before(df: pd.DataFrame, dt: pd.Timestamp) -> pd.Series | None:
    sub = df[df["净值日期"] <= dt]
    return None if sub.empty else sub.iloc[-1]


def _pick_on_or_after(df: pd.DataFrame, dt: pd.Timestamp) -> pd.Series | None:
    sub = df[df["净值日期"] >= dt]
    return None if sub.empty else sub.iloc[0]


def _period_return(df: pd.DataFrame, as_of: pd.Timestamp, days: int) -> float:
    visible = df[df["净值日期"] <= as_of]
    if visible.empty:
        return np.nan
    end = visible.iloc[-1]
    start = _pick_on_or_before(visible, pd.to_datetime(end["净值日期"]) - timedelta(days=int(days)))
    if start is None:
        start = visible.iloc[0]
    start_val = float(start["累计净值"])
    end_val = float(end["累计净值"])
    return (end_val / start_val - 1) * 100 if start_val > 0 else np.nan


def _forward_return(df: pd.DataFrame, as_of: pd.Timestamp, days: int) -> dict[str, Any]:
    target = as_of + timedelta(days=int(days))
    latest = df["净值日期"].max() if not df.empty else pd.NaT
    due = bool(pd.notna(latest) and latest >= target)
    buy = _pick_on_or_after(df, as_of)
    if buy is None or not due:
        return {
            "收益率%": np.nan,
            "是否完整验证": False,
            "目标验证日期": target.strftime("%Y-%m-%d"),
            "最新可用净值日期": latest.strftime("%Y-%m-%d") if pd.notna(latest) else None,
            "实际买入净值日期": pd.to_datetime(buy["净值日期"]).strftime("%Y-%m-%d") if buy is not None else None,
            "实际卖出净值日期": None,
        }
    sell = _pick_on_or_before(df, target)
    if sell is None or pd.to_datetime(sell["净值日期"]) <= pd.to_datetime(buy["净值日期"]):
        return {
            "收益率%": np.nan,
            "是否完整验证": False,
            "目标验证日期": target.strftime("%Y-%m-%d"),
            "最新可用净值日期": latest.strftime("%Y-%m-%d") if pd.notna(latest) else None,
            "实际买入净值日期": pd.to_datetime(buy["净值日期"]).strftime("%Y-%m-%d"),
            "实际卖出净值日期": None,
        }
    buy_val = float(buy["累计净值"])
    sell_val = float(sell["累计净值"])
    return {
        "收益率%": (sell_val / buy_val - 1) * 100 if buy_val > 0 else np.nan,
        "是否完整验证": True,
        "目标验证日期": target.strftime("%Y-%m-%d"),
        "最新可用净值日期": latest.strftime("%Y-%m-%d"),
        "实际买入净值日期": pd.to_datetime(buy["净值日期"]).strftime("%Y-%m-%d"),
        "实际卖出净值日期": pd.to_datetime(sell["净值日期"]).strftime("%Y-%m-%d"),
    }


def _load_fund_info(root: Path) -> pd.DataFrame:
    path = root / "data" / "cache" / "fund_name_em.csv"
    if not path.exists():
        return pd.DataFrame(columns=["基金代码", "基金名称", "基金类型"])
    df = pd.read_csv(path, dtype={"基金代码": str})
    df["基金代码"] = df["基金代码"].map(normalize_code)
    return df.drop_duplicates("基金代码")


def _is_active_equity(row: pd.Series) -> bool:
    text = f"{row.get('基金名称', '')}{row.get('基金类型', '')}"
    include = any(k in text for k in ["股票型", "混合型"])
    exclude = any(k in text for k in ["债券", "货币", "指数", "ETF", "联接", "QDII", "FOF", "养老", "REIT", "黄金", "原油", "商品"])
    return include and not exclude


def load_cached_universe(limit: int | None = None) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    root = project_path()
    info = _load_fund_info(root)
    info_map = info.set_index("基金代码").to_dict("index") if not info.empty else {}
    rows = []
    navs: dict[str, pd.DataFrame] = {}
    for path in sorted((root / "data" / "cache" / "nav").glob("*.csv")):
        code = normalize_code(path.stem)
        meta = info_map.get(code, {"基金代码": code, "基金名称": "", "基金类型": ""})
        if not _is_active_equity(pd.Series(meta)):
            continue
        try:
            nav = _prepare_nav(path)
        except Exception:
            continue
        if len(nav) < 120:
            continue
        navs[code] = nav
        rows.append({"基金代码": code, "基金名称": meta.get("基金名称", ""), "基金类型": meta.get("基金类型", "")})
        if limit and len(rows) >= int(limit):
            break
    return pd.DataFrame(rows), navs


def default_scan_dates(navs: dict[str, pd.DataFrame]) -> list[str]:
    latest = max((df["净值日期"].max() for df in navs.values() if not df.empty), default=pd.NaT)
    if pd.isna(latest):
        return []
    start = pd.Timestamp("2025-06-18")
    dates = [start]
    month_ends = pd.date_range("2025-07-31", latest.normalize(), freq="ME")
    dates.extend(month_ends.to_pydatetime())
    return [pd.Timestamp(x).strftime("%Y-%m-%d") for x in dates if pd.Timestamp(x) <= latest]


def build_scan_features(pool: pd.DataFrame, navs: dict[str, pd.DataFrame], as_of: str) -> pd.DataFrame:
    as_dt = pd.to_datetime(as_of)
    rows = []
    meta = pool.set_index("基金代码").to_dict("index")
    for code, nav in navs.items():
        visible = nav[nav["净值日期"] <= as_dt]
        if len(visible) < 80:
            continue
        row = {
            "扫描日": as_dt.strftime("%Y-%m-%d"),
            "基金代码": code,
            "基金名称": meta.get(code, {}).get("基金名称", ""),
            "基金类型": meta.get(code, {}).get("基金类型", ""),
            "最新净值日期": visible["净值日期"].max().strftime("%Y-%m-%d"),
            "净值样本数": len(visible),
        }
        for name, days in RETURN_PERIODS.items():
            row[name] = _period_return(nav, as_dt, days)
        rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["近1周排名分"] = _pct_score(out["近1周收益率%"])
    out["近3月排名分"] = _pct_score(out["近3月收益率%"])
    out["rank_jump_score"] = _pct_score(out["近1周排名分"] - out["近3月排名分"])
    slope_1w = pd.to_numeric(out["近1周收益率%"], errors="coerce") / 7
    slope_1m = pd.to_numeric(out["近1月收益率%"], errors="coerce") / 30
    slope_3m = pd.to_numeric(out["近3月收益率%"], errors="coerce") / 91
    out["acceleration_score"] = _pct_score((slope_1w - slope_3m) + 0.5 * (slope_1m - slope_3m))
    out["new_alpha_score"] = (out["rank_jump_score"] + out["acceleration_score"]) / 2
    return out.sort_values("new_alpha_score", ascending=False).reset_index(drop=True)


def add_forward_returns(features: pd.DataFrame, navs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    out = features.copy()
    for horizon, days in HORIZONS.items():
        values = []
        complete = []
        target_dates = []
        sell_dates = []
        dds = []
        for _, row in out.iterrows():
            code = normalize_code(row["基金代码"])
            nav = navs.get(code)
            if nav is None:
                values.append(np.nan)
                complete.append(False)
                target_dates.append(None)
                sell_dates.append(None)
                dds.append(np.nan)
                continue
            fr = _forward_return(nav, pd.to_datetime(row["扫描日"]), days)
            values.append(fr["收益率%"])
            complete.append(fr["是否完整验证"])
            target_dates.append(fr["目标验证日期"])
            sell_dates.append(fr["实际卖出净值日期"])
            dds.append(future_max_drawdown(nav.rename(columns={"净值日期": "净值日期", "累计净值": "累计净值"}), row["扫描日"], days))
        out[f"未来{horizon}收益%"] = values
        out[f"未来{horizon}是否完整验证"] = complete
        out[f"未来{horizon}目标验证日期"] = target_dates
        out[f"未来{horizon}实际卖出净值日期"] = sell_dates
        out[f"未来{horizon}最大回撤%"] = dds
    return out


def _group_stats(frame: pd.DataFrame, selected_codes: set[str], label: str, as_of: str) -> list[dict[str, Any]]:
    rows = []
    selected = frame[frame["基金代码"].isin(selected_codes)]
    for horizon in HORIZONS:
        complete_col = f"未来{horizon}是否完整验证"
        ret_col = f"未来{horizon}收益%"
        dd_col = f"未来{horizon}最大回撤%"
        universe = frame[frame[complete_col].fillna(False)]
        group = selected[selected[complete_col].fillna(False)]
        if universe.empty or group.empty:
            continue
        group_ret = pd.to_numeric(group[ret_col], errors="coerce").mean()
        universe_ret = pd.to_numeric(universe[ret_col], errors="coerce").mean()
        rows.append(
            {
                "扫描日": as_of,
                "验证对象": label,
                "horizon": horizon,
                "基金数": len(group),
                "全候选池数量": len(universe),
                "未来平均收益%": group_ret,
                "全候选池平均收益%": universe_ret,
                "相对全候选超额%": group_ret - universe_ret,
                "正超额": bool(group_ret > universe_ret),
                "平均最大回撤%": pd.to_numeric(group[dd_col], errors="coerce").mean(),
                "全候选平均最大回撤%": pd.to_numeric(universe[dd_col], errors="coerce").mean(),
            }
        )
    return rows


def validate_alpha(scans: list[pd.DataFrame], navs: dict[str, pd.DataFrame], config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    details = []
    stats = []
    for features in scans:
        if features.empty:
            continue
        as_of = str(features["扫描日"].iloc[0])
        frame = add_forward_returns(features, navs)
        v1_scored = score_funds(features.copy(), config)
        alpha_top = frame.sort_values("new_alpha_score", ascending=False).head(20)
        v1_top = v1_scored.head(5)
        alpha_codes = set(alpha_top["基金代码"])
        v1_codes = set(v1_top["基金代码"])
        tmp = alpha_top.copy()
        tmp["验证对象"] = "新星基金Top20"
        details.append(tmp)
        stats.extend(_group_stats(frame, alpha_codes, "新星基金Top20", as_of))
        stats.extend(_group_stats(frame, v1_codes, "V1精选观察池Top5", as_of))
    stat_df = pd.DataFrame(stats)
    if not stat_df.empty:
        v1 = stat_df[stat_df["验证对象"].eq("V1精选观察池Top5")][["扫描日", "horizon", "未来平均收益%", "平均最大回撤%"]].rename(
            columns={"未来平均收益%": "V1精选未来平均收益%", "平均最大回撤%": "V1精选平均最大回撤%"}
        )
        stat_df = stat_df.merge(v1, on=["扫描日", "horizon"], how="left")
        stat_df["相对V1精选超额%"] = stat_df["未来平均收益%"] - stat_df["V1精选未来平均收益%"]
    return pd.concat(details, ignore_index=True) if details else pd.DataFrame(), stat_df


def load_fund_theme_exposure() -> pd.DataFrame:
    root = project_path()
    theme_path = root / "config" / "theme_keywords.yaml"
    with open(theme_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    themes = {name: body.get("keywords", []) for name, body in raw.get("themes", {}).items()}
    rows = []
    for path in sorted((root / "data" / "cache" / "holdings").glob("*.csv")):
        code = normalize_code(path.stem)
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        for _, r in df.iterrows():
            stock = str(r.get("股票名称", ""))
            weight = pd.to_numeric(r.get("持仓占比%", 0), errors="coerce")
            for theme, keywords in themes.items():
                if any(k and k in stock for k in keywords):
                    rows.append({"基金代码": code, "主题": theme, "股票名称": stock, "持仓占比%": float(weight) if pd.notna(weight) else 0.0})
    if not rows:
        return pd.DataFrame(columns=["基金代码", "主题", "主题持仓占比%"])
    return pd.DataFrame(rows).groupby(["基金代码", "主题"], as_index=False)["持仓占比%"].sum().rename(columns={"持仓占比%": "主题持仓占比%"})


def build_theme_features(scans: list[pd.DataFrame], exposure: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for features in scans:
        if features.empty:
            continue
        as_of = str(features["扫描日"].iloc[0])
        merged = features.merge(exposure, on="基金代码", how="inner")
        if merged.empty:
            continue
        universe_1m = pd.to_numeric(features["近1月收益率%"], errors="coerce").median()
        universe_3m = pd.to_numeric(features["近3月收益率%"], errors="coerce").median()
        for theme, g in merged.groupby("主题"):
            total_weight = pd.to_numeric(g["主题持仓占比%"], errors="coerce").sum()
            fund_count = g["基金代码"].nunique()
            top_weight = g.groupby("基金代码")["主题持仓占比%"].sum().sort_values(ascending=False).head(5).sum()
            rows.append(
                {
                    "扫描日": as_of,
                    "主题": theme,
                    "覆盖基金数量": fund_count,
                    "主题持仓占比合计%": total_weight,
                    "Top5集中度%": top_weight / total_weight * 100 if total_weight else np.nan,
                    "主题近1月收益中位数%": pd.to_numeric(g["近1月收益率%"], errors="coerce").median(),
                    "主题近3月收益中位数%": pd.to_numeric(g["近3月收益率%"], errors="coerce").median(),
                    "主题近1年收益中位数%": pd.to_numeric(g["近1年收益率%"], errors="coerce").median(),
                    "全市场近1月收益中位数%": universe_1m,
                    "全市场近3月收益中位数%": universe_3m,
                }
            )
    theme = pd.DataFrame(rows)
    if theme.empty:
        return theme
    pieces = []
    for _, g in theme.groupby("扫描日"):
        part = g.copy()
        part["主题强度分"] = (
            _pct_score(part["覆盖基金数量"]) * 0.30
            + _pct_score(part["主题持仓占比合计%"]) * 0.30
            + _pct_score(part["主题近1月收益中位数%"]) * 0.20
            + _pct_score(part["主题近3月收益中位数%"]) * 0.20
        )
        pieces.append(part)
    theme = pd.concat(pieces, ignore_index=True)
    theme = theme.sort_values(["主题", "扫描日"]).reset_index(drop=True)
    theme["上期主题强度分"] = theme.groupby("主题")["主题强度分"].shift(1)
    theme["主题强度变化"] = theme["主题强度分"] - theme["上期主题强度分"]
    theme["生命周期阶段"] = theme.apply(classify_lifecycle, axis=1)
    return theme


def classify_lifecycle(row: pd.Series) -> str:
    delta = row.get("主题强度变化")
    strength = row.get("主题强度分", 0)
    r1m = row.get("主题近1月收益中位数%", np.nan)
    r3m = row.get("主题近3月收益中位数%", np.nan)
    r1y = row.get("主题近1年收益中位数%", np.nan)
    market_1m = row.get("全市场近1月收益中位数%", np.nan)
    if pd.notna(r1y) and r1y >= 150 or pd.notna(r3m) and r3m >= 90:
        return "过热期"
    if pd.notna(delta) and delta < -8 and pd.notna(r1m) and pd.notna(market_1m) and r1m < market_1m:
        return "退潮期"
    if pd.notna(delta) and delta > 8 and pd.notna(r1m) and pd.notna(market_1m) and r1m > market_1m:
        return "加速期"
    if pd.isna(delta) or strength < 45:
        return "萌芽期"
    return "加速期" if pd.notna(r1m) and pd.notna(market_1m) and r1m > market_1m else "退潮期"


def validate_lifecycle(theme_features: pd.DataFrame, scans_with_future: list[pd.DataFrame], exposure: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    future_map = {str(df["扫描日"].iloc[0]): df for df in scans_with_future if not df.empty}
    rows = []
    for _, row in theme_features.iterrows():
        as_of = row["扫描日"]
        frame = future_map.get(as_of)
        if frame is None:
            continue
        codes = set(exposure[exposure["主题"].eq(row["主题"])]["基金代码"])
        themed = frame[frame["基金代码"].isin(codes)]
        for horizon in ["1月", "3月"]:
            complete_col = f"未来{horizon}是否完整验证"
            ret_col = f"未来{horizon}收益%"
            universe = frame[frame[complete_col].fillna(False)]
            group = themed[themed[complete_col].fillna(False)]
            if universe.empty or group.empty:
                continue
            theme_ret = pd.to_numeric(group[ret_col], errors="coerce").mean()
            market_ret = pd.to_numeric(universe[ret_col], errors="coerce").mean()
            expected_positive = row["生命周期阶段"] in {"萌芽期", "加速期"}
            actual_positive = theme_ret > market_ret
            rows.append(
                {
                    **row.to_dict(),
                    "horizon": horizon,
                    "未来主题平均收益%": theme_ret,
                    "未来全市场平均收益%": market_ret,
                    "未来主题超额%": theme_ret - market_ret,
                    "趋势方向判断正确": bool(expected_positive == actual_positive),
                }
            )
    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail, pd.DataFrame()
    summary = (
        detail.groupby(["生命周期阶段", "horizon"])
        .agg(
            样本数=("主题", "count"),
            平均未来主题收益=("未来主题平均收益%", "mean"),
            平均未来超额=("未来主题超额%", "mean"),
            正超额比例=("未来主题超额%", lambda x: (pd.to_numeric(x, errors="coerce") > 0).mean() * 100),
            趋势一致率=("趋势方向判断正确", lambda x: pd.Series(x).mean() * 100),
        )
        .reset_index()
    )
    return detail, summary


def validate_flow(theme_features: pd.DataFrame, lifecycle_detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    dates = sorted(theme_features["扫描日"].dropna().unique())
    for date in dates[1:]:
        cur = theme_features[theme_features["扫描日"].eq(date)].dropna(subset=["主题强度变化"])
        if cur.empty:
            continue
        out_theme = cur.sort_values("主题强度变化").iloc[0]
        in_theme = cur.sort_values("主题强度变化", ascending=False).iloc[0]
        if out_theme["主题"] == in_theme["主题"] or in_theme["主题强度变化"] <= 0 or out_theme["主题强度变化"] >= 0:
            continue
        for horizon in ["1月", "3月"]:
            ld = lifecycle_detail[lifecycle_detail["扫描日"].eq(date) & lifecycle_detail["horizon"].eq(horizon)]
            a = ld[ld["主题"].eq(out_theme["主题"])]
            b = ld[ld["主题"].eq(in_theme["主题"])]
            if a.empty or b.empty:
                continue
            a_ret = float(a["未来主题平均收益%"].iloc[0])
            b_ret = float(b["未来主题平均收益%"].iloc[0])
            market_ret = float(b["未来全市场平均收益%"].iloc[0])
            rows.append(
                {
                    "扫描日": date,
                    "流出主题A": out_theme["主题"],
                    "流入主题B": in_theme["主题"],
                    "A强度变化": out_theme["主题强度变化"],
                    "B强度变化": in_theme["主题强度变化"],
                    "horizon": horizon,
                    "A未来收益%": a_ret,
                    "B未来收益%": b_ret,
                    "全市场未来收益%": market_ret,
                    "B跑赢A": b_ret > a_ret,
                    "B跑赢全市场": b_ret > market_ret,
                    "A走弱验证": a_ret < market_ret,
                }
            )
    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail, pd.DataFrame()
    summary = (
        detail.groupby("horizon")
        .agg(
            迁移事件数=("扫描日", "count"),
            B跑赢A比例=("B跑赢A", lambda x: pd.Series(x).mean() * 100),
            B跑赢全市场比例=("B跑赢全市场", lambda x: pd.Series(x).mean() * 100),
            A走弱验证比例=("A走弱验证", lambda x: pd.Series(x).mean() * 100),
            B相对A平均超额=("B未来收益%", "mean"),
            A平均收益=("A未来收益%", "mean"),
        )
        .reset_index()
    )
    summary["B相对A平均超额"] = detail.groupby("horizon").apply(lambda x: (x["B未来收益%"] - x["A未来收益%"]).mean()).values
    return detail, summary


def module_conclusions(alpha_summary: pd.DataFrame, lifecycle_summary: pd.DataFrame, flow_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    alpha = alpha_summary[alpha_summary["验证对象"].eq("新星基金Top20")] if not alpha_summary.empty else pd.DataFrame()
    if not alpha.empty:
        rows.append(
            {
                "模块": "新星基金验证",
                "样本数": len(alpha),
                "平均超额%": pd.to_numeric(alpha["相对全候选超额%"], errors="coerce").mean(),
                "正超额比例%": alpha["正超额"].mean() * 100,
                "量化结论": _judge_gain(pd.to_numeric(alpha["相对全候选超额%"], errors="coerce").mean(), alpha["正超额"].mean() * 100),
            }
        )
    if not lifecycle_summary.empty:
        rows.append(
            {
                "模块": "主线生命周期验证",
                "样本数": int(lifecycle_summary["样本数"].sum()),
                "平均超额%": pd.to_numeric(lifecycle_summary["平均未来超额"], errors="coerce").mean(),
                "正超额比例%": pd.to_numeric(lifecycle_summary["正超额比例"], errors="coerce").mean(),
                "量化结论": f"趋势一致率均值 {pd.to_numeric(lifecycle_summary['趋势一致率'], errors='coerce').mean():.1f}%",
            }
        )
    if not flow_summary.empty:
        rows.append(
            {
                "模块": "资金迁移验证",
                "样本数": int(flow_summary["迁移事件数"].sum()),
                "平均超额%": pd.to_numeric(flow_summary["B相对A平均超额"], errors="coerce").mean(),
                "正超额比例%": pd.to_numeric(flow_summary["B跑赢A比例"], errors="coerce").mean(),
                "量化结论": f"B跑赢A均值 {pd.to_numeric(flow_summary['B跑赢A比例'], errors='coerce').mean():.1f}%",
            }
        )
    return pd.DataFrame(rows)


def _judge_gain(mean_excess: float, positive_ratio: float) -> str:
    if pd.notna(mean_excess) and mean_excess > 0 and positive_ratio >= 55:
        return "有正向信息增益"
    if pd.notna(mean_excess) and mean_excess > 0:
        return "平均正超额但稳定性不足"
    return "未验证出稳定信息增益"


def run_v2_lite_validation(limit: int | None = None, scan_dates: list[str] | None = None, output_dir: str | Path | None = None) -> V2LiteResult:
    config = load_config()
    pool, navs = load_cached_universe(limit=limit)
    dates = scan_dates or default_scan_dates(navs)
    scans = [build_scan_features(pool, navs, d) for d in dates]
    scans = [s for s in scans if not s.empty]
    scans_with_future = [add_forward_returns(s, navs) for s in scans]
    alpha_detail, alpha_summary = validate_alpha(scans, navs, config)
    exposure = load_fund_theme_exposure()
    theme_features = build_theme_features(scans, exposure)
    lifecycle_detail, lifecycle_summary = validate_lifecycle(theme_features, scans_with_future, exposure)
    flow_detail, flow_summary = validate_flow(theme_features, lifecycle_detail)
    conclusions = module_conclusions(alpha_summary, lifecycle_summary, flow_summary)
    out_dir = ensure_dir(output_dir or project_path("reports", "v2_lite", today_str()))
    excel_path = write_excel(
        out_dir / "V2验证报告.xlsx",
        {
            "模块结论": conclusions,
            "新星基金验证汇总": alpha_summary,
            "新星基金明细": alpha_detail,
            "生命周期验证汇总": lifecycle_summary,
            "生命周期明细": lifecycle_detail,
            "主题时序特征": theme_features,
            "资金迁移验证汇总": flow_summary,
            "资金迁移明细": flow_detail,
            "基金主题暴露": exposure,
            "参数说明": pd.DataFrame(
                [
                    {"项目": "数据来源", "说明": "仅使用 data/cache/nav、data/cache/holdings、config/theme_keywords.yaml 和现有 V1 配置"},
                    {"项目": "新星定义", "说明": "rank_jump_score 与 acceleration_score 综合排名靠前，并取每期 Top20 验证"},
                    {"项目": "验证窗口", "说明": "未来1周、1月、3月；未到期窗口不参与统计"},
                    {"项目": "V1对照", "说明": "同一历史扫描日调用现有 V1 score_funds 生成 Top5 作为精选观察池对照，不修改 V1 逻辑"},
                    {"项目": "主题限制", "说明": "主题暴露基于现有持仓缓存，持仓披露存在滞后；结果用于验证流程和信息增益，不构成主题因子严格证明"},
                ]
            ),
        },
    )
    write_markdown(
        out_dir / "V2验证摘要.md",
        "V2-lite 验证摘要",
        {
            "模块结论": conclusions,
            "新星基金验证": alpha_summary,
            "主线生命周期验证": lifecycle_summary,
            "资金迁移验证": flow_summary,
            "重要限制": "本次验证只使用已有本地缓存和既有配置；主题持仓数据存在披露滞后，不能等同于实时资金流。结论必须以统计结果为准，不把设计合理性当成预测能力。",
        },
    )
    return V2LiteResult(out_dir, excel_path, alpha_summary, lifecycle_summary, flow_summary)

