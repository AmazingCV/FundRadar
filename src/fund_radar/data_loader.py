from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import ensure_dir, first_existing, load_config, normalize_code, project_path, retry_call


class DataLoader:
    def __init__(self, config: dict[str, Any] | None = None, logger: logging.Logger | None = None):
        self.config = config or load_config()
        self.logger = logger or logging.getLogger("fund_radar")
        cache_root = self.config.get("project", {}).get("cache_root", "data/cache")
        self.cache_root = ensure_dir(cache_root)
        self.raw_root = ensure_dir("data/raw")
        self.retry_times = int(self.config.get("data", {}).get("retry_times", 3))
        self.sleep_seconds = float(self.config.get("data", {}).get("request_sleep_seconds", 0.25))
        self.cache_expire_days = int(self.config.get("data", {}).get("cache_expire_days", 3))

    def _ak(self):
        try:
            import akshare as ak  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("缺少 akshare，请先安装 requirements.txt") from exc
        return ak

    def _is_cache_fresh(self, path: Path, expire_days: int | None = None) -> bool:
        if not path.exists():
            return False
        expire = self.cache_expire_days if expire_days is None else expire_days
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        return age <= timedelta(days=expire)

    def _read_csv(self, path: Path) -> pd.DataFrame:
        return pd.read_csv(path, dtype={"基金代码": str, "code": str})

    def fetch_fund_list(self, force: bool = False) -> pd.DataFrame:
        path = project_path(self.cache_root, "fund_name_em.csv")
        if not force and self._is_cache_fresh(path, 7):
            return self._read_csv(path)

        ak = self._ak()
        df = retry_call(lambda: ak.fund_name_em(), self.retry_times, self.sleep_seconds, self.logger, "fund_name_em")
        df = df.copy()
        code_col = first_existing(df.columns, ["基金代码", "代码", "fund_code"])
        name_col = first_existing(df.columns, ["基金简称", "基金名称", "简称", "名称"])
        type_col = first_existing(df.columns, ["基金类型", "类型"])
        if code_col is None or name_col is None:
            raise RuntimeError(f"fund_name_em 字段无法识别: {list(df.columns)}")
        out = pd.DataFrame(
            {
                "基金代码": df[code_col].map(normalize_code),
                "基金名称": df[name_col].astype(str),
                "基金类型": df[type_col].astype(str) if type_col else "",
            }
        ).drop_duplicates("基金代码")
        out.to_csv(path, index=False, encoding="utf-8-sig")
        return out

    def fetch_rank_table(self, force: bool = False) -> pd.DataFrame:
        path = project_path(self.cache_root, "fund_open_fund_rank_em.csv")
        if not force and self._is_cache_fresh(path, 1):
            return self._read_csv(path)
        ak = self._ak()

        def call():
            try:
                return ak.fund_open_fund_rank_em(symbol="全部")
            except TypeError:
                return ak.fund_open_fund_rank_em()

        df = retry_call(call, self.retry_times, self.sleep_seconds, self.logger, "fund_open_fund_rank_em")
        df = df.copy()
        code_col = first_existing(df.columns, ["基金代码", "代码"])
        name_col = first_existing(df.columns, ["基金简称", "基金名称", "简称", "名称"])
        type_col = first_existing(df.columns, ["基金类型", "类型"])
        if code_col is None:
            raise RuntimeError(f"rank table 字段无法识别: {list(df.columns)}")
        df["基金代码"] = df[code_col].map(normalize_code)
        if name_col and "基金名称" not in df.columns:
            df["基金名称"] = df[name_col].astype(str)
        if type_col and "基金类型" not in df.columns:
            df["基金类型"] = df[type_col].astype(str)
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return df

    def fetch_nav(self, code: str, force: bool = False) -> pd.DataFrame:
        code = normalize_code(code)
        path = project_path(self.cache_root, "nav", f"{code}.csv")
        ensure_dir(path.parent)
        if not force and path.exists():
            cached = self._normalize_nav(self._read_csv(path), code)
            target_date = os.environ.get("FUND_RADAR_NAV_TARGET_DATE")
            if target_date and not cached.empty:
                date_col = first_existing(cached.columns, ["净值日期", "鍑€鍊兼棩鏈?"])
                latest_cached = pd.to_datetime(cached[date_col], errors="coerce").max() if date_col else pd.NaT
                target_dt = pd.to_datetime(target_date, errors="coerce")
                if pd.notna(latest_cached) and pd.notna(target_dt) and latest_cached >= target_dt:
                    return cached
            elif not target_date:
                return cached

        ak = self._ak()

        def call_indicator(indicator: str):
            return ak.fund_open_fund_info_em(symbol=code, indicator=indicator)

        last_err: Exception | None = None
        for indicator in ("累计净值走势", "单位净值走势"):
            try:
                df = retry_call(lambda ind=indicator: call_indicator(ind), self.retry_times, self.sleep_seconds, self.logger, f"nav {code} {indicator}")
                out = self._normalize_nav(df, code)
                if not out.empty:
                    out.to_csv(path, index=False, encoding="utf-8-sig")
                    time.sleep(self.sleep_seconds)
                    return out
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                self.logger.warning("fetch_nav %s %s failed: %s", code, indicator, exc)
        raise RuntimeError(f"{code} 历史净值获取失败: {last_err}")

    def _normalize_nav(self, df: pd.DataFrame, code: str) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["基金代码", "净值日期", "累计净值", "单位净值", "日增长率%"])
        df = df.copy()
        date_col = first_existing(df.columns, ["净值日期", "日期", "FSRQ"])
        accum_col = first_existing(df.columns, ["累计净值", "累计净值走势", "LJJZ"])
        unit_col = first_existing(df.columns, ["单位净值", "单位净值走势", "DWJZ"])
        growth_col = first_existing(df.columns, ["日增长率", "日增长率%", "JZZZL"])
        if date_col is None:
            raise RuntimeError(f"{code} 净值日期字段无法识别: {list(df.columns)}")
        value_col = accum_col or unit_col
        if value_col is None:
            raise RuntimeError(f"{code} 净值字段无法识别: {list(df.columns)}")
        out = pd.DataFrame(
            {
                "基金代码": normalize_code(code),
                "净值日期": pd.to_datetime(df[date_col], errors="coerce"),
                "累计净值": pd.to_numeric(df[accum_col], errors="coerce") if accum_col else pd.to_numeric(df[value_col], errors="coerce"),
                "单位净值": pd.to_numeric(df[unit_col], errors="coerce") if unit_col else pd.to_numeric(df[value_col], errors="coerce"),
                "日增长率%": pd.to_numeric(df[growth_col].astype(str).str.replace("%", "", regex=False), errors="coerce") if growth_col else pd.NA,
            }
        )
        out = out.dropna(subset=["净值日期", "累计净值"]).sort_values("净值日期").drop_duplicates("净值日期")
        return out.reset_index(drop=True)

    def fetch_holdings(self, code: str, force: bool = False) -> pd.DataFrame:
        code = normalize_code(code)
        path = project_path(self.cache_root, "holdings", f"{code}.csv")
        ensure_dir(path.parent)
        if not force and self._is_cache_fresh(path, 30):
            return self._read_csv(path)
        ak = self._ak()

        def call():
            try:
                return ak.fund_portfolio_hold_em(symbol=code, date=None)
            except TypeError:
                return ak.fund_portfolio_hold_em(symbol=code)

        df = retry_call(call, self.retry_times, self.sleep_seconds, self.logger, f"holdings {code}")
        out = self._normalize_holdings(df, code)
        out.to_csv(path, index=False, encoding="utf-8-sig")
        time.sleep(self.sleep_seconds)
        return out

    def _normalize_holdings(self, df: pd.DataFrame, code: str) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["基金代码", "报告期", "股票代码", "股票名称", "持仓占比%"])
        df = df.copy()
        period_col = first_existing(df.columns, ["季度", "报告期", "公告日期", "截止日期"])
        stock_code_col = first_existing(df.columns, ["股票代码", "代码"])
        stock_name_col = first_existing(df.columns, ["股票名称", "名称"])
        weight_col = first_existing(df.columns, ["占净值比例", "持仓占比", "占净值比例%", "占基金净值比"])
        if stock_name_col is None:
            raise RuntimeError(f"{code} 持仓字段无法识别: {list(df.columns)}")
        out = pd.DataFrame(
            {
                "基金代码": normalize_code(code),
                "报告期": df[period_col].astype(str) if period_col else "",
                "股票代码": df[stock_code_col].astype(str) if stock_code_col else "",
                "股票名称": df[stock_name_col].astype(str),
                "持仓占比%": pd.to_numeric(df[weight_col].astype(str).str.replace("%", "", regex=False), errors="coerce") if weight_col else pd.NA,
            }
        )
        return out.dropna(subset=["股票名称"]).reset_index(drop=True)

    def fetch_fund_profile(self, code: str, force: bool = False) -> dict[str, Any]:
        code = normalize_code(code)
        path = project_path(self.cache_root, "profile", f"{code}.csv")
        ensure_dir(path.parent)
        if not force and self._is_cache_fresh(path, 30):
            df = self._read_csv(path)
            return dict(zip(df.get("item", []), df.get("value", [])))
        ak = self._ak()

        def call():
            return ak.fund_individual_basic_info_xq(symbol=code, timeout=10)

        df = retry_call(call, self.retry_times, self.sleep_seconds, self.logger, f"profile {code}")
        if df is None or df.empty:
            return {}
        out = df.copy()
        if "item" not in out.columns or "value" not in out.columns:
            item_col = first_existing(out.columns, ["item", "项目"])
            value_col = first_existing(out.columns, ["value", "值"])
            if item_col is None or value_col is None:
                return {}
            out = out.rename(columns={item_col: "item", value_col: "value"})
        out[["item", "value"]].to_csv(path, index=False, encoding="utf-8-sig")
        time.sleep(self.sleep_seconds)
        return dict(zip(out["item"], out["value"]))

    def fetch_index_nav(self, symbol: str = "sh000300", force: bool = False) -> pd.DataFrame:
        path = project_path(self.cache_root, "index", f"{symbol}.csv")
        ensure_dir(path.parent)
        if not force and self._is_cache_fresh(path, 3):
            return self._read_csv(path)
        ak = self._ak()

        def call():
            return ak.stock_zh_index_daily(symbol=symbol)

        df = retry_call(call, self.retry_times, self.sleep_seconds, self.logger, f"index {symbol}")
        date_col = first_existing(df.columns, ["date", "日期"])
        close_col = first_existing(df.columns, ["close", "收盘"])
        if date_col is None or close_col is None:
            raise RuntimeError(f"{symbol} 指数字段无法识别: {list(df.columns)}")
        out = pd.DataFrame(
            {
                "基金代码": symbol,
                "净值日期": pd.to_datetime(df[date_col], errors="coerce"),
                "累计净值": pd.to_numeric(df[close_col], errors="coerce"),
                "单位净值": pd.to_numeric(df[close_col], errors="coerce"),
                "日增长率%": pd.NA,
            }
        ).dropna(subset=["净值日期", "累计净值"]).sort_values("净值日期")
        out.to_csv(path, index=False, encoding="utf-8-sig")
        return out
