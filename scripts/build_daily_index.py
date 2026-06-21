from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401

import pandas as pd

from fund_radar.report import write_excel, write_markdown
from fund_radar.utils import ensure_dir, normalize_code, project_path


def _read_sheet(path: Path, sheet_name: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame()


def _first_value(df: pd.DataFrame, labels: list[str]) -> str:
    if df.empty:
        return ""
    if {"项目", "结果"}.issubset(df.columns):
        for label in labels:
            hit = df[df["项目"].astype(str).str.contains(label, na=False)]
            if not hit.empty:
                return str(hit.iloc[0]["结果"])
    return ""


def _first_theme(df: pd.DataFrame, limit: int = 3) -> str:
    if df.empty:
        return ""
    theme_col = next((c for c in df.columns if "主题" in str(c)), df.columns[0])
    values = [str(v) for v in df[theme_col].dropna().head(limit).tolist() if str(v).strip()]
    return "、".join(values)


def _normalize_fund_name(name: str) -> str:
    text = str(name or "").strip()
    for suffix in ["A类", "C类", "I类", "E类", "A", "C", "I", "E"]:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


def _share_priority(name: str) -> int:
    text = str(name or "").strip().upper()
    if text.endswith("A") or text.endswith("A类"):
        return 0
    if text.endswith("C") or text.endswith("C类"):
        return 1
    return 2


def _fund_sample(df: pd.DataFrame, limit: int = 3) -> str:
    if df.empty:
        return ""
    code_col = next((c for c in df.columns if "代码" in str(c)), None)
    name_col = next((c for c in df.columns if "名称" in str(c)), None)
    merged: dict[str, tuple[int, int, str]] = {}
    scan = df.head(max(limit * 5, limit))
    for idx, (_, row) in enumerate(scan.iterrows()):
        code = normalize_code(row.get(code_col, "")) if code_col else ""
        name = str(row.get(name_col, "")).strip() if name_col else ""
        key = _normalize_fund_name(name) or code
        text = f"{code} {name}".strip()
        priority = _share_priority(name)
        old = merged.get(key)
        if text and (old is None or (priority, idx) < (old[0], old[1])):
            merged[key] = (priority, idx, text)
    selected = sorted(merged.values(), key=lambda item: item[1])[:limit]
    return "；".join(item[2] for item in selected)


def _rotation_evidence(df: pd.DataFrame) -> str:
    if df.empty:
        return "否"
    text = " ".join(df.astype(str).fillna("").head(20).to_numpy().ravel().tolist())
    if any(token in text for token in ["暂无", "无明确", "首期", "无数据"]):
        return "否"
    return "是"


def _health_status(date_text: str) -> str:
    path = project_path("reports", "health", date_text, "health_report.xlsx")
    if not path.exists():
        return "未生成"
    df = _read_sheet(path, "健康摘要")
    return _first_value(df, ["总体状态"]) or "未知"


def _row_from_daily_report(path: Path) -> dict[str, Any]:
    date_text = path.parent.name
    summary = _read_sheet(path, "晨报摘要")
    core = _read_sheet(path, "主线状态")
    secondary = _read_sheet(path, "次级扩散方向")
    crowding = _read_sheet(path, "拥挤风险")
    new_star = _read_sheet(path, "新星基金Top10")
    allocation = _read_sheet(path, "V3仓位建议")
    rotation = _read_sheet(path, "V4轮动状态")

    return {
        "日期": date_text,
        "核心主线": _first_value(summary, ["当前核心主线"]) or _first_theme(core, 2),
        "次级方向": _first_value(summary, ["次级扩散方向"]) or _first_theme(secondary, 3),
        "高拥挤主题": _first_value(summary, ["高拥挤风险"]) or _first_theme(crowding, 3),
        "新星Top基金": _fund_sample(new_star, 3),
        "V3主仓位": _fund_sample(allocation, 3),
        "是否有轮动证据": _rotation_evidence(rotation),
        "数据健康状态": _health_status(date_text),
        "对应日报路径": str(path),
    }


def build_daily_index() -> tuple[Path, Path, pd.DataFrame]:
    root = project_path("reports", "daily")
    files = sorted([p for p in root.glob("20*/daily_report.xlsx") if p.exists() and not p.name.startswith("~$")])
    rows = [_row_from_daily_report(path) for path in files]
    df = pd.DataFrame(rows)
    out_dir = ensure_dir(root)
    excel = write_excel(out_dir / "index.xlsx", {"日报索引": df})
    markdown = write_markdown(out_dir / "index.md", "FundRadar 日报历史索引", {"日报索引": df})
    return excel, markdown, df


def main() -> None:
    excel, markdown, df = build_daily_index()
    print(f"Daily index rows: {len(df)}")
    print(f"Markdown: {markdown}")
    print(f"Excel: {excel}")


if __name__ == "__main__":
    main()
