from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..report import write_excel, write_markdown
from ..utils import ensure_dir, normalize_code, project_path, today_str
from ..v3.run import run_v3_full


@dataclass
class TrackerResult:
    output_dir: Path
    daily_log_path: Path
    performance_path: Path
    deviation_path: Path
    portfolio: pd.DataFrame
    deviation: pd.DataFrame
    performance_summary: pd.DataFrame


def resolve_run_date(text: str | None) -> str:
    if not text or text.lower() == "today":
        return today_str()
    return pd.to_datetime(text).strftime("%Y-%m-%d")


def _stamp(df: pd.DataFrame, run_date: str, kind: str) -> pd.DataFrame:
    out = df.copy() if df is not None else pd.DataFrame()
    out.insert(0, "记录日期", run_date)
    out.insert(1, "记录时间戳", pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"))
    out.insert(2, "记录类型", kind)
    return out


def _read_existing(path: Path) -> dict[str, pd.DataFrame]:
    if not path.exists():
        return {}
    try:
        xf = pd.ExcelFile(path)
        return {sheet: pd.read_excel(path, sheet_name=sheet) for sheet in xf.sheet_names}
    except Exception:
        return {}


def _append_replace(existing: pd.DataFrame, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if existing is None or existing.empty:
        return new
    if new is None or new.empty:
        return existing
    keep = existing.copy()
    for key in keys:
        if key not in keep.columns or key not in new.columns:
            return pd.concat([keep, new], ignore_index=True)
    marker = set(tuple(x) for x in new[keys].astype(str).to_numpy())
    mask = keep[keys].astype(str).apply(lambda r: tuple(r.to_numpy()) not in marker, axis=1)
    return pd.concat([keep[mask], new], ignore_index=True)


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {str(c).lower().replace(" ", "").replace("_", ""): c for c in df.columns}
    for cand in candidates:
        key = cand.lower().replace(" ", "").replace("_", "")
        if key in normalized:
            return normalized[key]
    for col in df.columns:
        s = str(col)
        if any(c in s for c in candidates):
            return col
    return None


def load_actual_execution(path: str | Path | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame(columns=["基金代码", "实际权重%", "是否按DCA执行", "是否按止盈执行"])
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"actual execution file not found: {p}")
    df = pd.read_csv(p, dtype=str) if p.suffix.lower() == ".csv" else pd.read_excel(p, dtype=str)
    code_col = _find_col(df, ["基金代码", "code", "fund_code"])
    weight_col = _find_col(df, ["实际权重%", "actual_weight", "weight"])
    dca_col = _find_col(df, ["是否按DCA执行", "DCA是否执行", "dca_executed"])
    exit_col = _find_col(df, ["是否按止盈执行", "止盈是否执行", "exit_executed"])
    out = pd.DataFrame()
    out["基金代码"] = df[code_col].map(normalize_code) if code_col else pd.NA
    out["实际权重%"] = pd.to_numeric(df[weight_col], errors="coerce") if weight_col else pd.NA
    out["是否按DCA执行"] = df[dca_col] if dca_col else pd.NA
    out["是否按止盈执行"] = df[exit_col] if exit_col else pd.NA
    for col in df.columns:
        if col not in {code_col, weight_col, dca_col, exit_col}:
            out[col] = df[col]
    return out.dropna(subset=["基金代码"])


def build_deviation(portfolio: pd.DataFrame, dca: pd.DataFrame, exit_plan: pd.DataFrame, actual: pd.DataFrame, run_date: str) -> pd.DataFrame:
    base_cols = ["基金代码", "基金名称", "最终权重%", "目标权重%", "信号来源", "风险提示"]
    present = [c for c in base_cols if c in portfolio.columns]
    base = portfolio[present].copy() if present else pd.DataFrame()
    if "基金代码" in base.columns:
        base["基金代码"] = base["基金代码"].map(normalize_code)
    target_col = "最终权重%" if "最终权重%" in base.columns else "目标权重%"
    base = base.rename(columns={target_col: "建议权重%"})
    actual_use = actual.copy()
    if not actual_use.empty:
        actual_use["基金代码"] = actual_use["基金代码"].map(normalize_code)
    out = base.merge(actual_use, on="基金代码", how="left")
    out["实际权重%"] = pd.to_numeric(out.get("实际权重%"), errors="coerce")
    out["建议权重%"] = pd.to_numeric(out.get("建议权重%"), errors="coerce")
    out["权重偏差%"] = out["实际权重%"] - out["建议权重%"]
    out["实际执行记录状态"] = np.where(out["实际权重%"].notna(), "已提供", "未提供实际执行")
    dca_cols = ["基金代码", "建仓周期", "每次投入比例%", "是否加速建仓"]
    if not dca.empty and all(c in dca.columns for c in ["基金代码"]):
        out = out.merge(dca[[c for c in dca_cols if c in dca.columns]], on="基金代码", how="left")
    exit_cols = ["基金代码", "止盈/退出触发项", "建议动作"]
    if not exit_plan.empty and "基金代码" in exit_plan.columns:
        out = out.merge(exit_plan[[c for c in exit_cols if c in exit_plan.columns]], on="基金代码", how="left")
    if "是否按DCA执行" not in out.columns:
        out["是否按DCA执行"] = pd.NA
    if "是否按止盈执行" not in out.columns:
        out["是否按止盈执行"] = pd.NA
    out.insert(0, "记录日期", run_date)
    out.insert(1, "记录时间戳", pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"))
    return out


def _load_nav(code: str, index: bool = False) -> pd.DataFrame:
    folder = "index" if index else "nav"
    path = project_path("data", "cache", folder, f"{normalize_code(code) if not index else code}.csv")
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["净值日期"] = pd.to_datetime(df["净值日期"], errors="coerce")
    df["累计净值"] = pd.to_numeric(df["累计净值"], errors="coerce")
    return df.dropna(subset=["净值日期", "累计净值"]).sort_values("净值日期")


def _forward_return_from_nav(nav: pd.DataFrame, as_of: str, days: int = 30) -> dict[str, Any]:
    if nav.empty:
        return {"收益率%": np.nan, "是否完整验证": False, "目标日期": None, "卖出日期": None}
    start = pd.to_datetime(as_of)
    target = start + pd.Timedelta(days=int(days))
    if nav["净值日期"].max() < target:
        return {"收益率%": np.nan, "是否完整验证": False, "目标日期": target.strftime("%Y-%m-%d"), "卖出日期": None}
    buy = nav[nav["净值日期"] >= start]
    sell = nav[nav["净值日期"] <= target]
    if buy.empty or sell.empty:
        return {"收益率%": np.nan, "是否完整验证": False, "目标日期": target.strftime("%Y-%m-%d"), "卖出日期": None}
    b = buy.iloc[0]
    s = sell.iloc[-1]
    if s["净值日期"] <= b["净值日期"]:
        return {"收益率%": np.nan, "是否完整验证": False, "目标日期": target.strftime("%Y-%m-%d"), "卖出日期": None}
    ret = (float(s["累计净值"]) / float(b["累计净值"]) - 1) * 100
    return {"收益率%": ret, "是否完整验证": True, "目标日期": target.strftime("%Y-%m-%d"), "卖出日期": s["净值日期"].strftime("%Y-%m-%d")}


def _weighted_30d_return(portfolio: pd.DataFrame, as_of: str) -> dict[str, Any]:
    if portfolio.empty or "基金代码" not in portfolio.columns:
        return {"收益率%": np.nan, "是否完整验证": False}
    weight_col = "最终权重%" if "最终权重%" in portfolio.columns else "目标权重%"
    rows = []
    for _, r in portfolio.iterrows():
        nav = _load_nav(str(r.get("基金代码")))
        fr = _forward_return_from_nav(nav, as_of, 30)
        wt = pd.to_numeric(r.get(weight_col), errors="coerce")
        if pd.notna(fr["收益率%"]) and pd.notna(wt) and wt > 0:
            rows.append((fr["收益率%"], float(wt)))
        elif fr["是否完整验证"] is False:
            return {"收益率%": np.nan, "是否完整验证": False, "目标日期": fr.get("目标日期")}
    if not rows:
        return {"收益率%": np.nan, "是否完整验证": False}
    vals = np.array([x[0] for x in rows])
    wts = np.array([x[1] for x in rows])
    return {"收益率%": float(np.dot(vals, wts / wts.sum())), "是否完整验证": True}


def _metrics(series: pd.Series) -> dict[str, float]:
    x = pd.to_numeric(series, errors="coerce").dropna()
    if x.empty:
        return {"累计收益%": np.nan, "平均30天收益%": np.nan, "最大回撤%": np.nan, "胜率%": np.nan}
    curve = (1 + x / 100).cumprod()
    dd = curve / curve.cummax() - 1
    return {
        "累计收益%": float((curve.iloc[-1] - 1) * 100),
        "平均30天收益%": float(x.mean()),
        "最大回撤%": float(dd.min() * 100),
        "胜率%": float((x > 0).mean() * 100),
    }


def build_performance_summary(v3_result: dict[str, Any], run_date: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    detail = v3_result.get("backtest_summary")
    backtest_path = v3_result.get("backtest_path")
    if backtest_path and Path(backtest_path).exists():
        try:
            bt_detail = pd.read_excel(backtest_path, sheet_name="回测明细")
        except Exception:
            bt_detail = pd.DataFrame()
    else:
        bt_detail = pd.DataFrame()
    if bt_detail.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    one_month = bt_detail[bt_detail["horizon"].eq("1月")].copy()
    idx_nav = _load_nav("sh000300", index=True)
    index_returns = []
    for _, r in one_month.iterrows():
        fr = _forward_return_from_nav(idx_nav, r["扫描日"], 30)
        index_returns.append(fr["收益率%"])
    one_month["沪深300收益%"] = index_returns
    rows = []
    mapping = {
        "V3建议": "V3组合收益%",
        "V1精选": "V1精选池收益%",
        "全市场": "全市场收益%",
        "随机持有": "随机组合收益%",
        "沪深300": "沪深300收益%",
    }
    for name, col in mapping.items():
        m = _metrics(one_month[col] if col in one_month.columns else pd.Series(dtype=float))
        rows.append({"对象": name, "窗口": "30天", "样本期数": int(pd.to_numeric(one_month.get(col), errors="coerce").notna().sum()) if col in one_month else 0, **m})
    perf_summary = pd.DataFrame(rows)
    current = _weighted_30d_return(v3_result.get("allocation", pd.DataFrame()), run_date)
    current_tracking = pd.DataFrame(
        [
            {
                "记录日期": run_date,
                "目标验证日期": (pd.to_datetime(run_date) + pd.Timedelta(days=30)).strftime("%Y-%m-%d"),
                "V3建议30天收益%": current.get("收益率%"),
                "是否完整验证": current.get("是否完整验证", False),
                "状态": "已到期可验证" if current.get("是否完整验证") else "未到期，等待后续净值",
            }
        ]
    )
    one_month["V3相对随机超额%"] = one_month["V3组合收益%"] - one_month["随机组合收益%"]
    one_month["V3相对V1超额%"] = one_month["V3组合收益%"] - one_month["V1精选池收益%"]
    one_month["V3相对沪深300超额%"] = one_month["V3组合收益%"] - one_month["沪深300收益%"]
    one_month["方向命中"] = np.sign(pd.to_numeric(one_month["V3组合收益%"], errors="coerce")) == np.sign(pd.to_numeric(one_month["全市场收益%"], errors="coerce"))
    return perf_summary, one_month, current_tracking


def save_daily_log(out_dir: Path, run_date: str, portfolio: pd.DataFrame, dca: pd.DataFrame, exit_plan: pd.DataFrame, rotation: pd.DataFrame, actual: pd.DataFrame, deviation: pd.DataFrame) -> Path:
    path = out_dir / "daily_log.xlsx"
    existing = _read_existing(path)
    sheets = {
        "portfolio_log": _append_replace(existing.get("portfolio_log", pd.DataFrame()), _stamp(portfolio, run_date, "portfolio"), ["记录日期", "基金代码"]),
        "dca_log": _append_replace(existing.get("dca_log", pd.DataFrame()), _stamp(dca, run_date, "dca"), ["记录日期", "基金代码"]),
        "exit_log": _append_replace(existing.get("exit_log", pd.DataFrame()), _stamp(exit_plan, run_date, "exit"), ["记录日期", "基金代码"]),
        "rotation_log": _append_replace(existing.get("rotation_log", pd.DataFrame()), _stamp(rotation, run_date, "rotation"), ["记录日期", "主题"]),
        "actual_execution": _append_replace(existing.get("actual_execution", pd.DataFrame()), _stamp(actual, run_date, "actual"), ["记录日期", "基金代码"]) if not actual.empty else existing.get("actual_execution", pd.DataFrame()),
        "deviation": _append_replace(existing.get("deviation", pd.DataFrame()), deviation, ["记录日期", "基金代码"]),
    }
    return write_excel(path, sheets)


def run_v3_tracker(run_date: str | None = None, limit: int | None = None, actual_csv: str | Path | None = None) -> TrackerResult:
    date = resolve_run_date(run_date)
    month = date[:7]
    out_dir = ensure_dir(project_path("reports", "v3_tracker", month))
    v3 = run_v3_full(limit=limit)
    portfolio = v3.get("allocation", pd.DataFrame())
    dca = v3.get("dca", pd.DataFrame())
    exit_plan = v3.get("exit_plan", pd.DataFrame())
    rotation = v3.get("rotation", pd.DataFrame())
    actual = load_actual_execution(actual_csv)
    deviation = build_deviation(portfolio, dca, exit_plan, actual, date)
    daily_log = save_daily_log(out_dir, date, portfolio, dca, exit_plan, rotation, actual, deviation)
    perf_summary, perf_detail, current_tracking = build_performance_summary(v3, date)
    performance_path = write_excel(
        out_dir / "performance_summary.xlsx",
        {
            "30天对比汇总": perf_summary,
            "30天walk_forward明细": perf_detail,
            "当日建议30天跟踪": current_tracking,
            "指标说明": pd.DataFrame(
                [
                    {"指标": "V3建议", "说明": "按 V3 输出仓位进行纸面组合模拟，不执行交易"},
                    {"指标": "随机持有", "说明": "V3 回测中的固定随机组合基准"},
                    {"指标": "V1精选", "说明": "历史时点 V1 精选池等权收益"},
                    {"指标": "沪深300", "说明": "本地 index 缓存 sh000300 的30天收益"},
                    {"指标": "walk-forward", "说明": "每个历史扫描日只使用当时已生成的 V1/V3 结果，未来收益只用于验证"},
                ]
            ),
        },
    )
    deviation_path = write_markdown(
        out_dir / "deviation_report.md",
        f"V3 Paper Tracking Deviation Report {date}",
        {
            "定位": "Paper Tracking Mode 只记录 V3 建议和实际执行偏差，不执行交易，不预测收益。",
            "当日记录": pd.DataFrame([{"记录日期": date, "V3输出目录": str(v3.get("output_dir")), "实际执行记录": str(actual_csv) if actual_csv else "未提供"}]),
            "偏差摘要": deviation.head(30),
            "30天表现摘要": perf_summary,
            "当前30天跟踪状态": current_tracking,
            "结论口径": "用于回答“如果按 V3 执行，长期是否优于随机/指数/V1精选”。当前未到期建议只记录，不参与收益判断。",
        },
    )
    return TrackerResult(out_dir, daily_log, performance_path, deviation_path, portfolio, deviation, perf_summary)

