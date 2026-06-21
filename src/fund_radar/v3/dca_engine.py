from __future__ import annotations

import numpy as np
import pandas as pd


def build_dca_plan(allocation: pd.DataFrame) -> pd.DataFrame:
    if allocation.empty:
        return pd.DataFrame()
    rows = []
    for rank, (_, r) in enumerate(allocation.iterrows(), start=1):
        source = str(r.get("来源池", ""))
        heat = str(r.get("热度提示", ""))
        r1w = pd.to_numeric(r.get("近1周收益率%", np.nan), errors="coerce")
        r1m = pd.to_numeric(r.get("近1月收益率%", np.nan), errors="coerce")
        if "新星池" in source and "精选池" not in source:
            cycle = "观察3天后10天"
            steps = 10
            start_rule = "新星基金：先观察3天"
            accelerate = "否"
        elif heat == "极热":
            cycle = "20天"
            steps = 20
            start_rule = "极热基金：谨慎分批，不快速满仓"
            accelerate = "否"
        elif "精选池" in source and rank <= 3:
            cycle = "5天"
            steps = 5
            start_rule = "强趋势：快速建仓"
            accelerate = "是"
        else:
            cycle = "10天"
            steps = 10
            start_rule = "中等趋势：均匀建仓"
            accelerate = "否"
        add = bool(pd.notna(r1w) and pd.notna(r1m) and r1w > r1m / 4 and heat not in {"极热", "很热"})
        rows.append(
            {
                "基金代码": r.get("基金代码"),
                "基金名称": r.get("基金名称"),
                "目标权重%": r.get("目标权重%"),
                "建仓周期": cycle,
                "每次投入比例%": float(r.get("目标权重%", 0)) / steps,
                "是否加速建仓": accelerate,
                "加仓规则触发": "是，目标仓位基础上+20%" if add else "否",
                "入场说明": start_rule,
            }
        )
    return pd.DataFrame(rows)
