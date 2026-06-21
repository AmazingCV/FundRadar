# 基金雷达 / 公募基金趋势发现系统


这是一个用于“发现基金和板块信息差”的 Python 工程。它不会预测哪只基金一定上涨，也不是荐基工具；它的目标是把大量公募基金压缩成可复盘的观察池，并用历史时点模拟和回测验证规则是否有信息价值。

## 功能

- 指定基金阶段收益对比：近1周、近1月、近3月、近6月、近1年、近3年，输出排序、图表和 Excel。
- 全市场主动权益基金扫描：过滤非主动权益品种，计算收益、回撤、波动率、加速分、综合分、热度提示。
- 分散观察池：保留纯评分精选池的同时，额外生成同基金公司/基金经理重复暴露更低的辅助观察池。
- 持仓归因和主题识别：抓取精选观察池重仓股，按 `config/theme_keywords.yaml` 识别主线。
- 连续跟踪快照：保存每次观察池、主题、持仓，并和上一次快照比较。
- 历史月度回测：每个月末只用当时以前的数据选 TopN，再验证未来 3/6/12 月收益。
- 时间机器验证：站在过去某一天生成观察池，再用之后真实数据验证未来 1/3/6/12 月表现。
- 权重搜索与留出验证：用 2023-2025-06-18 调参，用之后区间验证，标记疑似过拟合规则。
- V1.1 短期异动雷达：作为新增观察层，发现近几日/近1周/近1月突然变强的基金、新星基金和短期主题扩散，不改变 V1 精选观察池、分散观察池和主线判断逻辑。

## 安装

当前目录是项目根目录。建议使用 Python 3.10+：

```bash
pip install -r requirements.txt
```

本机当前 `python` 发行包缺少 `pip/venv`，因此需要使用一个带 pip 的 Python 3 环境运行。AKShare 需要联网访问公开数据源。

## 常用命令

```bash
python scripts/run_stage_return_compare.py
python scripts/run_market_scan.py
python scripts/run_backtest.py
python scripts/run_weight_search.py
python scripts/run_tracking.py
python scripts/run_time_machine.py --as-of 2025-06-18 --horizon 1m,3m,6m,12m --top-n 10
python scripts/run_short_term_radar.py --limit 800
python scripts/run_short_term_weight_search.py
python scripts/run_full_pipeline.py
```

也可以使用模块 CLI：

```bash
PYTHONPATH=src python -m fund_radar market-scan --limit 800
PYTHONPATH=src python -m fund_radar time-machine --as-of 2025-06-18 --horizon 1m,3m,6m,12m
```

## 输出

- `reports/stage_return_compare/<日期>/阶段收益对比.xlsx`
- `reports/<月份>/<日期>/基金雷达扫描结果.xlsx`
- `reports/<月份>/<日期>/分析摘要.md`
- `reports/time_machine/<历史日期>/历史时点观察池.xlsx`
- `reports/time_machine/<历史日期>/历史时点分析报告.md`
- `reports/<日期>/短期异动雷达.xlsx`
- `reports/short_term_weight_search/短期权重搜索结果.xlsx`
- `reports/backtest/<区间>/基金雷达历史回测结果.xlsx`
- `reports/weight_search/<区间>/权重搜索结果.xlsx`
- `data/cache/` 保存接口缓存，`data/snapshots/` 保存连续跟踪快照。

## 核心限制

- AKShare 接口字段和可用性会变化，系统做了重试、缓存和字段识别，但不能保证每次所有基金都成功。
- 公开接口很难完整还原历史任意时点的基金存续池和基金分类，因此历史回测仍可能存在幸存者偏差。
- 持仓数据有披露滞后。时间机器中净值信号严格按 as-of 截断，持仓主题信号需要结合可获得报告期解释，不能当作无滞后的预测因子。
- 强势和偏热经常同时出现。系统会提示过热、回撤和拥挤风险，不把涨幅榜直接当成买入清单。
- 精选观察池反映最强信号，可能高度集中；分散观察池只用于降低重复暴露，便于人工观察，不替代精选观察池。
- V1 精选观察池更适合中线趋势观察；短期异动雷达更适合发现近期刚变强的基金，但短期榜单波动更大、误报更多，不能直接当成买入推荐。
