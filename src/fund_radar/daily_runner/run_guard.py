from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from ..utils import ensure_dir, parse_date, project_path, today_str


STEP_NAMES = ["market_scan", "short_term_radar", "v3_full", "v3_tracker", "v4_full", "daily_report"]


def normalize_run_date(value: str | None = None) -> str:
    if value is None or str(value).lower() == "today":
        return today_str()
    parsed = parse_date(value)
    return parsed.strftime("%Y-%m-%d") if parsed else today_str()


def daily_report_dir(as_of: str) -> Path:
    return project_path("reports", "daily", as_of)


def guard_state_path(as_of: str) -> Path:
    return daily_report_dir(as_of) / "run_guard.json"


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _month_text(as_of: str) -> str:
    parsed = parse_date(as_of)
    return f"{parsed:%Y-%m}" if parsed else as_of[:7]


def _read_sheet(path: Path, sheet_name: str | int = 0) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame()


def _latest(paths: list[Path]) -> Path | None:
    valid = [p for p in paths if p.exists() and not p.name.startswith("~$")]
    return max(valid, key=lambda p: p.stat().st_mtime) if valid else None


def _date_from_path(path: Path) -> datetime | None:
    for part in reversed(path.parts):
        try:
            return datetime.strptime(part[:10], "%Y-%m-%d")
        except ValueError:
            continue
    return None


@lru_cache(maxsize=32)
def _latest_report_file(filename: str, as_of: str) -> Path | None:
    parsed = parse_date(as_of)
    candidates = []
    for path in project_path("reports").rglob(filename):
        if not path.exists() or path.name.startswith("~$") or "time_machine" in path.parts:
            continue
        dt = _date_from_path(path)
        if parsed is None or dt is None or dt <= parsed:
            candidates.append(path)
    return _latest(candidates)


@lru_cache(maxsize=32)
def _latest_dir(root: Path, as_of: str) -> Path | None:
    if not root.exists():
        return None
    parsed = parse_date(as_of)
    candidates = []
    for path in root.glob("20*"):
        if not path.is_dir():
            continue
        dt = _date_from_path(path)
        if parsed is None or dt is None or dt <= parsed:
            candidates.append(path)
    return _latest(candidates)


@lru_cache(maxsize=16)
def latest_nav_date(as_of: str) -> str | None:
    candidates = [
        _latest_report_file("短期异动雷达.xlsx", as_of),
        _latest_report_file("基金雷达扫描结果.xlsx", as_of),
    ]
    dates: list[pd.Timestamp] = []
    for path in [p for p in candidates if p is not None]:
        try:
            sheets = pd.ExcelFile(path).sheet_names
        except Exception:
            continue
        for sheet in sheets[:8]:
            df = _read_sheet(path, sheet)
            if "最新净值日期" not in df.columns:
                continue
            values = pd.to_datetime(df["最新净值日期"], errors="coerce").dropna()
            if not values.empty:
                dates.append(values.max())
    if not dates:
        return None
    return max(dates).strftime("%Y-%m-%d")


def daily_report_complete(as_of: str) -> bool:
    root = daily_report_dir(as_of)
    return (root / "daily_report.md").exists() and (root / "daily_report.xlsx").exists()


def tracker_recorded(as_of: str) -> bool:
    parsed = parse_date(as_of)
    if parsed is None:
        return False
    path = project_path("reports", "v3_tracker", f"{parsed:%Y-%m}", "daily_log.xlsx")
    if not path.exists():
        return False
    df = _read_sheet(path, "portfolio_log")
    if df.empty or "记录日期" not in df.columns:
        return False
    dates = pd.to_datetime(df["记录日期"], errors="coerce").dropna().dt.strftime("%Y-%m-%d")
    return as_of in set(dates)


def step_output_path(step: str, as_of: str) -> Path | None:
    month = _month_text(as_of)
    exact_paths = {
        "market_scan": project_path("reports", "v1_market", as_of, "基金雷达扫描结果.xlsx"),
        "short_term_radar": project_path("reports", "v1_1_short_term", as_of, "短期异动雷达.xlsx"),
        "v3_full": project_path("reports", "v3", as_of, "v3_summary.md"),
        "v3_tracker": project_path("reports", "v3_tracker", month, "daily_log.xlsx"),
        "v4_full": project_path("reports", "v4", as_of, "v4_summary.md"),
        "daily_report": project_path("reports", "daily", as_of, "daily_report.md"),
    }
    exact = exact_paths.get(step)
    if exact and exact.exists():
        return exact
    latest_paths = {
        "market_scan": _latest_report_file("基金雷达扫描结果.xlsx", as_of),
        "short_term_radar": _latest_report_file("短期异动雷达.xlsx", as_of),
        "v3_full": (_latest_dir(project_path("reports", "v3"), as_of) or Path("")) / "v3_summary.md",
        "v3_tracker": project_path("reports", "v3_tracker", month, "daily_log.xlsx"),
        "v4_full": (_latest_dir(project_path("reports", "v4"), as_of) or Path("")) / "v4_summary.md",
        "daily_report": exact_paths["daily_report"],
    }
    candidate = latest_paths.get(step)
    return candidate if candidate and candidate.exists() else None


def step_output_exists(step: str, as_of: str) -> bool:
    if step == "v3_tracker":
        return tracker_recorded(as_of) or bool(step_output_path(step, as_of))
    if step == "daily_report":
        return daily_report_complete(as_of)
    return bool(step_output_path(step, as_of))


def load_state(as_of: str) -> dict[str, Any]:
    path = guard_state_path(as_of)
    if not path.exists():
        return {"date": as_of, "latest_nav_date": latest_nav_date(as_of), "steps": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("date", as_of)
    data.setdefault("latest_nav_date", latest_nav_date(as_of))
    data.setdefault("steps", {})
    return data


def save_state(state: dict[str, Any], as_of: str | None = None) -> Path:
    run_date = as_of or state.get("date") or today_str()
    path = guard_state_path(run_date)
    ensure_dir(path.parent)
    state["date"] = run_date
    state["updated_at"] = _now_text()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def initialize_state(as_of: str) -> dict[str, Any]:
    state = load_state(as_of)
    state["date"] = as_of
    state["latest_nav_date"] = latest_nav_date(as_of)
    state.setdefault("steps", {})
    return state


def mark_step_started(as_of: str, step: str, command: list[str]) -> None:
    state = initialize_state(as_of)
    state["steps"][step] = {
        "status": "running",
        "started_at": _now_text(),
        "finished_at": None,
        "elapsed_sec": None,
        "output_exists": step_output_exists(step, as_of),
        "command": " ".join(command),
    }
    save_state(state, as_of)


def mark_step_done(as_of: str, step: str, elapsed_sec: float) -> None:
    state = initialize_state(as_of)
    current = state["steps"].setdefault(step, {})
    current.update(
        {
            "status": "done",
            "finished_at": _now_text(),
            "elapsed_sec": round(float(elapsed_sec), 3),
            "output_exists": step_output_exists(step, as_of),
        }
    )
    state["latest_nav_date"] = latest_nav_date(as_of)
    save_state(state, as_of)


def mark_step_skipped(as_of: str, step: str, reason: str) -> None:
    state = initialize_state(as_of)
    state["steps"][step] = {
        "status": "done",
        "started_at": None,
        "finished_at": _now_text(),
        "elapsed_sec": 0.0,
        "output_exists": step_output_exists(step, as_of),
        "skipped": True,
        "reason": reason,
    }
    save_state(state, as_of)


def mark_step_failed(as_of: str, step: str, elapsed_sec: float, reason: str) -> None:
    state = initialize_state(as_of)
    current = state["steps"].setdefault(step, {})
    current.update(
        {
            "status": "failed",
            "finished_at": _now_text(),
            "elapsed_sec": round(float(elapsed_sec), 3),
            "output_exists": step_output_exists(step, as_of),
            "reason": reason,
        }
    )
    save_state(state, as_of)


def step_status(as_of: str, step: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or initialize_state(as_of)
    current = dict(state.get("steps", {}).get(step, {}))
    output_exists = step_output_exists(step, as_of)
    current.setdefault("status", "done" if output_exists else "unknown")
    current["output_exists"] = output_exists
    if output_exists and not state.get("steps", {}).get(step):
        current["inferred"] = True
    return current


def should_skip_step(as_of: str, step: str, force: bool = False) -> tuple[bool, str]:
    if force:
        return False, "force"
    state = initialize_state(as_of)
    current_nav = latest_nav_date(as_of)
    state_nav = state.get("latest_nav_date")
    status = state.get("steps", {}).get(step, {}).get("status")
    output_exists = step_output_exists(step, as_of)
    if status == "done" and output_exists and current_nav and state_nav == current_nav:
        return True, "already done today, latest nav date unchanged"
    if output_exists and current_nav and (not state_nav or state_nav == current_nav):
        return True, "existing output found, latest nav date unchanged"
    return False, "not done or nav changed"


def status_lines(as_of: str) -> list[str]:
    state = initialize_state(as_of)
    lines = [f"date: {as_of}", f"latest_nav_date: {state.get('latest_nav_date') or 'unknown'}", ""]
    for step in STEP_NAMES:
        status = step_status(as_of, step, state)
        detail = status.get("status", "unknown")
        if status.get("inferred"):
            detail += "(inferred)"
        if status.get("elapsed_sec") is not None:
            detail += f" elapsed={status['elapsed_sec']}s"
        if status.get("output_exists"):
            detail += " output_exists=true"
        lines.append(f"{step}: {detail}")
    return lines
