from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from .utils import ensure_dir, safe_filename


def configure_matplotlib(config: dict) -> None:
    fonts = config.get("reports", {}).get("font_family", ["Microsoft YaHei", "SimHei"])
    plt.rcParams["font.sans-serif"] = fonts
    plt.rcParams["axes.unicode_minus"] = False


def write_excel(path: str | Path, sheets: dict[str, pd.DataFrame]) -> Path:
    p = Path(path)
    ensure_dir(p.parent)
    with pd.ExcelWriter(p, engine="openpyxl") as writer:
        for name, df in sheets.items():
            sheet = safe_filename(name, 31) or "Sheet1"
            (df if df is not None else pd.DataFrame()).to_excel(writer, sheet_name=sheet, index=False)
    return p


def bar_chart(df: pd.DataFrame, x_col: str, y_col: str, title: str, path: str | Path, top_n: int = 30, config: dict | None = None) -> Path:
    if config:
        configure_matplotlib(config)
    p = Path(path)
    ensure_dir(p.parent)
    plot_df = df[[x_col, y_col]].dropna().head(top_n).copy()
    plot_df[y_col] = pd.to_numeric(plot_df[y_col], errors="coerce")
    plot_df = plot_df.dropna().iloc[::-1]
    fig_h = max(4, min(12, 0.32 * len(plot_df) + 1.5))
    plt.figure(figsize=(10, fig_h))
    plt.barh(plot_df[x_col].astype(str), plot_df[y_col])
    plt.title(title)
    plt.xlabel(y_col)
    plt.tight_layout()
    plt.savefig(p, dpi=int((config or {}).get("reports", {}).get("chart_dpi", 160)))
    plt.close()
    return p


def line_chart(df: pd.DataFrame, x_col: str, y_cols: list[str], title: str, path: str | Path, config: dict | None = None) -> Path:
    if config:
        configure_matplotlib(config)
    p = Path(path)
    ensure_dir(p.parent)
    plt.figure(figsize=(11, 5))
    for col in y_cols:
        if col in df.columns:
            plt.plot(pd.to_datetime(df[x_col]), pd.to_numeric(df[col], errors="coerce"), marker="o", label=col)
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(p, dpi=int((config or {}).get("reports", {}).get("chart_dpi", 160)))
    plt.close()
    return p


def markdown_table(df: pd.DataFrame, cols: list[str] | None = None, max_rows: int = 20) -> str:
    if df is None or df.empty:
        return "无数据\n"
    use = df[cols].copy() if cols else df.copy()
    return use.head(max_rows).to_markdown(index=False)


def write_markdown(path: str | Path, title: str, sections: dict[str, Any]) -> Path:
    p = Path(path)
    ensure_dir(p.parent)
    lines = [f"# {title}", ""]
    for heading, content in sections.items():
        lines += [f"## {heading}", ""]
        if isinstance(content, pd.DataFrame):
            lines.append(markdown_table(content))
        else:
            lines.append(str(content))
        lines.append("")
    p.write_text("\n".join(lines), encoding="utf-8")
    return p
