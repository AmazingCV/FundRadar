from __future__ import annotations

import pandas as pd

from fund_radar.scoring import score_funds


def test_scoring_rewards_momentum_and_penalizes_drawdown() -> None:
    cfg = {
        "scoring": {
            "weights": {"近1月收益率%": 0.2, "近3月收益率%": 0.3, "近6月收益率%": 0.25, "近1年收益率%": 0.15, "近1年最大回撤%": 0.1},
            "acceleration_weight": 0.0,
            "overheat_penalty": False,
            "overheat_thresholds": {"warm": 60, "hot": 100, "extreme": 150},
        }
    }
    df = pd.DataFrame(
        [
            {"基金代码": "000001", "基金名称": "强势", "近1月收益率%": 10, "近3月收益率%": 30, "近6月收益率%": 40, "近1年收益率%": 50, "近1年最大回撤%": -15},
            {"基金代码": "000002", "基金名称": "较弱", "近1月收益率%": 1, "近3月收益率%": 3, "近6月收益率%": 5, "近1年收益率%": 8, "近1年最大回撤%": -35},
        ]
    )
    scored = score_funds(df, cfg)
    assert scored.iloc[0]["基金名称"] == "强势"
    assert scored.iloc[0]["最终分"] > scored.iloc[1]["最终分"]
