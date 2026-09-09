"""回测引擎统一入口。

主管道走 pandas 实现(数值精确、含费用建模、净值语义干净);
bt 实现保留为工具栈合规与交叉验证(测试对账 <1e-4,见 scripts/test_gem_backtest.py)。
"""
from __future__ import annotations

import pandas as pd

from .contract import BacktestResult, StrategyConfig
from .engine_pandas import run_monthly_switch_pandas


def run_monthly_switch(name: str, layer: str,
                       open_prices: pd.DataFrame,
                       exec_target: pd.Series,
                       cfg: StrategyConfig = StrategyConfig()) -> BacktestResult:
    """月度全仓切换回测入口。

    open_prices:开盘价面板(DatetimeIndex × 资产键);
    exec_target:index=执行日(每月首个交易日), value=资产键。
    """
    return run_monthly_switch_pandas(name, layer, open_prices, exec_target, cfg)
