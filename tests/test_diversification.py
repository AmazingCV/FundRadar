from __future__ import annotations

import pandas as pd

from fund_radar.diversification import build_diversified_watchlist, normalize_company_name


class DummyLoader:
    def fetch_fund_profile(self, code: str) -> dict:
        return {
            "000001": {"基金公司": "公司A", "基金经理": "经理1"},
            "000002": {"基金公司": "公司A", "基金经理": "经理1"},
            "000003": {"基金公司": "公司A", "基金经理": "经理2"},
            "000004": {"基金公司": "公司B", "基金经理": "经理3"},
        }.get(code, {})


def test_diversified_watchlist_limits_company_and_preserves_score_order() -> None:
    scored = pd.DataFrame(
        [
            {"基金代码": "000001", "基金名称": "公司A一号", "最终分": 100},
            {"基金代码": "000002", "基金名称": "公司A二号", "最终分": 99},
            {"基金代码": "000003", "基金名称": "公司A三号", "最终分": 98},
            {"基金代码": "000004", "基金名称": "公司B一号", "最终分": 97},
        ]
    )
    out = build_diversified_watchlist(scored, DummyLoader(), target_n=3, source_top_n=4, max_per_company=2, max_per_manager=2)
    assert out["基金代码"].tolist() == ["000001", "000002", "000004"]
    assert (out["基金公司"] == "公司A").sum() == 2


def test_diversified_watchlist_never_readds_over_limit_fund() -> None:
    scored = pd.DataFrame(
        [
            {"基金代码": "000001", "基金名称": "公司A一号", "最终分": 100},
            {"基金代码": "000002", "基金名称": "公司A二号", "最终分": 99},
            {"基金代码": "000003", "基金名称": "公司A三号", "最终分": 98},
        ]
    )
    out = build_diversified_watchlist(scored, DummyLoader(), target_n=3, source_top_n=3, max_per_company=2, max_per_manager=2)
    assert out["基金代码"].tolist() == ["000001", "000002"]
    assert "000003" not in out["基金代码"].tolist()
    assert len(out) == 2


def test_company_name_normalization() -> None:
    assert normalize_company_name("财通基金管理有限公司") == normalize_company_name("财通基金管理公司")
    assert normalize_company_name("财通基金管理有限公司") == "财通"
    assert normalize_company_name("新华基金管理股份有限公司") == "新华"
