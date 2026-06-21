from __future__ import annotations

import pandas as pd


def build_v4_validation_note() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"项目": "验证口径", "说明": "V4当前只读 V1/V3/V3_tracker 输出，历史样本依赖 paper tracking 的逐日/月度记录积累。"},
            {"项目": "walk-forward", "说明": "每期只使用该日期前已生成的 V1/V3/V3_tracker 记录；后续收益只用于验证。"},
            {"项目": "当前限制", "说明": "本地样本初期较少，ETF行业资金流和成交额尚未接入真实数据源，当前使用主题暴露迁移代理。"},
        ]
    )

