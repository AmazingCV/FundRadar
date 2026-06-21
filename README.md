# 基金雷达 / 公募基金趋势发现系统


这是一个用于“发现基金和板块信息差”的 Python 工程。它不会预测哪只基金一定上涨，也不是荐基工具；它的目标是把大量公募基金压缩成可复盘的观察池，并用历史时点模拟和回测验证规则是否有信息价值。

## 项目定位

FundRadar 是一个公募基金观察池与主线识别系统，不提供买卖建议，不预测哪只基金一定上涨，也不把涨幅榜包装成荐基工具。它的核心用途是：

- 从全市场主动权益基金中压缩出少量观察池；
- 识别可能正在形成或扩散的市场主线；
- 记录每期扫描、持仓、主题和风险提示；
- 用历史时点模拟和回测检查规则是否有信息价值。

## 功能

### V1 中线雷达

- 全市场主动权益基金扫描；
- 精选观察池；
- 分散观察池；
- 用户观察池表现；
- 持仓归因；
- 主题统计；
- 主线预警；
- 时间机器；
- 历史回测；
- 权重搜索。

V1 是当前主系统，适合做中线趋势观察和复盘。

### V1.1 短期异动雷达

- 短期异动总榜；
- 近1周强势榜；
- 短期强但未极热榜；
- 主题异动榜；
- 短期权重搜索。

V1.1 只作为短期观察层，用来发现“谁开始冒头”，不能作为买入信号。

### V2-lite 验证层

- 新星基金验证；
- 生命周期验证；
- 资金迁移验证。

V2-lite 当前结论是：有解释价值，但没有稳定预测能力。它只保留验证报告和验证脚本，不继续产品化完整 V2。

### V3 资金决策辅助层

V3 建立在 V1、V1.1、V2-lite 之上，只读使用已有观察信号，不改动上游逻辑。V3 不是预测系统：

- 不预测涨跌；
- 不推荐股票或基金；
- 不做未来收益预测。

V3 做的是资金管理辅助：

- 资金怎么分；
- 什么时候分批买；
- 什么时候止盈或退出；
- 什么时候观察主线轮动；
- 风险怎么控。

当前 V3 包含仓位分配、DCA 定投计划、止盈退出计划、轮动信号、风险控制和简单回测。

## 安装

当前目录是项目根目录。建议使用 Python 3.10+：

```bash
pip install -r requirements.txt
```

本机当前 `python` 发行包缺少 `pip/venv`，因此需要使用一个带 pip 的 Python 3 环境运行。AKShare 需要联网访问公开数据源。

## 常用命令

日常最常用：

```bash
python scripts/run_market_scan.py --limit 800
python scripts/run_tracking.py
```

短期观察：

```bash
python scripts/run_short_term_radar.py --limit 800
```

历史时点验证：

```bash
python scripts/run_time_machine.py --as-of 2025-06-18 --horizon 1m,3m,6m,12m --top-n 10 --limit 800
```

V2-lite 验证：

```bash
python scripts/run_v2_lite_validation.py --limit 800
```

V3 资金决策辅助：

```bash
python scripts/run_v3_full.py --limit 800
```

其他研究命令包括 `run_stage_return_compare.py`、`run_backtest.py`、`run_weight_search.py`、`run_short_term_weight_search.py` 和 `run_full_pipeline.py`。

## 推荐使用方式

- 每周或每月运行一次 `market_scan + tracking`；
- 重点看精选观察池、分散观察池、主线预警表和主题统计；
- 短期异动雷达只看近期谁开始冒头，不作为买入信号；
- V2-lite 只作为研究验证和解释层，不作为交易系统；
- V3 只把观察池信号转成仓位、定投、止盈、轮动和风险控制计划，不预测未来收益；
- 每次结论都要结合回撤、热度、主题拥挤度和历史验证结果。

## 输出

日常优先查看：

- `reports/daily/YYYY-MM-DD/daily_report.md`
- `reports/daily/YYYY-MM-DD/daily_report.xlsx`
- `reports/health/YYYY-MM-DD/health_report.md`
- `reports/daily/index.md`

日常执行和观察层输出：

- `reports/v1_market/YYYY-MM-DD/基金雷达扫描结果.xlsx`
- `reports/v1_1_short_term/YYYY-MM-DD/短期异动雷达.xlsx`
- `reports/v3/YYYY-MM-DD/`
- `reports/v3_tracker/YYYY-MM/`
- `reports/v4/YYYY-MM-DD/`

研究和历史验证输出归档在：

- `reports/research/`：回测、时间机器、权重搜索、阶段收益对比等低频研究报告
- `reports/legacy/`：早期旧目录结构的历史输出

详细说明见 `docs/报告目录说明.md`。`reports/`、`data/cache/`、`logs/` 和 Excel/CSV/Pickle/Parquet 生成物均不进入 Git。

## 核心限制

- AKShare 接口字段和可用性会变化，系统做了重试、缓存和字段识别，但不能保证每次所有基金都成功。
- 公开接口很难完整还原历史任意时点的基金存续池和基金分类，因此历史回测仍可能存在幸存者偏差。
- 持仓数据有披露滞后。时间机器中净值信号严格按 as-of 截断，持仓主题信号需要结合可获得报告期解释，不能当作无滞后的预测因子。
- 强势和偏热经常同时出现。系统会提示过热、回撤和拥挤风险，不把涨幅榜直接当成买入清单。
- 精选观察池反映最强信号，可能高度集中；分散观察池只用于降低重复暴露，便于人工观察，不替代精选观察池。
- V1 精选观察池更适合中线趋势观察；短期异动雷达更适合发现近期刚变强的基金，但短期榜单波动更大、误报更多，不能直接当成买入推荐。

## V4.2 Daily Runner

日常运行请优先使用统一入口，不再手动分别执行旧脚本：

```bash
python scripts/run_daily_all.py --limit 800
```

该入口会按步骤调度 `market_scan`、`short_term_radar`、`v3_full`、`v3_tracker`、`v4_full` 和 `daily_report`。每一步都会输出 `[START]`、`[DONE]`、`[SKIP]` 或 `[FAIL]` 以及耗时，并在 `reports/daily/YYYY-MM-DD/run_guard.json` 中记录 step-level 状态。

常用命令：

```bash
python scripts/run_daily_all.py --status
python scripts/run_daily_all.py --step daily_report
python scripts/run_daily_all.py --step market_scan --force
python scripts/run_daily_all.py --report-only
```

默认情况下，如果某一步已完成、输出存在且最新净值日期未变化，daily runner 会跳过该步骤。`--force` 会完整重跑指定步骤或全部步骤，属于昂贵操作，通常只建议在夜间或明确需要刷新缓存时使用。

## Windows 自动运行

可以使用 Windows Task Scheduler 每天自动运行 FundRadar。默认日常任务不加 `--force`，会使用 step-level run guard 跳过已完成步骤。

手动日常运行：

```powershell
python scripts/run_daily_all.py --limit 800
```

查看状态：

```powershell
python scripts/run_daily_all.py --status
```

只重建日报：

```powershell
python scripts/run_daily_all.py --report-only
```

注册每日自动运行任务，默认建议 23:30：

```powershell
.\scripts\register_fundradar_daily_task.ps1 -Time "23:30"
```

检查任务状态：

```powershell
.\scripts\check_fundradar_daily_task.ps1
```

删除任务：

```powershell
.\scripts\unregister_fundradar_daily_task.ps1
```

运行日志保存在 `logs/daily_runner/`。不要每天使用 `--force`，它会完整重跑 `market_scan`，可能耗时很久。
