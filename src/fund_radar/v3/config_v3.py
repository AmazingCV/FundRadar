from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class V3Config:
    selected_bucket: float = 0.40
    diversified_bucket: float = 0.30
    newstar_bucket: float = 0.20
    cash_bucket: float = 0.10
    max_single_fund: float = 0.20
    max_single_theme: float = 0.60
    drawdown_reduce: float = -15.0
    drawdown_clear: float = -25.0
    profit_take_1: float = 30.0
    profit_take_2: float = 60.0
    top_selected: int = 10
    top_diversified: int = 10
    top_newstar: int = 10
    random_seed: int = 42
    backtest_horizons: dict[str, int] = field(default_factory=lambda: {"1月": 30, "3月": 91})


def default_v3_config() -> V3Config:
    return V3Config()

