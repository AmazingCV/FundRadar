from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
import os

import pandas as pd

from ..data_loader import DataLoader
from ..utils import load_config, load_yaml, normalize_code, project_path
from .run_guard import (
    STEP_NAMES,
    mark_step_done,
    mark_step_failed,
    mark_step_started,
    latest_nav_date,
    normalize_run_date,
    save_state,
    should_skip_step,
    status_lines,
    initialize_state,
    mark_step_skipped,
)

PROXY_ENV_NAMES = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]
FALLBACK_PROBE_CODES = ["002112", "001416", "011949"]


@dataclass(frozen=True)
class DailyStep:
    key: str
    label: str
    command: list[str]


def _python_script(script: str, *args: str) -> list[str]:
    return [sys.executable, str(project_path("scripts", script)), *args]


def _disable_blocking_proxy_env() -> None:
    for name in PROXY_ENV_NAMES:
        if "127.0.0.1:9" in str(os.environ.get(name, "")):
            os.environ.pop(name, None)


def _probe_codes() -> list[str]:
    codes: list[str] = []
    try:
        data = load_yaml("config/fund_list.yaml")
        for row in data.get("watchlist", []):
            code = normalize_code(row.get("code", ""))
            if code and code not in codes:
                codes.append(code)
    except Exception:
        pass
    for code in FALLBACK_PROBE_CODES:
        if code not in codes:
            codes.append(code)
    return codes[:8]


def resolve_data_date(run_date: str) -> str:
    _disable_blocking_proxy_env()
    loader = DataLoader(load_config())
    dates: list[pd.Timestamp] = []
    for code in _probe_codes():
        try:
            nav = loader.fetch_nav(code, force=True)
            date_col = next((col for col in nav.columns if "日期" in str(col)), None)
            if date_col is None:
                continue
            latest = pd.to_datetime(nav[date_col], errors="coerce").max()
            if pd.notna(latest):
                dates.append(latest)
        except Exception:
            continue
    if dates:
        return max(dates).strftime("%Y-%m-%d")
    return latest_nav_date(run_date) or run_date


def build_daily_steps(limit: int | None = None, data_date: str | None = None) -> list[DailyStep]:
    limit_args = ["--limit", str(limit)] if limit is not None else []
    date_text = data_date or "today"
    return [
        DailyStep("market_scan", "market_scan", _python_script("run_market_scan.py", "--as-of", date_text, *limit_args)),
        DailyStep("short_term_radar", "short_term_radar", _python_script("run_short_term_radar.py", "--as-of", date_text, *limit_args)),
        DailyStep("v3_full", "v3_full", _python_script("run_v3_full.py", "--date", date_text, *limit_args)),
        DailyStep("v3_tracker", "v3_tracker", _python_script("run_v3_tracker.py", "--date", date_text, *limit_args)),
        DailyStep("v4_full", "v4_full", _python_script("run_v4_full.py", "--date", date_text, *limit_args)),
        DailyStep("daily_report", "daily_report", _python_script("run_daily_report.py", "--date", date_text)),
    ]


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m{sec:.1f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h{int(minutes)}m{sec:.1f}s"


def _start_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_step(as_of: str, step: DailyStep, force: bool = False) -> None:
    skip, reason = should_skip_step(as_of, step.key, force=force)
    if skip:
        print(f"[SKIP] {step.label} reason={reason}", flush=True)
        mark_step_skipped(as_of, step.key, reason)
        return
    print(f"[START] {step.label} {_start_text()}", flush=True)
    print(" ".join(step.command), flush=True)
    mark_step_started(as_of, step.key, step.command)
    start = time.perf_counter()
    env = os.environ.copy()
    env["FUND_RADAR_NAV_TARGET_DATE"] = as_of
    for name in PROXY_ENV_NAMES:
        if "127.0.0.1:9" in str(env.get(name, "")):
            env.pop(name, None)
    result = subprocess.run(step.command, cwd=project_path(), text=True, env=env)
    elapsed = time.perf_counter() - start
    if result.returncode != 0:
        reason_text = f"exit={result.returncode}"
        mark_step_failed(as_of, step.key, elapsed, reason_text)
        print(f"[FAIL] {step.label} reason={reason_text} elapsed={_format_duration(elapsed)}", flush=True)
        raise RuntimeError(f"{step.label} failed: {reason_text}")
    mark_step_done(as_of, step.key, elapsed)
    print(f"[DONE] {step.label} elapsed={_format_duration(elapsed)}", flush=True)


def _steps_for(step_name: str | None, limit: int | None, data_date: str | None) -> list[DailyStep]:
    steps = build_daily_steps(limit=limit, data_date=data_date)
    if step_name is None:
        return steps
    selected = [step for step in steps if step.key == step_name]
    if not selected:
        valid = ", ".join(STEP_NAMES)
        raise ValueError(f"Unknown step: {step_name}. Valid steps: {valid}")
    return selected


def print_status(as_of: str) -> None:
    initialize_state(as_of)
    for line in status_lines(as_of):
        print(line, flush=True)


def run_daily_all(
    limit: int | None = None,
    force: bool = False,
    report_only: bool = False,
    status: bool = False,
    step: str | None = None,
) -> None:
    run_date = normalize_run_date("today")
    if status:
        status_date = latest_nav_date(run_date) or run_date
        print(f"run_date: {run_date}", flush=True)
        print_status(status_date)
        return
    data_date = resolve_data_date(run_date)
    as_of = data_date
    if data_date != run_date:
        print(f"[DATA_DATE] latest nav date={data_date}; report folders use data date, run date={run_date}", flush=True)
    else:
        print(f"[DATA_DATE] latest nav date={data_date}", flush=True)
    if force:
        print("[FORCE] Full recompute enabled. This may take a long time.", flush=True)
    if report_only:
        step = "daily_report"
        force = True
        print("[REPORT_ONLY] Rebuild daily_report only.", flush=True)
    for current_step in _steps_for(step, limit=limit, data_date=data_date):
        run_step(as_of, current_step, force=force)
    state = initialize_state(as_of)
    save_state(state, as_of)
    print("[DONE] daily runner", flush=True)
