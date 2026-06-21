from __future__ import annotations

import logging
import re
from collections import defaultdict

import pandas as pd

from .data_loader import DataLoader
from .utils import normalize_code


KNOWN_COMPANY_PREFIXES = [
    "易方达", "华夏", "广发", "南方", "嘉实", "富国", "汇添富", "招商", "博时", "鹏华", "工银瑞信", "景顺长城",
    "交银施罗德", "中欧", "兴证全球", "银华", "华安", "国泰", "天弘", "建信", "华宝", "信澳", "财通", "德邦",
    "红土创新", "永赢", "中航", "安信", "华富", "湘财", "浦银安盛", "长城", "国投瑞银", "农银汇理", "摩根",
    "诺安", "海富通", "大成", "万家", "融通", "国联安", "中银", "兴业", "创金合信", "平安", "前海开源",
]


def normalize_company_name(company: str) -> str:
    text = str(company or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", "", text)
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"基金管理股份有限公司$", "", text)
    text = re.sub(r"(股份)?基金管理(有限责任公司|有限公司|公司)$", "", text)
    text = re.sub(r"资产管理(有限责任公司|有限公司|公司)$", "", text)
    text = re.sub(r"管理(有限责任公司|有限公司|公司)$", "", text)
    text = re.sub(r"(有限责任公司|有限公司|公司)$", "", text)
    return text


def infer_company_from_name(name: str) -> str:
    text = str(name or "").strip()
    for prefix in sorted(KNOWN_COMPANY_PREFIXES, key=len, reverse=True):
        if text.startswith(prefix):
            return prefix
    m = re.match(r"^([\u4e00-\u9fff]{2,8}?)(?:成长|创新|科技|价值|质量|景气|先锋|远见|精选|优选|智能|周期|新能源|数字|事件|行业)", text)
    if m:
        return m.group(1)
    return text[:4] if text else ""


def enrich_identity(df: pd.DataFrame, loader: DataLoader, logger: logging.Logger | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    if "基金公司" not in out.columns:
        out["基金公司"] = ""
    if "基金经理" not in out.columns:
        out["基金经理"] = ""
    log = logger or logging.getLogger("fund_radar")
    for idx, row in out.iterrows():
        code = normalize_code(row.get("基金代码"))
        company = str(row.get("基金公司") or "").strip()
        manager = str(row.get("基金经理") or "").strip()
        if not (company and manager):
            try:
                profile = loader.fetch_fund_profile(code)
                if not company:
                    company = str(profile.get("基金公司") or "").strip()
                if not manager:
                    manager = str(profile.get("基金经理") or "").strip()
            except Exception as exc:  # noqa: BLE001
                log.debug("fund profile unavailable %s: %s", code, exc)
        if not company:
            company = infer_company_from_name(str(row.get("基金名称") or ""))
        out.at[idx, "基金公司"] = company
        out.at[idx, "基金公司标准名"] = normalize_company_name(company)
        out.at[idx, "基金经理"] = manager
    return out


def build_diversified_watchlist(
    scored: pd.DataFrame,
    loader: DataLoader,
    target_n: int,
    source_top_n: int = 10,
    max_per_company: int = 2,
    max_per_manager: int = 2,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    if scored is None or scored.empty or target_n <= 0:
        return pd.DataFrame()

    # Start from the practical-watchlist depth, then continue down the full natural ranking
    # if constraints leave the auxiliary view under-filled.
    primary = scored.head(max(source_top_n, target_n)).copy()
    tail = scored.iloc[len(primary):].copy()
    candidates = pd.concat([primary, tail], ignore_index=True)
    candidates = enrich_identity(candidates, loader, logger)

    selected_rows = []
    company_count: dict[str, int] = defaultdict(int)
    manager_count: dict[str, int] = defaultdict(int)
    skipped_count = 0

    for _, row in candidates.iterrows():
        company_key = str(row.get("基金公司标准名") or normalize_company_name(str(row.get("基金公司") or ""))).strip()
        manager_key = str(row.get("基金经理") or "").strip()
        if company_key and company_count[company_key] >= max_per_company:
            skipped_count += 1
            continue
        if manager_key and manager_count[manager_key] >= max_per_manager:
            skipped_count += 1
            continue

        r = row.copy()
        r["分散池说明"] = "入选"
        selected_rows.append(r)
        if company_key:
            company_count[company_key] += 1
        if manager_key:
            manager_count[manager_key] += 1
        if len(selected_rows) >= target_n:
            break

    out = pd.DataFrame(selected_rows).reset_index(drop=True)
    if not out.empty:
        out["分散池排名"] = range(1, len(out) + 1)
        if len(out) < target_n:
            out["分散池说明"] = out["分散池说明"] + f"；因分散约束未填满，目标{target_n}只，实际{len(out)}只，跳过{skipped_count}只"
    return out
