from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def project_path(*parts: str | Path) -> Path:
    return PROJECT_ROOT.joinpath(*map(Path, parts))


def load_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = project_path(p)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def load_config(path: str | Path = "config/config.yaml") -> dict[str, Any]:
    return load_yaml(path)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = project_path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def setup_logging(name: str = "fund_radar", log_dir: str | Path = "data/reports") -> logging.Logger:
    ensure_dir(log_dir)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    log_path = project_path(log_dir, f"{datetime.now():%Y%m%d}.log")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    return logger


def normalize_code(code: Any) -> str:
    return str(code).strip().split(".")[0].zfill(6)


def normalize_name_for_ac(name: str) -> str:
    s = str(name or "")
    s = re.sub(r"[\s\-_/（(]?(A|B|C|D|E|I|Y|人民币|美元|后端|前端|类|份额)[）)]?$", "", s, flags=re.I)
    s = re.sub(r"(A|B|C|D|E|I|Y)$", "", s, flags=re.I)
    return s.strip()


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def parse_date(value: Any | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.strptime(str(value)[:10], "%Y-%m-%d")


def safe_filename(text: str, max_len: int = 80) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "_", str(text))
    return text[:max_len].strip("_")


def cache_key(*parts: Any) -> str:
    return hashlib.md5("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:16]


def retry_call(
    func: Callable[[], Any],
    retry_times: int = 3,
    sleep_seconds: float = 0.5,
    logger: logging.Logger | None = None,
    what: str = "call",
) -> Any:
    last_err: Exception | None = None
    for i in range(max(1, retry_times)):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - external data interfaces are noisy.
            last_err = exc
            if logger:
                logger.warning("%s failed %s/%s: %s", what, i + 1, retry_times, exc)
            if i < retry_times - 1:
                time.sleep(sleep_seconds * (i + 1))
    if last_err:
        raise last_err
    raise RuntimeError(f"{what} failed")


def first_existing(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    colset = {str(c): c for c in columns}
    for cand in candidates:
        if cand in colset:
            return colset[cand]
    for col in columns:
        for cand in candidates:
            if cand in str(col):
                return str(col)
    return None


def month_dir(root: str | Path, dt: str | datetime | date | None = None) -> Path:
    parsed = parse_date(dt) if dt else datetime.now()
    assert parsed is not None
    return ensure_dir(Path(root) / f"{parsed:%Y-%m}")
