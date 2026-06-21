from __future__ import annotations

import re

import pandas as pd

from ..utils import normalize_code


FUND_CODE_COL = "基金代码"
FUND_NAME_COL = "基金名称"
MERGE_NOTE_COL = "份额合并提示"


def format_fund_codes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if str(col).strip() == FUND_CODE_COL:
            out[col] = out[col].map(lambda x: normalize_code(x) if pd.notna(x) and str(x).strip() != "" else "")
            out[col] = out[col].astype("string")
    return out


def normalize_fund_share_name(name: object) -> str:
    text = str(name or "").strip()
    text = re.sub(r"\s*[（(]?(A|C|I|E)类?[）)]?\s*$", "", text, flags=re.I)
    text = re.sub(r"\s*(A|C|I|E)\s*$", "", text, flags=re.I)
    text = re.sub(r"\s*[（(]?LOF[）)]?\s*$", "", text, flags=re.I)
    return re.sub(r"\s+", "", text)


def share_priority(name: object) -> int:
    text = str(name or "").strip()
    if re.search(r"[（(]?A类?[）)]?\s*$", text, flags=re.I) or re.search(r"A\s*$", text, flags=re.I):
        return 0
    if re.search(r"[（(]?C类?[）)]?\s*$", text, flags=re.I) or re.search(r"C\s*$", text, flags=re.I):
        return 1
    if re.search(r"[（(]?(I|E)类?[）)]?\s*$", text, flags=re.I) or re.search(r"(I|E)\s*$", text, flags=re.I):
        return 2
    return 3


def deduplicate_fund_display(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = format_fund_codes(df)
    if FUND_NAME_COL not in out.columns:
        return out
    working = out.copy()
    working["_display_order"] = range(len(working))
    working["_fund_key"] = working[FUND_NAME_COL].map(normalize_fund_share_name)
    working["_share_priority"] = working[FUND_NAME_COL].map(share_priority)
    group_sizes = working.groupby("_fund_key", dropna=False).size()
    chosen = (
        working.sort_values(["_fund_key", "_share_priority", "_display_order"])
        .groupby("_fund_key", dropna=False, as_index=False)
        .head(1)
        .sort_values("_display_order")
        .copy()
    )
    chosen[MERGE_NOTE_COL] = chosen["_fund_key"].map(lambda key: "已合并A/C等份额" if int(group_sizes.get(key, 1)) > 1 else "")
    return chosen.drop(columns=["_display_order", "_fund_key", "_share_priority"], errors="ignore").reset_index(drop=True)

