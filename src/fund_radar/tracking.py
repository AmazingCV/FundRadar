from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .pipeline import market_scan
from .report import write_excel, write_markdown
from .theme_analysis import compare_theme_stats
from .utils import ensure_dir, load_config, project_path, setup_logging, today_str


def find_previous_snapshot(snapshot_root: Path, current_date: str) -> Path | None:
    files = sorted(snapshot_root.glob("*/snapshot.xlsx"))
    files = [p for p in files if p.parent.name < current_date]
    return files[-1] if files else None


def read_sheet(path: Path, sheet: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet, dtype={"基金代码": str})
    except Exception:
        return pd.DataFrame()


def compare_selected(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    cur = current[["基金代码", "基金名称", "最终分"]].copy() if not current.empty else pd.DataFrame(columns=["基金代码", "基金名称", "最终分"])
    prev = previous[["基金代码", "基金名称", "最终分"]].copy() if not previous.empty else pd.DataFrame(columns=["基金代码", "基金名称", "最终分"])
    merged = cur.merge(prev, on="基金代码", how="outer", suffixes=("_当前", "_上期"))
    merged["变化"] = merged.apply(
        lambda r: "新进入" if pd.isna(r.get("基金名称_上期")) else ("掉出" if pd.isna(r.get("基金名称_当前")) else "留存"),
        axis=1,
    )
    merged["分数变化"] = pd.to_numeric(merged.get("最终分_当前"), errors="coerce") - pd.to_numeric(merged.get("最终分_上期"), errors="coerce")
    return merged


def run_tracking(
    config: dict[str, Any] | None = None,
    as_of: str | None = None,
    limit: int | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    logger = logger or setup_logging(log_dir=config.get("project", {}).get("log_root", "data/reports"))
    as_of = as_of or today_str()
    report_dir = ensure_dir(project_path("reports", as_of[:7], as_of))
    scan = market_scan(config=config, as_of=as_of, output_dir=report_dir, limit=limit, with_holdings=True, logger=logger)
    snapshot_root = ensure_dir(project_path("data", "snapshots"))
    snap_dir = ensure_dir(snapshot_root / as_of)
    snap_path = snap_dir / "snapshot.xlsx"
    current_selected = scan["selected"]
    current_diversified = scan.get("diversified", pd.DataFrame())
    current_theme = scan["theme_stats"]
    previous_path = find_previous_snapshot(snapshot_root, as_of)
    previous_selected = read_sheet(previous_path, "精选观察池") if previous_path else pd.DataFrame()
    previous_theme = read_sheet(previous_path, "主题统计") if previous_path else pd.DataFrame()
    selected_compare = compare_selected(current_selected, previous_selected)
    theme_compare = compare_theme_stats(current_theme, previous_theme)
    sheets = {
        "当前实用观察池": scan["rankings"].get("当前实用观察池Top10", pd.DataFrame()),
        "精选观察池": current_selected,
        "分散观察池": current_diversified,
        "精选池变化": selected_compare,
        "重仓明细": scan.get("holding_detail", pd.DataFrame()),
        "重仓股统计": scan.get("holding_stats", pd.DataFrame()) if "holding_stats" in scan else pd.DataFrame(),
        "主题统计": current_theme,
        "主题变化": theme_compare,
        "失败记录": scan.get("failures", pd.DataFrame()),
    }
    write_excel(snap_path, sheets)
    tracking_excel = write_excel(report_dir / "连续跟踪报告.xlsx", sheets)
    new_in = selected_compare[selected_compare["变化"] == "新进入"] if not selected_compare.empty else pd.DataFrame()
    out = selected_compare[selected_compare["变化"] == "掉出"] if not selected_compare.empty else pd.DataFrame()
    write_markdown(
        report_dir / "连续跟踪摘要.md",
        f"基金雷达连续跟踪摘要 {as_of}",
        {
            "本期核心主线": current_theme.head(5) if not current_theme.empty else "未取得主题归因。",
            "精选观察池": current_selected[["基金代码", "基金名称", "最终分", "热度提示"]] if not current_selected.empty else pd.DataFrame(),
            "分散观察池": current_diversified[["分散池排名", "基金代码", "基金名称", "基金公司", "基金经理", "最终分", "分散池说明"]] if not current_diversified.empty else pd.DataFrame(),
            "新进基金": new_in,
            "掉出基金": out,
            "主题变化": theme_compare,
            "后续跟踪重点": "重点观察核心主线是否继续强化、扩散或退潮；精选观察池反映最强信号，可能高度集中；分散观察池用于降低重复暴露，便于人工观察。",
        },
    )
    return {"snapshot_path": snap_path, "report_path": tracking_excel, "scan": scan, "selected_compare": selected_compare, "theme_compare": theme_compare}
