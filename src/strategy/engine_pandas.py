"""纯 pandas 回测引擎(主管道,精确口径 + 费用建模)。

成交约定(设计文档第十节,杜绝未来函数):
区间 (t−1, t] 的收益记给该区间持有的资产,换仓发生在开盘边界。
实现:r[t] = O[t][pos[t]] / O[t−1][pos[t]] − 1,其中 pos[t] = 执行日目标前向填充后右移一日
——pos[t] 只依赖 ≤ t−1 收盘已知的信息(信号在 t−1 月末已产生,t 日开盘执行)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .contract import BacktestResult, StrategyConfig


def run_monthly_switch_pandas(name: str, layer: str,
                              open_prices: pd.DataFrame,
                              exec_target: pd.Series,
                              cfg: StrategyConfig) -> BacktestResult:
    """月度全仓切换回测。

    open_prices:开盘价面板(DatetimeIndex × 资产键,已对齐);
    exec_target:index=执行日(每月首个交易日), value=资产键。
    净值从首个执行日开盘起算(=1);cost_bps 为单边成本,每次换仓扣 2×(卖旧买新)。
    """
    first_exec = exec_target.index.min()
    idx = open_prices.index[open_prices.index >= first_exec]
    prices = open_prices.loc[idx]

    # pos[t]:区间 (t−1, t] 持有的资产 = t−1 日已生效目标 → ffill 后 shift(1)
    holding = exec_target.reindex(idx).ffill().shift(1)      # 区间口径(收益归属)
    effective = exec_target.reindex(idx).ffill()             # 生效口径(展示/调仓记录)

    ret_asset = prices.pct_change()
    col_idx = pd.Series(range(prices.shape[1]), index=prices.columns)
    picks = holding.map(col_idx).fillna(-1).astype(int).to_numpy()  # −1 = 首日无区间持仓
    ret = pd.Series(
        np.where(picks >= 0,
                 ret_asset.to_numpy()[np.arange(len(idx)), np.clip(picks, 0, None)],
                 np.nan),
        index=idx,
    )

    # 换仓费用:执行日(目标变化日)结算,卖旧买新各收单边 → 因子 (1 − 2×cost_bps/1e4)
    switched = effective.ne(effective.shift(1)) & effective.notna()
    cost_factor = pd.Series(1.0, index=idx)
    cost_factor[switched] = 1.0 - 2.0 * cfg.cost_bps / 1e4

    factor = (1.0 + ret.fillna(0.0)) * cost_factor.shift(1).fillna(1.0)
    nav = factor.cumprod()
    ret_final = nav.pct_change().fillna(0.0)

    # 调仓记录:effective 变化点(首个生效日 = 建仓)
    changes = effective.ne(effective.shift(1)) & effective.notna()
    trades_rows = []
    prev_pos = None
    for d in idx[changes]:
        to = effective.loc[d]
        trades_rows.append({
            "exec_date": d,
            "from": prev_pos if prev_pos is not None else "cash",
            "to": to,
            "exec_price": float(prices.loc[d, to]),
        })
        prev_pos = to

    drawdown = nav / nav.cummax() - 1.0
    summary = _summary(nav, ret_final, switched.sum())

    return BacktestResult(
        name=name, layer=layer, config=cfg,
        nav=nav, ret=ret_final, position=effective, drawdown=drawdown,
        trades=pd.DataFrame(trades_rows), summary=summary,
        updated=f"{idx.max():%Y-%m-%d}",
    )


def _summary(nav: pd.Series, ret: pd.Series, switch_count: int) -> dict:
    """年化/回撤/夏普等摘要(年化基数 252 交易日,夏普 rf=0)。"""
    n_years = len(nav) / 252.0
    cagr = float(nav.iloc[-1] ** (1.0 / n_years) - 1.0) if n_years > 0 else float("nan")
    mdd = float((nav / nav.cummax() - 1.0).min())
    vol = float(ret.std() * np.sqrt(252))
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else float("nan")
    return {
        "cagr": cagr, "mdd": mdd, "vol": vol, "sharpe": sharpe,
        "calmar": cagr / abs(mdd) if mdd < 0 else float("nan"),
        "switch_count": int(switch_count), "days": len(nav),
    }
