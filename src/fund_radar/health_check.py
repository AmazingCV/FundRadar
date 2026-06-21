from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .report import write_excel, write_markdown
from .utils import ensure_dir, parse_date, project_path, today_str


EXPECTED_DAILY_STEPS = [
    "market_scan",
    "short_term_radar",
    "v3_full",
    "v3_tracker",
    "v4_full",
    "daily_report",
]


@dataclass
class HealthResult:
    as_of: str
    output_dir: Path
    markdown: Path
    excel: Path


def _valid_file(path: Path) -> bool:
    return path.is_file() and not path.name.startswith("~$")


def _latest_file(pattern: str) -> Path | None:
    files = [p for p in project_path("reports").rglob(pattern) if _valid_file(p)]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _read_excel_sheets(path: Path | None) -> dict[str, pd.DataFrame]:
    if path is None or not path.exists():
        return {}
    try:
        xf = pd.ExcelFile(path)
    except Exception:
        return {}
    out: dict[str, pd.DataFrame] = {}
    for sheet in xf.sheet_names:
        try:
            out[sheet] = pd.read_excel(path, sheet_name=sheet)
        except Exception:
            out[sheet] = pd.DataFrame()
    return out


def _latest_nav_date_from_reports() -> tuple[str, str]:
    candidates = [
        _latest_file("基金雷达扫描结果.xlsx"),
        _latest_file("短期异动雷达.xlsx"),
        _latest_file("历史时点观察池.xlsx"),
    ]
    max_dt: datetime | None = None
    source = ""
    date_col_pattern = re.compile(r"(净值日期|结束日期|最新可用净值日期|实际卖出净值日期|日期)")
    for path in [p for p in candidates if p is not None]:
        for df in _read_excel_sheets(path).values():
            if df.empty:
                continue
            for col in df.columns:
                if not date_col_pattern.search(str(col)):
                    continue
                parsed = pd.to_datetime(df[col], errors="coerce")
                if parsed.dropna().empty:
                    continue
                cur = parsed.max().to_pydatetime()
                if max_dt is None or cur > max_dt:
                    max_dt = cur
                    source = str(path)
    return (max_dt.strftime("%Y-%m-%d") if max_dt else "", source)


def _failure_rows_from_reports() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in project_path("reports").rglob("*.xlsx"):
        if not _valid_file(path):
            continue
        try:
            xf = pd.ExcelFile(path)
        except Exception:
            continue
        for sheet in xf.sheet_names:
            if not re.search(r"(失败|异常|failure|error)", sheet, flags=re.I):
                continue
            try:
                df = pd.read_excel(path, sheet_name=sheet)
            except Exception:
                continue
            rows.append(
                {
                    "文件": str(path),
                    "sheet": sheet,
                    "失败记录数": int(len(df)),
                    "是否持仓相关": "是" if "持仓" in sheet else "否",
                }
            )
    return pd.DataFrame(rows)


def _log_error_summary() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    log_roots = [project_path("logs"), project_path("data", "reports")]
    pattern = re.compile(r"(ERROR|Exception|Traceback|failed|失败|异常)", re.I)
    for root in log_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.log"):
            if not _valid_file(path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            hits = pattern.findall(text)
            if hits:
                rows.append(
                    {
                        "日志文件": str(path),
                        "错误/异常行数估算": len(hits),
                        "最后修改时间": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
    return pd.DataFrame(rows)


def _cache_status(as_of: str, stale_days: int = 7) -> pd.DataFrame:
    roots = [project_path("data", "cache"), project_path("data", "raw")]
    rows: list[dict[str, Any]] = []
    today = parse_date(as_of) or datetime.now()
    for root in roots:
        files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
        latest_mtime = max((p.stat().st_mtime for p in files), default=None)
        latest_text = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M:%S") if latest_mtime else ""
        age = (today - datetime.fromtimestamp(latest_mtime)).days if latest_mtime else None
        rows.append(
            {
                "目录": str(root),
                "文件数": len(files),
                "最新缓存修改时间": latest_text,
                "缓存年龄天数": age if age is not None else "",
                "状态": "正常" if age is not None and age <= stale_days else ("无缓存" if age is None else "可能过旧"),
            }
        )
    return pd.DataFrame(rows)


def _run_guard_status(as_of: str) -> pd.DataFrame:
    path = project_path("reports", "daily", as_of, "run_guard.json")
    if not path.exists():
        return pd.DataFrame([{"步骤": "run_guard", "状态": "缺失", "说明": str(path)}])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return pd.DataFrame([{"步骤": "run_guard", "状态": "读取失败", "说明": str(exc)}])
    steps = data.get("steps", {})
    rows = []
    for step in EXPECTED_DAILY_STEPS:
        item = steps.get(step, {})
        rows.append(
            {
                "步骤": step,
                "状态": item.get("status", "missing"),
                "开始时间": item.get("started_at", ""),
                "结束时间": item.get("finished_at", ""),
                "耗时秒": item.get("elapsed_sec", ""),
                "输出存在": item.get("output_exists", ""),
            }
        )
    return pd.DataFrame(rows)


def build_health_report(as_of: str | None = None) -> dict[str, pd.DataFrame]:
    date_text = as_of or today_str()
    latest_nav, nav_source = _latest_nav_date_from_reports()
    parsed_nav = parse_date(latest_nav)
    parsed_as_of = parse_date(date_text) or datetime.now()
    nav_age = (parsed_as_of - parsed_nav).days if parsed_nav else None

    failure_rows = _failure_rows_from_reports()
    log_errors = _log_error_summary()
    cache = _cache_status(date_text)
    guard = _run_guard_status(date_text)

    nav_status = "正常"
    if nav_age is None:
        nav_status = "未知"
    elif nav_age > 5:
        nav_status = "过旧"
    elif nav_age > 3:
        nav_status = "需关注"

    missing_steps = int((guard["状态"].astype(str) != "done").sum()) if "状态" in guard.columns else len(EXPECTED_DAILY_STEPS)
    overall = "正常"
    if nav_status in {"过旧", "未知"} or missing_steps > 0:
        overall = "需检查"
    if not failure_rows.empty or not log_errors.empty:
        overall = "有异常记录"

    summary = pd.DataFrame(
        [
            {"项目": "总体状态", "结果": overall, "说明": "健康检查只读取本地 reports/logs/cache，不触发外部接口"},
            {"项目": "最新净值日期", "结果": latest_nav or "未识别", "说明": f"来源: {nav_source}"},
            {"项目": "净值日期年龄", "结果": "" if nav_age is None else nav_age, "说明": nav_status},
            {"项目": "净值失败记录数", "结果": int(failure_rows["失败记录数"].sum()) if not failure_rows.empty else 0, "说明": "来自历史报告中失败/异常 sheet"},
            {"项目": "持仓抓取失败数量", "结果": int(failure_rows.loc[failure_rows["是否持仓相关"].eq("是"), "失败记录数"].sum()) if not failure_rows.empty else 0, "说明": "来自持仓相关失败 sheet"},
            {"项目": "接口/日志异常数量", "结果": int(log_errors["错误/异常行数估算"].sum()) if not log_errors.empty else 0, "说明": "来自 logs 和 data/reports"},
            {"项目": "今日任务未完成步骤", "结果": missing_steps, "说明": "来自 daily_runner run_guard.json"},
        ]
    )

    return {
        "健康摘要": summary,
        "失败记录摘要": failure_rows if not failure_rows.empty else pd.DataFrame([{"说明": "未发现失败/异常 sheet"}]),
        "接口日志异常": log_errors if not log_errors.empty else pd.DataFrame([{"说明": "未发现日志异常关键字"}]),
        "缓存状态": cache,
        "run_guard状态": guard,
    }


def run_health_check(as_of: str | None = None) -> HealthResult:
    date_text = as_of or today_str()
    output_dir = ensure_dir(project_path("reports", "health", date_text))
    sheets = build_health_report(date_text)
    excel = write_excel(output_dir / "health_report.xlsx", sheets)
    markdown = write_markdown(output_dir / "health_report.md", f"FundRadar 数据健康检查 {date_text}", sheets)
    return HealthResult(as_of=date_text, output_dir=output_dir, markdown=markdown, excel=excel)

