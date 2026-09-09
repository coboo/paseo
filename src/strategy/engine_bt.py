"""bt 组合回测引擎(工具栈合规执行器 + 与 pandas 引擎对账,设计文档第十节)。

bt 1.2.0 语义(源码核实):RunMonthly() 默认月初首个交易日触发;
WeighTarget(weights) 按 target.now in weights.index 设权;以喂入面板价格成交
——喂开盘价面板即"次日开盘成交"。bt 不做费用建模(费用在 pandas 引擎),
口径差:净值基数 100、索引前自动加前置日、份额取整(~1e-5 舍入)。
"""
from __future__ import annotations

import pandas as pd

from .contract import BacktestResult, StrategyConfig

try:  # bt 可用性由 engine.py 判定后才会调到这里
    import bt
    BT_AVAILABLE = True
except ImportError:  # pragma: no cover
    BT_AVAILABLE = False


def run_monthly_switch_bt(name: str, layer: str,
                           open_prices: pd.DataFrame,
                           exec_target: pd.Series,
                           cfg: StrategyConfig) -> BacktestResult:
    """与 pandas 引擎同输入的 bt 实现(零费用)。用于交叉验证,不作主管道。"""
    if not BT_AVAILABLE:
        raise ImportError("bt 不可用")

    # 权重表:仅执行日行,目标资产 100%
    weights = pd.get_dummies(exec_target).astype(float)
    weights = weights.reindex(columns=open_prices.columns, fill_value=0.0)

    strat = bt.Strategy(name, [
        bt.algos.RunMonthly(),
        bt.algos.WeighTarget(weights),
        bt.algos.Rebalance(),
    ])
    res = bt.run(bt.Backtest(strat, open_prices), progress_bar=False)
    prices = res.prices
    if hasattr(prices, "columns"):  # 单策略返回 DataFrame
        prices = prices.iloc[:, 0]

    # 归一(基数 100 → 1)并对齐面板索引(bt 会自动加前置日)
    nav = prices / prices.iloc[0]
    nav = nav.reindex(open_prices.index).ffill()
    first_exec = exec_target.index.min()
    nav = nav[nav.index >= first_exec]
    ret = nav.pct_change().fillna(0.0)
    drawdown = nav / nav.cummax() - 1.0

    effective = exec_target.reindex(nav.index).ffill()
    changed = effective.ne(effective.shift(1)) & effective.notna()
    from .engine_pandas import _summary
    return BacktestResult(
        name=name, layer=layer, config=cfg,
        nav=nav, ret=ret, position=effective, drawdown=drawdown,
        trades=pd.DataFrame(columns=["exec_date", "from", "to", "exec_price"]),
        summary=_summary(nav, ret, changed.sum()),
        updated=f"{nav.index.max():%Y-%m-%d}",
    )
