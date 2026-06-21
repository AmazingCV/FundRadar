from __future__ import annotations

import pandas as pd

from fund_radar.metrics import forward_return, period_return


def sample_nav() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=500, freq="D")
    return pd.DataFrame({"基金代码": "000001", "净值日期": dates, "累计净值": [1 + i * 0.001 for i in range(len(dates))]})


def test_period_return_uses_requested_days_not_years() -> None:
    nav = sample_nav()
    r_3m = period_return(nav, "2025-01-01", 91)
    r_3y = period_return(nav, "2025-01-01", 1095)
    assert r_3m["起始净值日期"] != r_3y["起始净值日期"]
    assert pd.to_datetime(r_3m["起始净值日期"]) > pd.to_datetime(r_3y["起始净值日期"])


def test_forward_return_buy_after_sell_before() -> None:
    nav = sample_nav()
    r = forward_return(nav, "2024-02-01 12:00:00", 30)
    assert r["买入净值日期"] == "2024-02-02"
    assert r["卖出净值日期"] == "2024-03-02"
    assert r["未来收益率%"] > 0
    assert r["是否完整验证"] is True


def test_forward_return_marks_unmatured_horizon() -> None:
    nav = sample_nav()
    r = forward_return(nav, "2025-05-01", 365)
    assert pd.isna(r["未来收益率%"])
    assert r["卖出净值日期"] is None
    assert r["horizon是否到期"] is False
    assert r["是否完整验证"] is False
