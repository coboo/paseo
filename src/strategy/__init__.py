"""策略层(设计文档第十节:基线 1 双动量 GEM 中美本土化)。

模块地图:contract(契约)→ gem_signal(信号)→ engine(pandas/bt 双引擎)
→ qdii_filter(溢价门控)→ run_gem(两层编排)→ report(QuantStats)→ backtest(CLI)。
"""
from .contract import BOND, HS300, SPX, BacktestResult, StrategyConfig
from .gem_signal import (
    ETF_MAP,
    build_index_panel,
    compute_gem_signals,
    month_end_anchors,
    save_signals,
)
from .run_gem import build_open_panel, compare_layers, run_all, run_etf_layer, run_index_layer

__all__ = [
    "BOND", "HS300", "SPX",
    "BacktestResult", "StrategyConfig",
    "ETF_MAP", "build_index_panel", "compute_gem_signals", "month_end_anchors", "save_signals",
    "build_open_panel", "compare_layers", "run_all", "run_etf_layer", "run_index_layer",
]
