"""红利低波簇打分轮动日频回测（设计文档十三节；模式同 strategy/engine_weights.py）。

成交约定与 engine_weights.run_monthly_weights 完全一致（复用其模式）：
- 权重表索引 = 月末锚点 → 映射到次一交易日执行（信号次日成交，无未来函数）；
- 区间权重 = 执行日权重 ffill + shift(1)（区间 (t−1, t] 收益记给 t−1 已生效权重）；
- 日收益 = Σ wᵢ·rᵢ − 换手 × 单边成本；换手 = 生效权重 Σ|Δw|（含 cash 列，同 Faber 引擎口径）；
- 闲置资金 = cash 资产列 = 中债 3M 日利率 ACT/365 复利（strategy.panels.cash_price，沿用 Faber 现金腿）。

面板（骨架 = A 股交易日，同 GEM/Faber 踩坑结论）：
- 信号层：H30269/930955 用全收益指数收盘（index_tr_H20269/H20955），
  515450/159545 用基金累计净值代理（factors.py 既定口径：净值天然无溢价）；
  沪深300 基准 = index_tr_H00300（全收益）。
- 执行层：四 ETF 前复权收盘，共同区间 = 数据交集起点（自动 dropna，如实报告起点）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_module.storage import read_raw

from strategy.contract import BacktestResult, StrategyConfig
from strategy.engine_pandas import _summary
from strategy.panels import cash_price

from .strategy import CODES

# 信号层资产键 → raw 数据（中证系全收益 / 基金净值代理）
_SIGNAL_FILES = {
    "H30269": ("index_daily/index_tr_H20269.parquet", "close"),
    "930955": ("index_daily/index_tr_H20955.parquet", "close"),
    "515450": ("index_daily/spdiv50_nav_515450.parquet", "acc_nav"),
    "159545": ("index_global/hshylv_nav_159545.parquet", "acc_nav"),
}
# 执行层资产键 → ETF 代码（前复权市价，必须 qfq——AGENTS.md 信号-执行分离）
_ETF_CODES = {"H30269": "563020", "930955": "159307",
              "515450": "515450", "159545": "159545"}
_BENCH_FILE = "index_daily/index_tr_H00300.parquet"  # 沪深300 全收益（基准）


def _skeleton() -> pd.DatetimeIndex:
    """A 股交易日骨架（calendar.parquet）。"""
    return pd.DatetimeIndex(sorted(read_raw("calendar.parquet")["date"]))


def _add_cash(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["cash"] = cash_price().reindex(frame.index).ffill(limit=10)
    return frame


def build_signal_panel() -> pd.DataFrame:
    """信号层面板：四标的干净价格（全收益/净值）+ cash，A 股骨架。

    未开始的标的（515450 2020 起 / 159545 2024 起）列保留 NaN，不裁掉历史
    （其权重在无分位数据期间为零，不参与收益）；面板截断至源数据最末日期
    （日历含未来交易日，防陈旧 ffill 价格进入未来行）。
    """
    frame = pd.DataFrame(index=_skeleton())
    last_dates = []
    for code, (rel, col) in _SIGNAL_FILES.items():
        s = read_raw(rel).set_index("date")[col].astype(float)
        frame[code] = s.reindex(frame.index).ffill(limit=5)
        last_dates.append(s.index.max())
    frame = _add_cash(frame)
    frame = frame[frame.index <= min(last_dates)]  # 截断至源数据末日期
    return frame.dropna(subset=["H30269", "cash"])


def build_execution_panel() -> pd.DataFrame:
    """执行层面板：四 ETF 前复权收盘 + cash；共同区间 = 数据交集起点（dropna）。

    四 ETF 历史起点不同（563020 2023-12 / 159307、159545 2024-04 / 515450 2020-02），
    交集起点 = 2024-04-25（如实报告）；面板截断至源数据末日期。
    """
    frame = pd.DataFrame(index=_skeleton())
    last_dates = []
    for code, etf in _ETF_CODES.items():
        s = read_raw(f"etf_daily/etf_qfq_{etf}.parquet").set_index("date")["close"]
        frame[code] = s.astype(float).reindex(frame.index)
        last_dates.append(s.index.max())
    frame = _add_cash(frame)
    frame = frame[frame.index <= min(last_dates)]
    return frame.dropna(subset=CODES)  # 交集起点：159307/159545 2024-04 起


def hs300_tr() -> pd.Series:
    """沪深300 全收益收盘（基准）。"""
    return read_raw(_BENCH_FILE).set_index("date")["close"].astype(float).sort_index()


def month_end_anchors(end: pd.Timestamp) -> pd.DatetimeIndex:
    """A 股日历月末锚点，截断至 end（新鲜度纪律，同 panels.month_end_anchor_dates）。"""
    cal = _skeleton()
    anchors = cal.to_series().groupby(cal.to_period("M")).max()
    return pd.DatetimeIndex(sorted(anchors[anchors <= end].values))


def weights_at_exec(weights_anchor: pd.DataFrame,
                    panel_index: pd.DatetimeIndex) -> pd.DataFrame:
    """月末锚点权重 → 执行日权重：锚点映射到面板中次一交易日（信号次日成交）。"""
    pos = panel_index.searchsorted(weights_anchor.index, side="right")
    valid = pos < len(panel_index)
    w = weights_anchor.loc[valid]
    exec_idx = panel_index[pos[valid]]
    out = pd.DataFrame(w.to_numpy(), index=exec_idx, columns=w.columns)
    return out[~out.index.duplicated(keep="first")].sort_index()


def run_dividend_backtest(name: str, layer: str,
                          prices: pd.DataFrame,
                          weights_anchor: pd.DataFrame,
                          cost_bps: float = 5.0) -> BacktestResult:
    """月度权重型回测（设计文档十三节：单边 5bps，闲置 = 3M 复利 cash 列）。

    prices: 收盘面板（含 cash 列，资产键与权重列一致）；
    weights_anchor: 月末锚点目标权重（列=四标的，和 ≤ 簇上限，余量为现金）。
    面板起点早于首个执行日时，起点补一行零权重（起步全零从现金开始，
    闲置期 holding=零权重 + cash=1，按 3M 复利计息）。
    """
    cfg = StrategyConfig(cost_bps=cost_bps)
    w_exec = weights_at_exec(weights_anchor, prices.index)
    # 余量入 cash 列，使每行权重和 = 1.0（cash 参与换手计费，同 Faber 引擎口径）
    w_exec["cash"] = 1.0 - w_exec[CODES].sum(axis=1)
    # 起步全零：首个执行日晚于面板起点时，在起点补零权行（从现金开始）
    if len(w_exec) == 0:
        raise ValueError("weights_anchor 无可用执行日（锚点均超出面板范围）")
    if w_exec.index.min() > prices.index.min():
        zero = pd.DataFrame([[0.0] * len(CODES)], index=prices.index[:1], columns=CODES)
        zero["cash"] = 1.0
        w_exec = pd.concat([zero, w_exec])

    first_exec = w_exec.index.min()
    idx = prices.index[prices.index >= first_exec]
    prices = prices.loc[idx, w_exec.columns]

    holding = w_exec.reindex(idx).ffill().shift(1)   # 区间权重（收益归属）
    effective = w_exec.reindex(idx).ffill()          # 生效权重（展示/调仓）

    ret_asset = prices.pct_change()
    port_ret = (holding * ret_asset).sum(axis=1)

    # 换手成本：执行日 Σ|Δw| 结算于次一净值日（模式同 engine_weights）
    turnover = effective.diff().abs().sum(axis=1).fillna(0.0)
    cost_factor = 1.0 - turnover * cfg.cost_bps / 1e4
    factor = (1.0 + port_ret.fillna(0.0)) * cost_factor.shift(1).fillna(1.0)
    nav = factor.cumprod()
    ret = nav.pct_change().fillna(0.0)

    position = effective.apply(
        lambda row: "+".join(c for c in CODES if row.get(c, 0) > 1e-9) or "cash",
        axis=1)

    changes = effective[CODES].diff().abs().sum(axis=1) > 1e-9
    trades_rows = []
    for d in idx[changes]:
        w = effective.loc[d]
        trades_rows.append({
            "exec_date": d,
            "to": "+".join(c for c in CODES if w.get(c, 0) > 1e-9) or "cash",
            "weights": {c: round(float(w[c]), 4) for c in CODES if w[c] > 1e-9},
            "gross": round(float(sum(w[c] for c in CODES)), 4),
        })

    drawdown = nav / nav.cummax() - 1.0
    summary = _summary(nav, ret, int(changes.sum()))
    years = len(nav) / 252.0
    summary["turnover_annual"] = float(turnover.sum() / years)  # 年化单边换手（含 cash 侧）
    summary["gross_avg"] = float(effective[CODES].sum(axis=1).mean())  # 平均簇仓位
    return BacktestResult(
        name=name, layer=layer, config=cfg,
        nav=nav, ret=ret, position=position, drawdown=drawdown,
        trades=pd.DataFrame(trades_rows), summary=summary,
        updated=f"{idx.max():%Y-%m-%d}",
    )


def cluster_equal_bh(panel: pd.DataFrame,
                     start: pd.Timestamp | None = None,
                     end: pd.Timestamp | None = None) -> pd.Series:
    """簇等权 B&H 净值：期初对当时有数据的标的等权（各 1/n），买入持有不再平衡。

    四标的信号数据起点不齐（2018/2019/2023/2025），等权成员 = 窗口首日有数据的标的
    （如 2020 起窗口 = H30269+930955 各 50%）；不中途加入新标的（B&H 口径）。
    """
    px = panel[CODES]
    if start is not None:
        px = px[px.index >= start]
    if end is not None:
        px = px[px.index <= end]
    avail = [c for c in CODES if px[c].notna().iloc[0]]
    nav = (px[avail] / px[avail].iloc[0]).mean(axis=1)
    return nav


def benchmark_stats(nav: pd.Series) -> dict:
    """一段净值序列的 (年化, MDD, 夏普)（年化基数 252，夏普 rf=0，同 _summary 口径）。"""
    ret = nav.pct_change().fillna(0.0)
    n_years = len(nav) / 252.0
    cagr = float(nav.iloc[-1] ** (1.0 / n_years) - 1.0)
    mdd = float((nav / nav.cummax() - 1.0).min())
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else float("nan")
    return {"cagr": cagr, "mdd": mdd, "sharpe": sharpe}
