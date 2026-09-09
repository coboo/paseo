# 项目进展

> 基准设计文档：`指数ETF量化系统设计方案.md`；Agent 工作约定：`AGENTS.md`；文件结构与模块关系：`架构说明.md`；**CMV 15 模型复刻看板：`CMV模型复刻清单.md`（2026-09-09 建，跟踪探数与实施）**。
> 本文件随实施推进持续更新，记录"做到哪了、怎么继续、有什么坑"。

## 当前状态：第 1-3 步完成 ✅，第 4 步推进中（策略页 + 7/12 卡片 + 综合分 + 快照就位）

| 步骤 | 内容 | 状态 |
|---|---|---|
| 第 1 步 | 数据模块 | ✅ 完成（2026-08-17） |
| 第 2 步 | 基线策略复现 | ✅ 4/4 完成（2026-08-25）：GEM ❌ / **Faber 过主检验** / FED ❌ / GTAA ❌ |
| 第 3 步 | 验证（敏感性 + walk-forward + holdout） | ✅ 执行完毕：Faber WF ✅ / holdout 实测 ❌（差幅小）→ **用户裁决：通过验收（2026-08-26）** |
| 第 4 步 | 展示层 | 🔶 推进中：Faber 策略页 ✅；**估值卡片 11 卡综合分 + EPU/Sahm 独立卡 ✅（2026-09-09 CMV 复刻两批落地）**；metrics_history 快照机制 ✅；余量：散点图自证、#15/#2/#3 卡壳项 |

## 部署准备：Streamlit Community Cloud（2026-09-09，进行中）

决策：展示层部署到 Streamlit Community Cloud，parquet 随仓库走（raw 6.1M + derived 1.2M + reports 3.6M，很轻）。Vercel 不可行：Streamlit 是长驻 WebSocket 进程，与 Serverless 函数模型冲突。

- `app/valuation_dashboard.py` 补 `sys.path.insert(0, ...parents[1]/"src")`——此前 `from metrics import ...` 依赖 uv 把 src 装进 venv，云上没这一步（faber_strategy.py 早就是此模式）；其他页面无 src 包直引，无需改
- 新增 `requirements.txt`：`uv export --no-dev` 生成（117 包全 hash 锁定），**已移除 `-e .`**（可编辑安装在云上易出问题，导入已由 sys.path 解决）
- 回归：`test_frontend_alignment.py` 全绿（仪表盘双口径/全卡片/浏览器/组件）
- **落地（2026-09-09 收工）**：`.gitignore`（排除 .venv/.DS_Store/__pycache__）+ `.github/workflows/daily-update.yml`（UTC 9:00 ≈ 北京时间 17:00 跑 update+snapshot，无 diff 不提交）+ git 建仓，191 文件首批提交（data/ reports/ 入库约 11MB）
- 待办（用户操作）：GitHub 建私有仓库 → 推送 → share.streamlit.io 建 app（main file `app/paseo.py`，Python 3.12）→ 验证 Actions 定时任务跑通

## 第 1 步完成情况（2026-08-17）

### 落地物

- `src/data_module/`：storage（parquet 增量追加/列标准化/meta 侧车）、sources（42 个数据集注册表）、update（CLI）、validate（五查）、bond_splice、tracking_check、net（东财补丁+重试）
- `data/raw/`：42 个 parquet + 42 个 `.meta.json`（4.6MB），覆盖设计文档第四节全部清单
- `data/derived/aligned/bond_leg_spliced_511260.parquet`：债券腿拼接（2007 起，收益率对齐，累乘净值）
- `reports/tracking_check.md`：跟踪差检验报告
- `scripts/probe_interfaces*.py`、`scripts/fill_n225_em.py`：接口探针与东财补数脚本

### 验收结果

- 五查 5/5 通过（沪深300=5971 交易日；指数 vs ETF 近5年偏差<0.5% 占比 97%+；300PE 2007 峰值 50.8 / 2014 均值 8.68；10Y 国债 [2.48, 4.72]；QVIX 峰值对应 2015/2018/2020/2024）
- 债券拼接：重叠期近 3 年日收益相关性 0.879
- 跟踪差：A股 ETF 与股息率自洽；QDII 正常（513100 年化 -0.71%≈费率）；**QDII 对比必须用累计净值**（513100/513500 有份额拆分，单位净值有断崖）

### 遗留事项（下次开工前先看）

1. **日经225 只有 2022-08 起**（东财不可达时用了新浪兜底）。东财恢复后：`uv run python -m data_module.update n225` 或 `scripts/fill_n225_em.py` 向前补齐。
2. **11/12 只 ETF 前复权日线是腾讯 qfq 兜底**（本机代理对东财时通时断）。质量已验证可用；如需换回东财 `fund_etf_hist_em`，须删除对应 parquet 再重抓（raw 只增不改，直接重跑不覆盖）。
3. **单指数股息率无长历史源**（funddb 接口已被 akshare 移除）：csindex 仅近月快照，靠每日重跑 `update` 积累；全 A 股息率（`dividend_all_a`）有全历史。
4. 4 只 A股指数日线是新浪兜底，**无成交额列**；H30269 来自中证官网。

## 提前落地：指标层 σ 引擎 + ERP 卡片 + 估值仪表盘 v1（2026-08-21）

对标 [CurrentMarketValuation.com](https://www.currentmarketvaluation.com/) 的标准差评估方法，σ 方法已定稿写入设计文档第六节（月频采样 / 方向归一 / 五档 / 双窗口 / expanding 无前视 / 2010 前评级不可信）。

- `src/metrics/`：`contract.py`（MetricResult 契约 + 五档评级表）、`sigma.py`（σ 引擎：月频、双窗口、expanding 当时视角）、`erp.py`（股债利差指标，中间量 pe/ep/bond_10y 同结构保留）。指标**不落盘**，实时计算（AGENTS.md 规则 5）
- `app/valuation_dashboard.py`：CMV 复刻五件套（当前值大字 → 偏离 σ → 五档红绿灯 → 走势 + ±1σ/±2σ 带 → 白话解释）+ expanding 评级演进图 + 双窗口对照 + 历史锚点回验
- 验证：`streamlit.testing.v1.AppTest` 双口径无异常；锚点回验 4/4 方向正确（2007 橙 / 2014 绿 / 2024 绿）
- `DESIGN.md` 前端设计规范定稿（2026-08-24）：CMV 五件套结构 + 五档语义色 + 图表/文案纪律 + 可复用组件清单，后续所有前端页面以此为准，风格漂移视为 bug
- 当前结论：ERP +5.65pp，近10年口径 −0.22σ、全历史 −0.47σ，双口径「公允」
- 遗留到第 4 步余量：其余 11 张模型卡片、`aggregate.py` σ 加权综合分、`metrics_history.parquet` 每日评级快照、散点图（估值分 vs 未来收益）

## 前端对齐 DESIGN.md（2026-08-24）

规范定稿后回头对齐两个已落地页面（DESIGN.md 第八节：漂移即 bug）：

- **新增 `app/components.py`**：色彩常量（墨色系 chrome / categorical 8 色 / 双 wash）+ `base_layout`（图面一次到位）+ `tier_fill`/`tier_text`（3.1 表代码化）。两页面统一 import，页面内禁止重写；DESIGN.md 第七节组件表已同步更新引用
- **`valuation_dashboard.py` 修档色漂移（真 bug 两处）**：当前档色块/徽章此前用全值 `m.color`，当前档=2 时不呈现 50% 绿；档 3 黄底、档 4 橙底配白字对比度仅 1.8–2.7:1 不可读 → 按档位改墨字（3.1 表新增"色块上文字"列）。档 3/4 色值恢复全值（此前 0.8 透明度与表格不符）
- **`browse_data.py` 对齐**：图表接入 `base_layout` + categorical 固定顺序取色（蓝 `#2a78d6` 起，超 8 序列不生成第 9 色）+ 2px 线宽 + 单序列无图例/多序列顶置横排 + hover 模板统一；全部 `use_container_width` → `width="stretch"`（streamlit ≥1.59 已废弃前者，button/dataframe/plotly 共 4 处）
- **AppTest 裸执行坑**：`from_file` 不把脚本目录加进 `sys.path`（`streamlit run` 会），页面间 import `components` 需页面顶部自插 `sys.path`；另 st.dataframe 的行选择交互 AppTest 无法模拟，测试走侧栏"直接挑选"路径
- 验证：`scripts/test_frontend_alignment.py`（AppTest 冒烟 + 组件断言）全过——仪表盘双口径、浏览器总览+详情、tier 呈现色

## cn10y 扩展为全期限曲线（2026-08-25）

为双动量策略本土化（绝对动量基准需 3M 国债收益率）将 `cn10y` 从 1Y/10Y 两列扩为**全期限 9 列**（`yield_3m/6m/1y/3y/5y/7y/10y/30y`）：

- 改动：`sources.py` `_fetch_cn10y` col_map 全保留 + Dataset 描述更名"中债国债收益率曲线（3M–30Y 全期限）"；`browse_data.py` DATASET_NAMES 同步。**数据集名 `cn10y` 保留不改**（4 处引用均按路径/列名，改名不值当）
- 重抓：raw 只增不改 + `append_save` 旧行优先，扩列必须删 `cn10y.parquet` + `.meta.json` 重抓全历史（按月分块 ~248 请求，约 6 分钟）。5123 行，2006-03-01 ~ 2026-08-24（顺带补齐了此前缺的 8/15~8/24）
- 质量：**8 期限列全部 0 缺失**，2006 年起整段完整。3M 区间 [0.78, 5.11]，锚点核对通过（2007-11 加息顶 3.59 / 2020-04 疫情底 0.89 / 当前 1.20）；10Y 区间 [1.60, 4.72] 与旧数据一致
- 验证：五查 5/5（查 4 不受影响）；`test_frontend_alignment.py` 三件套通过（ERP 读 `yield_10y` 无回归）
- 对第 2 步的意义：① 绝对动量无风险基准直接用 `yield_3m` 日利率复利 12 个月，**无需引入 yfinance**；② 设计文档"511360 上市前现金腿固定 2% 填充"的旧约定可用真实 3M 序列替代（2007-2008 现金利率 3-4%，固定 2% 系统性低估防御期收益）

## 页面入口

```bash
uv run streamlit run app/paseo.py   # 统一入口:侧栏切换四页(默认 Faber 策略页)
```

四页:Faber 策略(实盘视角:当前持仓/距均线/下次调仓)· 估值仪表盘(8 卡:综合分+7 模型)· 回测工作台(GEM 两层/敏感性/基线三策略)· 数据浏览器(42 数据集,侧栏一键增量更新)。页面文件原位保留,亦可单页直开(`streamlit run app/faber_strategy.py` 等,AppTest 测试仍指向原文件);`app/paseo.py` 仅做 st.navigation 导航(2026-08-26 增)。

`app/browse_data.py`：轻量数据浏览器（v3，2026-08-17）。首页为数据集总览表（类别/中文名/行数/起止/来源，点行进详情）；侧栏顶部显示**数据最新日期 + 更新按钮**。43 个数据集中文名登记在文件顶部 `DATASET_NAMES`，**新增数据集时在此补一行**。

## 常用命令

```bash
cd /Users/kai/paseo
uv sync                                                  # 首次/依赖变更后
# ── 数据 ──
uv run python -m data_module.update                      # 全量增量更新（断点续传）
uv run python -m data_module.update n225 cn10y           # 按名称更新
uv run python -m data_module.validate                    # 数据验收五查
uv run python -m data_module.bond_splice                 # 重建债券腿（derived 全量重算）
uv run python -m data_module.tracking_check              # 跟踪差检验
# ── 策略 ──
PYTHONPATH=src uv run python -m strategy.run_baselines   # 三基线信号层回测 + 判读表
PYTHONPATH=src uv run python -m strategy.backtest        # GEM 两层回测 + QuantStats 报告
PYTHONPATH=src uv run python -m strategy.sweep           # GEM 回望敏感性扫描
PYTHONPATH=src uv run python -m strategy.walkforward     # Faber WF + holdout 终验
# ── 指标 ──
PYTHONPATH=src uv run python -m metrics.snapshot          # 每日评级快照(metrics_history 追加一行)
# ── 测试 ──
uv run python scripts/test_gem_signal.py && uv run python scripts/test_gem_backtest.py
uv run python scripts/test_baselines.py && uv run python scripts/test_gem_backtest_app.py
uv run python scripts/test_faber_strategy_app.py && uv run python scripts/test_frontend_alignment.py
```

**日常运行节奏**:每日 `data_module.update` + `metrics.snapshot`;月末(最后交易日收盘后)跑 `strategy.run_baselines` 刷新 Faber 信号,次月首个交易日开盘按信号调仓。

## 双动量 GEM 策略实施开工（2026-08-25）

- 依赖落地：vectorbt 1.1.0 / bt 1.2.0 / QuantStats 0.0.81 装入，pandas 3.0.5 + numpy 2.5.2 原封未动，三库冒烟 3/3 通过（scripts/probe_backtest_libs.py），零 fallback。已知口径差：bt 净值基数 100、索引前自动加前置日、份额取整（~1e-5 舍入差）
- 设计文档新增第十节「基线 1：双动量 GEM 中美本土化」：资产/口径/局限/QDII 冲突处理/防御腿澄清/锚点预期/交付物；DESIGN.md 增补回测页区块类型；pyproject hatch packages 加 src/strategy
- 下一步：src/strategy 模块骨架 + 信号层

## 基线 1：双动量 GEM 落地完成（2026-08-25，当日闭环）

全链路当日跑完：依赖 → 设计文档 → `src/strategy/`（contract / gem_signal / engine+engine_pandas+engine_bt / qdii_filter / run_gem / report / backtest CLI）→ derived 落盘 → QuantStats 报告 → `app/gem_backtest.py` 卡片页 → 三套测试全绿。

### 实测结果（第一轮原参数、零成本）

| 层 | 区间 | 年化 | 最大回撤 | 夏普 | 换仓 |
|---|---|---|---|---|---|
| 信号层（指数） | 2008-02 → 2026-08 | **+5.12%** | **−54.4%**（2015-06 峰→2020-03 谷） | 0.35 | 36 次 |
| 执行层（ETF，含溢价门控） | 2014-02 → 2026-08 | +12.70% | −48.9% | 0.66 | 42 次（跳过 11 月） |

**通过线判读（AGENTS 验证纪律 5）：年化 ✅（基准的 46 倍）、回撤 ❌（只砍 19%，要求 40%+）——基线 1 第一轮未通过回撤线**。−54.4% 来自 2015 股灾（12M 动量滞后，1-6 月仍持沪深300）+ 2016 熔断 + 2018 单边熊 + 2020 疫情的连续打击；A 股急牛急熊环境下 12 月回望的绝对动量滞后严重。按纪律不改参数，去留留待第 3 步敏感性/walk-forward 裁决（若 6/9 月回望同样挡不住急跌，则本土化 GEM 判孤峰放弃）。

### 执行层超额的归因（诚实记录，勿当策略能力）

执行层比信号层共同区间年化高 5.0pp，两个来源都是**溢价门控的运气收益**而非策略能力：① 2020-03 的 nav 滞后假信号（>3%）恰好躲过美股熔断（月差 +10.7pp）；② 2024 年 QDII 溢价大波动期的进出择时 + 溢价中枢从 0 抬到 5-11% 的 β。无门控对照（premium_cap=∞）：12.70% → 10.22%，门控贡献 +2.47pp/年——门控价值真实存在但量级依赖个别年份，第 3 步应做稳健性检验。

### 踩坑记录（复用价值高）

1. **面板骨架必须是 A 股交易日**：最初 outer-merge+ffill(limit=5) 把国庆/春节休市日造成假数据行，bt 的 RunMonthly 月首触发日（10-01）与执行日（10-08）错位整月 → 两引擎差 18.7%。修法：以 hs300/510310 日期为骨架，只对美股/汇率列 reindex+ffill
2. **bt 正确用法**：`bt.run(bt.Backtest(...))` 才返回 Result（`Backtest.run()` 返回 None）；份额整数记账的取整残差在 36+ 次换仓上双向累积 ~0.5%，对账断言用"总差<5e-3 且单月收益差<0.2%"（后者才是逻辑错位探测器）
3. **513500 溢价必须滚动锚定**：单位净值 2022-03-30 份额拆分断崖（-49.8%）使 close/nav 有 -50% 级假溢价；用 63 日滚动中位数锚 + >50% 单日跳幅断点重置
4. pandas 3：`Series.clip(min=...)` 已废（用 numpy np.clip）；`hoverformat` 不是 plotly layout 属性
5. 信号起点口径：`_rf_compound` min_days=240（12 个日历月≈250 个中债工作日）+ SIGNAL_START=2008-01，防止不完整利率窗口扭曲绝对动量基准

### 常用命令

```bash
PYTHONPATH=src uv run python -m strategy.backtest          # 一键两层回测 + 报告
PYTHONPATH=src uv run python -m strategy.backtest --cost-bps 5 --premium-cap inf   # 费用/无门控对照
PYTHONPATH=src uv run python -m strategy.sweep             # 回望敏感性扫描(第 3 步)
uv run python scripts/test_gem_signal.py && uv run python scripts/test_gem_backtest.py
uv run streamlit run app/gem_backtest.py                    # 回测卡片页(含敏感性视图)
```

## 基线 1 敏感性分析:判放弃(2026-08-25)

`src/strategy/sweep.py` + `python -m strategy.sweep`:回望 {3,6,9,12,15,18,24,30} 月网格,统一共同区间 2009-02 起,落盘 `derived/backtests/gem_cn_sweep.parquet`;卡片页新增"敏感性扫描"视图。

| 回望(月) | 3 | 6 | 9 | **12** | 15 | 18 | 24 | 30 |
|---|---|---|---|---|---|---|---|---|
| 年化 | 8.98% | 6.18% | 5.99% | **5.42%** | 5.16% | 1.69% | 2.04% | 8.89% |
| 最大回撤 | −43.4% | −46.9% | −43.1% | **−54.4%** | −46.9% | −46.9% | −46.9% | −46.9% |
| 回撤削减 | 7% | −0% | 8% | **−17%** | −0% | −0% | −0% | −1% |

**判读:结构性失败——全域 8 窗口无一通过回撤线(要求砍 40%+)**。各窗口 MDD 几乎全部锚在 −46.9%(= 2015-06 峰后持沪深300 吃完股灾下半场,各窗口只差转防御快慢),不是参数选择问题,是月频 + 月级回望的动量轮动在 A 股急牛急熊环境的结构性水土不服。按验证纪律(参数高原 vs 孤峰),**本土化 GEM 判放弃,降级为反面参照**(留在代码库与卡片页作为对照组,不进入实盘候选)。3M/30M 的 sharpe 略高(0.55/0.62)但不构成达标区,不足以翻案;若未来探索短回望变体,须独立过 walk-forward + holdout,不复用 GEM 结论。

- 工程副产物:vectorbt 净值级交叉验证(from_orders + targetpercent + cash_sharing,喂开盘面板)与 pandas 主管道最大日收益差 **5.6e-16**(浮点精度级)——三库互证闭环(pandas 主管道 / bt 组合对账 / vbt 净值对照)
- 回归:`gem_signal` rf min_days 改为按窗口自适应(12M 时 240 不变,信号 223 条无回归);`test_gem_backtest.py` 增 sweep 一致性 + vbt 交叉断言;AppTest 四视图全过
- 第 3 步余量:GEM 的 walk-forward/holdout 因判放弃不再执行;Faber / FED 分位 / GTAA 三基线的复现 + 各自敏感性是下一步主战场

## 基线 2/3/4 落地 + 敏感性:四策略终局 1 通过 3 失败(2026-08-25)

设计文档新增第十一节(三基线资产映射与参数定稿,数据约束:日经/纳指/中证1000/恒生红利低波历史不足出局;黄金信号层用沪金主力 2008-01 起)。新增代码:`panels.py`(通用信号面板:A股骨架+cash=3M利率复利)、`engine_weights.py`(组合权重引擎,单资产引擎为其特例,测试恒等 0e+00)、`baseline_signals.py`(三基线信号)、`run_baselines.py`(编排+CLI+判读表)。

### 终局结果(信号层,共同区间 2009-02 起;通过线=回撤砍 40%+ 且年化 ≥70%)

| 策略 | 年化 | 最大回撤 | 回撤削减 | 敏感性 | 裁决 |
|---|---|---|---|---|---|
| **Faber 10月均线** | **+8.76%** | **−17.6%** | **62%** | SMA 6–15 月 **5/5 全域高原通过**(削减 59–64%) | ✅ **通过,首个实盘候选** |
| FED 股债利差分位 | +4.80% | −46.9% | −0% | 8/8 失败(阈值×分位窗) | ❌ 放弃 |
| GTAA 动量轮动 | +6.20% | −52.1% | −12% | 6/6 失败(TopN×回望) | ❌ 放弃 |
| (GEM,对照) | +5.42% | −54.4% | −17% | 8/8 失败 | ❌ 已判放弃 |

- **Faber 为什么活**:每资产独立的绝对趋势过滤(不做跨资产排名)+ 跌破均线即转现金(比 12M 回望快)+ 等权分散。锚点行为核对:2015-08-31 全部转出只剩债券(−17.6% 回撤的直接来源)、2008-12 只剩 bond、2018-12 bond+gold、2009-06 全通过——与金融直觉一致
- **Faber 执行层复测(通过线义务)通过**:2014-02 起 ETF qfq(510310/513500/518880/拼接 511260+溢价门控跳过 14 月)年化 +11.11%、MDD −17.5%、夏普 1.11;同区间信号层 +12.47%/−17.6% → 两层 MDD 一致、年化差 1.36pp = ETF 载体真实成本,诚实
- **FED 死因**:ERP 结构性抬升(利率长周期下行)使 expanding 分位长期高位 → 0.7 阈值下 17 年零切换,策略退化为买入持有;滚动 60M 窗亦无回撤保护(削减 3%)。教训:**慢变量(估值分位)对 A 股急跌无保护**
- **GTAA/GEM 同病**:月频动量(排名或绝对)在 2015 急牛急熊的滞后是结构性的,TopN/回望全网格无一达标

### 交付物

- `derived/signals/{faber,fed,gtaa}_monthly.parquet` + `derived/backtests/{faber,fed,gtaa}_index.parquet` + `faber_etf.parquet` + `baselines_verdict.parquet` + `baselines_sweep.parquet`
- `scripts/test_baselines.py` 全绿(引擎特例恒等/扰动不变性/权重合法性/Faber 锚点/两层一致性);`sweep_baselines.py`;卡片页新增"基线三策略"视图(判读表+敏感表+四策略净值对比,AppTest 五视图全过)
- 常用命令:`PYTHONPATH=src uv run python -m strategy.run_baselines`(三基线)、`...run_baselines faber`、`uv run python scripts/sweep_baselines.py`

### 下一步(第 3 步收尾)

Faber 过了第一轮+敏感性,还差终验:**walk-forward 滚动校准 + 最后一年 untouched holdout 只做一次**(设计文档第八节 3);通过后进入第 4 步展示层(策略卡片化)。FED/GTAA/GEM 已判死,不再消耗算力。

## Faber 终验:walk-forward ✅ / holdout ❌ → 用户裁决通过验收(2026-08-26)

`src/strategy/walkforward.py` + `PYTHONPATH=src uv run python -m strategy.walkforward`。

### walk-forward 滚动校准 ✅

8 年训练窗按 Calmar 在 SMA {6,8,10,12,15} 内选参 → 次年样本外,滚动 10 段(2016-08→2026-08):
- **选参 10 段全部落在 SMA 8(9 段)/ 6(1 段)**——与敏感性高原结论互相印证,滚动视角下最优参数稳定在高原中心
- 样本外拼接:年化 +7.60%、MDD −11.8%、**回撤削减 74%** → 主通过线 ✅
- WF − 固定10M = −0.86pp/年:参数选择依赖极小,非过拟合

### holdout 终验 ❌(2025-08-15 → 2026-08-14,untouched 只看一次)

| 判读(事前定死) | 实测 | 结果 |
|---|---|---|
| ① 年化 ≥ 基准 70% | +8.65% vs +12.80% = 67.6% | ❌(差 2.4pp 达标线) |
| ② 回撤绝对值 < 基准 | −10.66% vs −9.86% | ❌(深 0.8pp) |
| ③ 换手 <15 次 | 8 次 | ✅ |

**诚实记录**:判②首版实现方向写反(`mdd < bh_mdd` 在负数语义下选中"更深"一侧),修正为比绝对值后重跑——判读标准未变,修的是实现 bug。holdout 年行为核对无异常:多数月份 3-4 资产持有(牛市特征),2026-07 沪深300 跌出均线;跑输原因是**趋势过滤+等权在"单一资产强牛年"的结构性折价**(组合含债券/黄金,天然跑输最强单一资产),不是信号失效。

### 处置(已裁决,2026-08-26)

**用户裁决:通过验收。** 记录纪律:holdout 两条判读的**实测结果未变**(67.6%<70%、回撤深 0.8pp),本次"通过"属验收裁决而非检验通过——支持裁决的证据:18 年全区间削减 62% + WF 样本外削减 74% + SMA 高原 5/5 + 执行层复测一致,远强于单年差幅,且差因可识别(牛市结构性折价,非信号失效)。Faber 定为**唯一通过策略**,进入第 4 步策略卡片化;后续如做实盘,建议保留 2027 年新 holdout 复验作为追加确认(非纪律要求)。

## 第 4 步推进：Faber 策略页 + 2 张估值卡片（2026-08-26）

### Faber 策略页 `app/faber_strategy.py`（策略页新区块类型，DESIGN.md 已登记）

- **当前信号状态区**（策略页专属，置顶）：四资产距 10 月均线 %（delta 文字"均线上·持有/均线下·现金"）+ 当前组合权重 + 下次调仓日（calendar 动态推导，测试断言禁止硬编码）。当前实际状态：**50% 标普500 + 50% 债券腿**（沪深300 −2.4%、黄金 −10.9% 在均线下），下次调仓 2026-08-31 月末信号
- 证据链表：主检验/敏感性/WF/执行层/holdout **实测**/终局**裁决**逐行分列（实测与验收分离纪律在页面层面落实）；近 24 个月 ●/— 信号矩阵；实盘 ETF 映射页脚（513500 注溢价 ≤3%）
- `scripts/test_faber_strategy_app.py` AppTest 全过

### 估值卡片 3/12

- 新增 `metrics/curve_10y1y.py`（10Y−1Y 曲线利差，INVERSE：倒挂=风险区）与 `metrics/dividend_spread.py`（全A股息率−10Y，口径声明：300 股息率长历史源缺失用全 A）——均复刻 erp.py 模式走 σ 引擎
- 仪表盘分发改函数表 `_MODEL_SPECS`（新模型补一行），MODELS 注册 3 张；当前读数：曲线 +0.48pp（+0.52σ 公允）、股息差 +0.96pp（−0.84σ 公允）、ERP +5.65pp（公允）
- `test_frontend_alignment.py` 增三卡片遍历；**AppTest 坑**：selectbox options=key + format_func 中文显示，`select()` 必须传原始 key（`sb.options` 给的是显示值，传它必 ValueError）

### 顺手修的真 bug

`panels.month_end_anchor_dates` 缺数据新鲜度截断 → 基线信号表出现 **2026-08-31 未来伪信号**（8 月未走完，用 8-14 价格贴未来锚点）。已加"锚点 ≤ min(各资产源+利率最后日期)"截断（GEM 同款纪律），三基线信号重落盘，回测数字本就未受污染（执行日超面板被丢弃），测试全绿。

## 第 4 步推进:7/12 卡片 + 综合分 + 每日快照（2026-08-26 下半场）

### 新增 4 张卡片 `metrics/more_cards.py`（_card 模板:日频中间量→月频σ→五档）

| 卡片 | 方向 | 当前读数 |
|---|---|---|
| 沪深300 PE(TTM) | POSITIVE(高=贵) | 13.62 倍,z +0.99,公允近高档 |
| 偏离 250 日均线 | POSITIVE(过热=红) | +0.39%,z −0.18,中性 |
| 10Y 国债收益率 | POSITIVE(高利率=股承压) | 1.68%,z −1.76,利率极低位 |
| QVIX 情绪(50ETF,逆向) | INVERSE(高恐慌=绿) | 16.47 点,z +0.55(平静侧) |

### aggregate.py 综合分 + snapshot.py 每日快照

- **综合分**:7 卡估值z 等权平均 → 五档;历史序列 = 各卡 expanding 序列按月对齐平均(任一卡缺失该月不输出,口径一致性优先)。当前 **−0.13σ 公允**。诚实声明已写入 docstring:ERP/PE/股息差同源强相关,综合分当前偏"股债估值+情绪"画像,12 卡齐后再调权重。综合卡为仪表盘默认卡(MODELS 第一项,测试断言已同步)
- **快照**:`PYTHONPATH=src uv run python -m metrics.snapshot` 算 7 卡+综合,按数据截止日追加 `derived/metrics_history.parquet`(AGENTS 规则 5 唯一追加写文件;同日重跑幂等覆盖)。首行已写入(2026-08-24,composite_z −0.13/档3)。散点图(估值分 vs 未来收益)待快照积累
- 仪表盘:_MODEL_SPECS 函数表分发(新卡补一行);综合卡 expanding 副图特判走 composite_series;**锚点回验表加了样本不足保护**(综合卡序列 2020 起有效,2007/2014 锚点显示"样本不足"而非崩溃)
- 测试:八卡片 AppTest 全过(遍历 composite+7 卡);**AppTest 坑再记一条:页面头部 import 块必须先于引用它的模块级 dict(定义顺序)**

## 下次开工怎么继续

第 4 步核心已就位(策略页 + 13 卡 + 综合分 + 快照 + IC 自证)。余量按价值排序:

1. **#15 消费者信心换源**:央行城镇储户调查(季度,手工下载)或替代情绪源
2. **#2 CAPE / #3 PS**:需长历史盈利/营收数据,另立项(可从 csindex 月度估值快照逐日积累起步)
3. 快照逐日积累,每季度可重跑一次 IC 自证看稳定性;2027 年新数据到齐后可对 Faber 做新 holdout 追加确认(建议项,非纪律)

## 修数据浏览器"更新数据"按钮:部分失败误报 + 展示重做(2026-08-26)

用户反馈"经常需要重试 + 展示不友好"。根因诊断与修复:

1. **"经常失败"的真相 = 部分失败被当整体失败**:42 个数据集顺序更新,几个碰到东财间歇不可达即 FAILED → update.py 退出码 1 → 页面 ❌。但 raw 只增不改 + 断点续传,成功部分已入库,重试只补失败项——几次后就全过,用户观感是"不稳定"。修复:解析 stdout 的 OK/FAILED 计数,部分失败显示"⚠️ N 个失败——其余已入库,再点一次只补失败项"(expanded 保留日志),仅全部失败才 ❌
2. **子进程没带 PYTHONPATH=src**:可能跑 .venv 里旧安装版 data_module;已加 env(源码优先)+ `uv run --no-sync`(跳过每次环境同步检查)
3. **并发保护**:更新中刷新页面再点会起第二个进程(parquet 追加竞争)。加锁文件 data/.update_lock 记**更新子进程 pid**(生命周期=子进程,退出自动失效;页面刷新不杀子进程、子进程亡则锁自动清,无死锁路径);已有更新在跑则拒绝并说明
4. **展示重做**:进度行(已处理 N 个 · ✅ x · ❌ y · ⏱ 耗时 · 当前数据集名)+ 最近 10 行日志;15 分钟总超时防僵死(超时同样"成功部分已入库"话术)
5. 修复过程中的自查:首版锁记 os.getpid()——streamlit 脚本里那是**服务器进程** pid(常活),页面中断时 finally 不保证执行 → 锁永久卡死。改为 Popen 后立即改写为子进程 pid

验证:frontend_alignment 回归全过;`uv run --no-sync python -m data_module.update --list` 子进程命令组合实测可用。按钮交互(AppTest 无法模拟按钮+子进程)待用户在页面实测。

## CMV 复刻第一批落地:#7/#11/#1/#12,综合分扩至 10 卡(2026-09-09)

研究 currentmarketvaluation.com 全部 15 模型并建跟踪看板 `CMV模型复刻清单.md`(探数+实施状态随时更新)。第一批 4 张卡落地,仪表盘 10 卡 + 综合分:

- **#7 收益率曲线口径修正 10Y−1Y → 10Y−3M**(CMV 原版口径,`curve_10y3m.py`;旧 `curve_10y1y` 留别名)
- **#11 两融杠杆变化**:`margin/margin_total.parquet`(沪深合并日频 2010-04 起),CMV 口径 = 12M 余额变化占全A总市值比
- **#1 巴菲特指标**:`valuation/a_market_cap.parquet`(东财月度两市总市值 2008-01 起,**一次调用全量**)+ `macro/gdp_quarterly.parquet`(季度累计 GDP,卡内滚动四季求和)。分子踩坑:交易所官网均非长源(上交所 commonQuery 只覆盖近月,乐咕已下架),东财 datacenter `RPT_ECONOMY_STOCK_STATISTICS` 是正解
- **#12 信用利差**:`rates/credit_ts_aaa.parquet`(中短票 AAA 曲线 2006-12 起,按月分块抓),AAA−国债 10Y;中国无高收益债长历史,AAA 代理并声明

当前读数(近10年):巴菲特 **81% +1.72σ 高估**、信用利差 0.37pp +1.40σ 高估(极窄=乐观拥挤)、两融 +0.35% +0.40σ、曲线 +0.47pp +0.95σ;综合分 +0.20σ 公允(10 卡等权,快照已写入,metrics_history 33 列)。锚点回验:巴菲特 2008 底 36-39% / 2015 顶 86%,方向量级符合 A 股共识。

验证:frontend_alignment 全卡片 AppTest 过;gem_signal/baselines/faber_strategy_app 回归全绿。

### 第二批(2026-09-09 下半场):#14 EPU / #9 Sahm / #8 PMI,仪表盘 14 模型

- **EPU**:`macro/epu_china`(1995-01 起,官方停滞止于 2023-11,卡面声明滞后),743 点 −1.00σ 低估档
- **Sahm**:`macro/urban_unemployment`(2018-01 起 103 点;item 列带尾部空格须 strip),缺口 0.00pp 未触发;短样本不参与综合分
- **PMI 景气动量**:`macro/pmi_official`(2008-01 起),PMI−12MMA +0.10pp −0.07σ;LEI 降级替代,进综合分(第 11 张)
- **设计决策**:EPU/Sahm 独立展示不进综合分——dropna 口径下停滞数据会使序列末端缺失、短样本拖后历史起点;两卡价值在独立判读
- 综合分 11 卡等权 +0.18σ 公允;快照已更新;frontend_alignment 14 项遍历过

**CMV 复刻总进度:15 模型 ✅ 11 落地 / 🔴 3 卡壳(#15 无源、#2/#3 需长历史财务数据) / ❌ 1 跳过(#10)**。

## IC 自证:综合分 3 年 IC −0.72,σ 方法预测力成立(2026-09-09)

第 4 步余量头名"散点图(估值分 vs 未来收益)"落地:`src/metrics/validate.py`(纯函数:expanding 估值z × 沪深300 未来 1/3 年月度收益的 Spearman 秩相关)+ 仪表盘底部 IC 自证区块(IC 总表 + 散点 + OLS 趋势线;DESIGN.md 已登记"模型页附属区块")。

**实测 IC(2026-09-09,expanding 当时视角无前视)**:

| 卡 | IC 1年 (n) | IC 3年 (n) |
|---|---|---|
| **综合分** | −0.35 (72) | **−0.72 (55)** |
| 巴菲特指标 | −0.50 (162) | **−0.78 (138)** |
| 两融 | −0.30 (119) | −0.65 (102) |
| ERP | −0.31 (186) | −0.51 (162) |
| PE | −0.25 (197) | −0.58 (173) |
| 均线偏离 | −0.23 (224) | −0.36 (200) |
| 股息差 | −0.39 (186) | −0.35 (162) |
| QVIX / 利率 / 曲线 / PMI / 利差 | 方向不稳或接近 0 | 同左 |

判读:① **σ 方法的核心自证通过**——综合分与未来 3 年收益秩相关 −0.72,估值类卡(巴菲特/ERP/PE/两融)1/3 年 IC 一致为负且量级可观,"便宜→未来收益高"成立;② 巴菲特卡单卡 IC 最高(3 年 −0.78),第一批的分子攻坚值回票价;③ 利率/曲线/PMI/QVIX 方向不稳(宏观与情绪变量本非估值锚,不进共识方向);④ 综合分 3 年口径 n≈55 样本小,页面已声明"仅供参考"。

工程:AppTest 坑 +1——页面多 radio 时下标取元素会错位,**必须按 label 取**;表数断言 2→3。回归全绿。

## 架构说明.md 全量更新至现状(2026-08-26)

旧版停在 08-24(指标层刚落地时),缺整个 `src/strategy/` 策略层、`app/paseo.py` 统一入口、`components.py`、Faber 策略页与回测工作台。本次按现状重写:

- 全景图重画:raw → (strategy/metrics → derived) → app 四层单向流,metrics_history 快照例外标注
- 新增 `src/strategy/` 整节(contract/panels/信号/三引擎/qdii_filter/编排/CLI 各行职责与依赖关系)
- metrics 节补 aggregate/snapshot/curve_10y1y/dividend_spread/more_cards;app 节补统一入口与四页;scripts 节改为测试+探针分类清单
- derived 目录结构补 signals/backtests/metrics_history;报告层补 QuantStats HTML
- 关键约定从 4 条扩到 6 条(+新增估值卡三步、页面只读不算);新增"页面入口与运行节奏"、"当前状态与余量"两节(取代过时的"与未来步骤的接口")
