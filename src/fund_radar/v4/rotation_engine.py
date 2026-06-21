from __future__ import annotations

import pandas as pd

from .config_v4 import V4Config, default_v4_config, has_theme_flow_change, valid_theme_mask


def build_rotation_paths(flow_in: pd.DataFrame, flow_out: pd.DataFrame, crowding_high: pd.DataFrame, config: V4Config | None = None) -> pd.DataFrame:
    config = config or default_v4_config()
    if flow_in.empty or flow_out.empty:
        return pd.DataFrame()
    combined = pd.concat([flow_in, flow_out], ignore_index=True)
    empty_cols = ["流出主题A", "流入主题B", "A流出分", "B流入分", "轮动机会分", "迁移证据", "口径说明"]
    if not has_theme_flow_change(combined):
        return pd.DataFrame(columns=empty_cols)
    out_candidates = flow_out[valid_theme_mask(flow_out)].head(config.top_n)
    in_candidates = flow_in[valid_theme_mask(flow_in)].head(config.top_n)
    rows = []
    high_set = set(crowding_high.get("主题", pd.Series(dtype=str)).astype(str)) if crowding_high is not None and not crowding_high.empty else set()
    for _, old in out_candidates.iterrows():
        for _, new in in_candidates.iterrows():
            if old["主题"] == new["主题"]:
                continue
            score = float(new.get("主题暴露流入分", 0)) + float(old.get("主题暴露流出分", 0))
            if old["主题"] in high_set:
                score += 10
            rows.append(
                {
                    "流出主题A": old["主题"],
                    "流入主题B": new["主题"],
                    "A流出分": old.get("主题暴露流出分"),
                    "B流入分": new.get("主题暴露流入分"),
                    "轮动机会分": score,
                    "迁移证据": "A主题暴露下降/低权重 + B主题暴露上升/强度上升",
                    "口径说明": "可能轮动路径，基于主题暴露迁移和拥挤变化，不代表真实资金流",
                }
            )
    return pd.DataFrame(rows).sort_values("轮动机会分", ascending=False).head(config.top_n).reset_index(drop=True) if rows else pd.DataFrame()
