"""策略层统一契约(设计文档第十节:基线 1 双动量 GEM)。

与指标层 MetricResult 平行:StrategyConfig 承载"不改一个数"的原参数,
BacktestResult 承载回测全量明细(净值/持仓/调仓/摘要),供 CLI 落盘与展示层消费。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# 持仓三态(信号层口径;执行层为 ETF 代码,由 run_gem 映射)
SPX = "spx"
HS300 = "hs300"
BOND = "bond"


@dataclass
class StrategyConfig:
    """双动量 GEM 参数(第一轮原参数复现,验证纪律:不改一个数)。"""

    lookback_months: int = 12        # 回望窗口(日历月,原版口径)
    rf_col: str = "yield_3m"         # 无风险基准列(中债 3M,日利率 ACT/365 复利)
    cost_bps: float = 0.0            # 单边成本 bp(基线 0,敏感性另跑 5/10)
    premium_cap: float = 0.03        # QDII 溢价买入门(仅执行层对照,设计文档第十节)
    premium_anchor_window: int = 63  # 溢价代理滚动中位数窗口(交易日)
    as_of: str | None = None         # 数据截止(测试注入截断,防未来数据泄漏)


@dataclass
class BacktestResult:
    """单层回测结果。layer ∈ {"index"(信号层·指数), "etf"(执行层·ETF)}。"""

    name: str
    layer: str
    config: StrategyConfig
    nav: pd.Series                 # 日净值(DatetimeIndex,首执行日=1)
    ret: pd.Series                 # 日收益(已扣 cost_bps)
    position: pd.Series            # 每日区间持仓(spx/hs300/bond 或 ETF 代码)
    drawdown: pd.Series            # 回撤(负值小数)
    trades: pd.DataFrame           # 调仓记录
    summary: dict = field(default_factory=dict)  # cagr/mdd/sharpe/...
    updated: str = ""              # 数据截止日 YYYY-MM-DD
