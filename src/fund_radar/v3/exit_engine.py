from __future__ import annotations

import numpy as np
import pandas as pd

from .config_v3 import V3Config, default_v3_config


def build_exit_plan(allocation: pd.DataFrame, theme_stats: pd.DataFrame | None = None, config: V3Config | None = None) -> pd.DataFrame:
    config = config or default_v3_config()
    if allocation.empty:
        return pd.DataFrame()
    rows = []
    weak_themes = set()
    if theme_stats is not None and not theme_stats.empty and "主线状态" in theme_stats.columns and "主题" in theme_stats.columns:
        weak_themes = set(theme_stats[theme_stats["主线状态"].astype(str).str.contains("退潮|分散", na=False)]["主题"])
    for _, r in allocation.iterrows():
        r1w = pd.to_numeric(r.get("近1周收益率%", np.nan), errors="coerce")
        r1m = pd.to_numeric(r.get("近1月收益率%", np.nan), errors="coerce")
        dd = pd.to_numeric(r.get("近1年最大回撤%", np.nan), errors="coerce")
        profit = pd.to_numeric(r.get("近6月收益率%", np.nan), errors="coerce")
        actions = []
        momentum_check = "未触发"
        rank_check = "无上期排名数据，未触发"
        theme_check = "未触发"
        dd_check = "未触发"
        profit_check = "未触发"
        if pd.notna(r1w) and pd.notna(r1m) and r1w < r1m / 4:
            actions.append("动量衰减")
            momentum_check = "触发：近1周弱于近1月节奏"
        if str(r.get("主题", "")) in weak_themes:
            actions.append("主题退潮")
            theme_check = "触发：主题退潮或分散"
        if pd.notna(dd) and dd <= config.drawdown_clear:
            actions.append("-25%清仓线")
            dd_check = "触发：-25%清仓线"
            suggested = "清仓"
        elif pd.notna(dd) and dd <= config.drawdown_reduce:
            actions.append("-15%降仓线")
            dd_check = "触发：-15%降仓线"
            suggested = "减仓50%"
        elif pd.notna(profit) and profit > config.profit_take_2:
            actions.append("盈利超过60%")
            profit_check = "触发：盈利超过60%"
            suggested = "再卖30%，剩余跟随趋势"
        elif pd.notna(profit) and profit > config.profit_take_1:
            actions.append("盈利超过30%")
            profit_check = "触发：盈利超过30%"
            suggested = "卖出30%"
        elif actions:
            suggested = "观察或小幅降仓"
        else:
            suggested = "继续持有并跟踪"
        rows.append(
            {
                "基金代码": r.get("基金代码"),
                "基金名称": r.get("基金名称"),
                "当前目标权重%": r.get("目标权重%"),
                "主题": r.get("主题"),
                "动量衰减检查": momentum_check,
                "排名下降检查": rank_check,
                "主题退潮检查": theme_check,
                "回撤触发检查": dd_check,
                "止盈规则检查": profit_check,
                "止盈/退出触发项": "；".join(actions) if actions else "无",
                "建议动作": suggested,
                "说明": "规则化资金管理提示，不构成买卖建议",
            }
        )
    return pd.DataFrame(rows)
