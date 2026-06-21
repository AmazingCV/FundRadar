from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..report import write_excel, write_markdown
from ..utils import ensure_dir, project_path, today_str
from .backtest import run_v3_backtest
from .config_v3 import default_v3_config
from .dca_engine import build_dca_plan
from .exit_engine import build_exit_plan
from .portfolio_engine import allocation_summary, build_portfolio_allocation
from .rotation_engine import build_rotation_signal
from .signal_adapter import load_v3_signals


def run_v3_full(limit: int | None = None, output_dir: str | Path | None = None) -> dict[str, Path | pd.DataFrame]:
    config = default_v3_config()
    signals = load_v3_signals()
    out_dir = ensure_dir(output_dir or project_path("reports", "v3", today_str()))
    allocation = build_portfolio_allocation(signals, config)
    if limit:
        allocation = allocation.head(limit)
    dca = build_dca_plan(allocation)
    exit_plan = build_exit_plan(allocation, signals.theme_stats, config)
    rotation = build_rotation_signal(signals, allocation)
    backtest_detail, backtest_summary = run_v3_backtest(config)
    summary = allocation_summary(allocation, config)

    portfolio_path = write_excel(out_dir / "portfolio_allocation.xlsx", {"组合仓位": allocation, "仓位摘要": summary})
    dca_path = write_excel(out_dir / "dca_plan.xlsx", {"DCA计划": dca})
    exit_path = write_excel(out_dir / "exit_plan.xlsx", {"止盈退出计划": exit_plan})
    rotation_path = write_excel(out_dir / "rotation_signal.xlsx", {"轮动信号": rotation})
    backtest_path = write_excel(out_dir / "V3_backtest.xlsx", {"回测汇总": backtest_summary, "回测明细": backtest_detail})
    summary_path = write_markdown(
        out_dir / "v3_summary.md",
        "FundRadar V3 资金决策辅助报告",
        {
            "定位": "V3 不是预测系统，不推荐基金，不预测未来收益；它只把 V1/V1.1/V2-lite 的观察信号转成仓位、定投、止盈、轮动和风险控制建议。当前定位是风险约束后的执行模拟，不是实盘建议。",
            "读取的上游报告": pd.DataFrame(
                [
                    {"类型": "V1", "路径": str(signals.v1_report)},
                    {"类型": "V1.1", "路径": str(signals.short_report)},
                    {"类型": "V2-lite", "路径": str(signals.v2_report)},
                ]
            ),
            "仓位摘要": summary,
            "组合仓位Top20": allocation.head(20),
            "DCA计划": dca.head(20),
            "止盈退出计划": exit_plan.head(20),
            "轮动信号": rotation,
            "回测汇总": backtest_summary,
            "重要限制": "V3 资金建议必须结合人工判断；主题持仓披露存在滞后，短期信号误报更高，所有动作仅为资金管理辅助规则。",
        },
    )
    return {
        "output_dir": out_dir,
        "portfolio_path": portfolio_path,
        "dca_path": dca_path,
        "exit_path": exit_path,
        "rotation_path": rotation_path,
        "backtest_path": backtest_path,
        "summary_path": summary_path,
        "allocation": allocation,
        "dca": dca,
        "exit_plan": exit_plan,
        "rotation": rotation,
        "backtest_summary": backtest_summary,
    }
