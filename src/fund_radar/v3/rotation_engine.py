from __future__ import annotations

import pandas as pd

from .signal_adapter import V3Signals


def build_rotation_signal(signals: V3Signals, allocation: pd.DataFrame) -> pd.DataFrame:
    themes = signals.theme_stats.copy() if signals.theme_stats is not None else pd.DataFrame()
    short = signals.short_newstars.copy() if signals.short_newstars is not None else pd.DataFrame()
    current_main = ""
    if not themes.empty and "主题" in themes.columns:
        current_main = str(themes.iloc[0].get("主题", ""))
    rows = []
    if allocation.empty:
        return pd.DataFrame()
    alloc_theme = allocation.groupby("主题", dropna=False)["目标权重%"].sum().sort_values(ascending=False).reset_index()
    theme_names = list(dict.fromkeys([str(x) if pd.notna(x) else "未归因" for x in alloc_theme["主题"].tolist()]))
    if not themes.empty and "主题" in themes.columns:
        for name in themes["主题"].dropna().astype(str).tolist():
            if name not in theme_names:
                theme_names.append(name)
    for theme in theme_names:
        aw = alloc_theme[alloc_theme["主题"].fillna("未归因").astype(str).eq(theme)]
        alloc_weight = float(aw["目标权重%"].iloc[0]) if not aw.empty else 0.0
        newstar_count = 0
        if not short.empty and "基金代码" in short.columns:
            theme_codes = set(allocation[allocation["主题"].eq(theme)]["基金代码"])
            newstar_count = int(short["基金代码"].isin(theme_codes).sum())
        can_be_new_main = theme not in {"未归因", "", None}
        theme_row = themes[themes["主题"].astype(str).eq(theme)].head(1) if not themes.empty and "主题" in themes.columns else pd.DataFrame()
        judgement = str(theme_row["主线判断"].iloc[0]) if not theme_row.empty and "主线判断" in theme_row.columns else ""
        theme_state = str(theme_row["主线状态"].iloc[0]) if not theme_row.empty and "主线状态" in theme_row.columns else ""
        if theme == current_main:
            status = "当前主线"
        elif "退潮" in theme_state:
            status = "退潮信号"
        elif can_be_new_main and ("次强" in judgement or "扩散" in theme_state):
            status = "次方向/扩散方向"
        elif can_be_new_main and newstar_count >= 2 and alloc_weight >= 10:
            status = "疑似新主线"
        else:
            status = "观察"
        direction = "维持" if status == "当前主线" else ("加仓观察" if status == "疑似新主线" else "不动作")
        if status == "次方向/扩散方向":
            direction = "观察扩散，不替代当前主线"
        if status == "退潮信号":
            direction = "降低暴露或停止加仓"
        if alloc_weight > 60:
            direction = "主题超过60%，降低集中仓位"
        rows.append(
            {
                "当前主线": current_main,
                "主题": theme,
                "主题目标权重%": alloc_weight,
                "新星基金数量": newstar_count,
                "主线切换判断": status,
                "主线判断": judgement,
                "主线状态": theme_state,
                "迁移证据": "新星集中+主题暴露上升" if status == "疑似新主线" else ("V1主题统计显示次强/扩散" if status == "次方向/扩散方向" else ""),
                "资金迁移方向": f"{current_main} -> {theme}" if status == "疑似新主线" and current_main else "",
                "迁移口径": "主题暴露迁移/主线强度迁移，不代表真实资金流",
                "建议减仓/加仓方向": direction,
            }
        )
    return pd.DataFrame(rows)
