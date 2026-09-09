"""组合权重版回测引擎(基线 2/3/4 共用,设计文档第十一节"引擎泛化")。

与单资产版同一无未来函数约定:区间 (t−1, t] 的收益记给该区间的权重组合,
换仓发生在开盘边界——W[t] = 执行日权重表前向填充后右移一日,只依赖 ≤ t−1 已知信息。
日收益 = Σᵢ W[t]ᵢ · r[t]ᵢ − 换手 × 单边成本;现金腿作为面板中的 cash 资产列参与。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .contract import BacktestResult, StrategyConfig
from .engine_pandas import _summary


def run_monthly_weights(name: str, layer: str,
                        prices: pd.DataFrame,
                        weights_exec: pd.DataFrame,
                        cfg: StrategyConfig) -> BacktestResult:
    """月度组合再平衡回测。

    prices:开盘价面板(含 cash 列,资产键与 weights_exec 列一致);
    weights_exec:index=执行日(每月首个交易日), 每行权重和 = 1.0。
    """
    first_exec = weights_exec.index.min()
    idx = prices.index[prices.index >= first_exec]
    prices = prices.loc[idx, weights_exec.columns]

    holding = weights_exec.reindex(idx).ffill().shift(1)   # 区间权重(收益归属)
    effective = weights_exec.reindex(idx).ffill()          # 生效权重(展示/调仓)

    ret_asset = prices.pct_change()
    port_ret = (holding * ret_asset).sum(axis=1)

    # 换手成本:执行日 Σ|Δw|(生效权重变化)结算于次一净值日
    turnover = effective.diff().abs().sum(axis=1).fillna(0.0)
    cost_factor = 1.0 - turnover * cfg.cost_bps / 1e4

    factor = (1.0 + port_ret.fillna(0.0)) * cost_factor.shift(1).fillna(1.0)
    nav = factor.cumprod()
    ret = nav.pct_change().fillna(0.0)

    # 持仓标签:生效权重 >0 的资产拼接(展示用)
    position = effective.apply(
        lambda row: "+".join(c for c in effective.columns if row.get(c, 0) > 1e-9),
        axis=1)

    changes = effective.diff().abs().sum(axis=1) > 1e-9
    trades_rows = []
    for d in idx[changes]:
        w = effective.loc[d]
        trades_rows.append({
            "exec_date": d,
            "to": "+".join(c for c in effective.columns if w.get(c, 0) > 1e-9) or "cash",
            "weights": {c: round(float(w.get(c, 0.0)), 4) for c in effective.columns if w.get(c, 0) > 1e-9},
        })

    drawdown = nav / nav.cummax() - 1.0
    summary = _summary(nav, ret, changes.sum())
    return BacktestResult(
        name=name, layer=layer, config=cfg,
        nav=nav, ret=ret, position=position, drawdown=drawdown,
        trades=pd.DataFrame(trades_rows), summary=summary,
        updated=f"{idx.max():%Y-%m-%d}",
    )
