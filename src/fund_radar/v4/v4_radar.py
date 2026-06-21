from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..report import write_excel, write_markdown
from ..utils import ensure_dir, project_path, today_str
from .backtest_v4 import build_v4_validation_note
from .config_v4 import default_v4_config, has_theme_flow_change, valid_theme_mask
from .crowding_engine import build_crowding_report
from .feature_store_v4 import build_v4_feature_store
from .flow_engine import build_flow_report
from .rotation_engine import build_rotation_paths


def run_v4_full(limit: int | None = None, output_dir: str | Path | None = None) -> dict[str, Path | pd.DataFrame]:
    config = default_v4_config()
    store = build_v4_feature_store()
    out_dir = ensure_dir(output_dir or project_path("reports", "v4", today_str()))
    features = store.theme_features
    if limit:
        features = features.head(limit)
    has_flow_change = has_theme_flow_change(features)
    unmapped = features[~valid_theme_mask(features)].copy()
    inflow, outflow = build_flow_report(features, config)
    high, mid, low = build_crowding_report(features, config)
    rotation = build_rotation_paths(inflow, outflow, high, config)
    validation = build_v4_validation_note()
    source = pd.DataFrame(
        [
            {"来源": "V1报告", "路径": str(store.v1_report)},
            {"来源": "V3目录", "路径": str(store.v3_dir)},
            {"来源": "V3_tracker目录", "路径": str(store.tracker_dir)},
            {"来源": "口径说明", "路径": store.source_note},
        ]
    )
    flow_in_sheet = "主题暴露增强榜" if has_flow_change else "首期主题强度基准榜"
    flow_out = outflow.head(config.top_n) if has_flow_change else pd.DataFrame([{"说明": "首期基准快照或暂无历史主题暴露变化，暂无流出证据"}])
    flow_path = write_excel(
        out_dir / "flow_report.xlsx",
        {
            flow_in_sheet: inflow.head(config.top_n),
            "主题暴露减弱榜": flow_out,
            "unmapped_exposure": unmapped,
            "主题特征": features,
            "数据来源": source,
        },
    )
    crowding_path = write_excel(
        out_dir / "crowding_report.xlsx",
        {
            "高拥挤风险榜": high.head(config.top_n),
            "中拥挤榜": mid.head(config.top_n),
            "低拥挤机会榜": low.head(config.top_n),
            "unmapped_exposure": unmapped,
            "主题特征": features,
        },
    )
    rotation_sheet = rotation.head(config.top_n) if not rotation.empty else pd.DataFrame([{"说明": "首期基准快照或暂无历史主题暴露变化，暂无明确轮动路径"}])
    rotation_path = write_excel(
        out_dir / "rotation_report.xlsx",
        {
            "轮动机会榜": rotation_sheet,
            flow_in_sheet: inflow.head(config.top_n),
            "主题暴露减弱榜": flow_out,
            "验证说明": validation,
        },
    )
    unmapped_weight = pd.to_numeric(unmapped.get("V3主题权重%", pd.Series(dtype=float)), errors="coerce").fillna(0).sum() if not unmapped.empty else 0.0
    flow_heading = "当前主题强度基准" if not has_flow_change else "主题暴露流入方向"
    flow_text = "当前是首期基准快照或暂无历史主题暴露变化，不能判断真实流入/流出。" if not has_flow_change else inflow.head(config.top_n)
    outflow_text = "暂无流出证据。" if not has_flow_change else outflow.head(config.top_n)
    summary_path = write_markdown(
        out_dir / "v4_summary.md",
        "FundRadar V4 主题暴露与拥挤度观察层",
        {
            "定位": "V4 是资金行为分析层，只读 V1/V3/V3_tracker 输出，不改上游逻辑，不预测收益，不是荐基工具，不直接用收益预测作为信号。",
            "当前运行口径": "当前没有直接接入 ETF 行业资金流和成交额；本报告只使用主题暴露迁移/主线强度迁移代理。首期记录不足时不能判断真实轮动。",
            flow_heading: flow_text,
            "主题暴露流出证据": outflow_text,
            "哪里已经过热": high.head(config.top_n),
            "下一轮可能切哪里": rotation.head(config.top_n) if not rotation.empty else "当前是首期基准快照或暂无历史主题暴露变化，暂无明确轮动路径。",
            "未映射主题仓位": f"当前 V3 有 {unmapped_weight:.2f}% 仓位未映射到明确主题，不参与主题榜单和轮动判断。",
            "重要口径": "当前 ETF行业资金流/成交额未直接接入；主题暴露变化只是代理指标，不代表真实交易所资金流。",
            "数据来源": source,
        },
    )
    return {
        "output_dir": out_dir,
        "flow_report": flow_path,
        "crowding_report": crowding_path,
        "rotation_report": rotation_path,
        "summary": summary_path,
        "inflow": inflow,
        "outflow": outflow,
        "crowding_high": high,
        "rotation": rotation,
    }
