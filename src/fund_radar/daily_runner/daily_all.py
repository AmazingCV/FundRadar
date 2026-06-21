from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime

from ..utils import project_path
from .run_guard import (
    STEP_NAMES,
    mark_step_done,
    mark_step_failed,
    mark_step_started,
    normalize_run_date,
    save_state,
    should_skip_step,
    status_lines,
    initialize_state,
    mark_step_skipped,
)


@dataclass(frozen=True)
class DailyStep:
    key: str
    label: str
    command: list[str]


def _python_script(script: str, *args: str) -> list[str]:
    return [sys.executable, str(project_path("scripts", script)), *args]


def build_daily_steps(limit: int | None = None) -> list[DailyStep]:
    limit_args = ["--limit", str(limit)] if limit is not None else []
    return [
        DailyStep("market_scan", "market_scan", _python_script("run_market_scan.py", *limit_args)),
        DailyStep("short_term_radar", "short_term_radar", _python_script("run_short_term_radar.py", *limit_args)),
        DailyStep("v3_full", "v3_full", _python_script("run_v3_full.py", *limit_args)),
        DailyStep("v3_tracker", "v3_tracker", _python_script("run_v3_tracker.py", "--date", "today", *limit_args)),
        DailyStep("v4_full", "v4_full", _python_script("run_v4_full.py", *limit_args)),
        DailyStep("daily_report", "daily_report", _python_script("run_daily_report.py", "--date", "today")),
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
    result = subprocess.run(step.command, cwd=project_path(), text=True)
    elapsed = time.perf_counter() - start
    if result.returncode != 0:
        reason_text = f"exit={result.returncode}"
        mark_step_failed(as_of, step.key, elapsed, reason_text)
        print(f"[FAIL] {step.label} reason={reason_text} elapsed={_format_duration(elapsed)}", flush=True)
        raise RuntimeError(f"{step.label} failed: {reason_text}")
    mark_step_done(as_of, step.key, elapsed)
    print(f"[DONE] {step.label} elapsed={_format_duration(elapsed)}", flush=True)


def _steps_for(step_name: str | None, limit: int | None) -> list[DailyStep]:
    steps = build_daily_steps(limit=limit)
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
    as_of = normalize_run_date("today")
    if status:
        print_status(as_of)
        return
    if force:
        print("[FORCE] Full recompute enabled. This may take a long time.", flush=True)
    if report_only:
        step = "daily_report"
        force = True
        print("[REPORT_ONLY] Rebuild daily_report only.", flush=True)
    for current_step in _steps_for(step, limit=limit):
        run_step(as_of, current_step, force=force)
    state = initialize_state(as_of)
    save_state(state, as_of)
    print("[DONE] daily runner", flush=True)
