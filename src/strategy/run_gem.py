"""双动量 GEM 两层回测编排(信号层·指数 2008-02 起 / 执行层·ETF 2014-02 起)。

信号-执行分离(AGENTS.md):信号层用干净价格(spx×usdcny、沪深300 指数、拼接债券腿);
执行层用 ETF qfq 开盘价(513500/510310),防御腿沿用拼接序列(收益率口径正确,
2017 前指数段无开盘价,以前收盘近似——设计文档第十节口径声明)。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import DERIVED_DIR, read_raw, save_derived

from .contract import BacktestResult, StrategyConfig
from .engine import run_monthly_switch
from .gem_signal import compute_gem_signals
from .qdii_filter import apply_premium_gate, premium_proxy


def _bond_leg() -> pd.DataFrame:
    """拼接债券腿(derived):date, close。"""
    return pd.read_parquet(DERIVED_DIR / "aligned" / "bond_leg_spliced_511260.parquet")[["date", "close"]]


def build_open_panel(layer: str, start: str | None = None) -> pd.DataFrame:
    """开盘价面板(资产键:信号层 spx/hs300/bond;执行层 ETF 代码)。

    面板骨架 = A股交易日(沪深300/510310 的日期)——国庆/春节等长假期不得混入,
    否则月首触发日与执行日错位(bt RunMonthly 以面板日期判月界)。
    海外源(美股/汇率)在骨架上缺失时 ffill(limit=5) 补假日错位;spx 开盘 × 汇率。
    """
    if layer == "index":
        spx = read_raw("index_global/spx_inx.parquet").set_index("date")["open"].rename("spx")
        hs = read_raw("index_daily/index_000300.parquet").set_index("date")["open"].rename("hs300")
        bond = _bond_leg().set_index("date")["close"].rename("bond")  # 拼接段无开盘价,前收盘近似
        fx = read_raw("fx/usdcny.parquet").set_index("date")["close"].rename("fx")
        idx = hs.index                                  # 骨架 = A股交易日
        df = pd.concat([hs, bond, fx.reindex(idx).ffill(limit=5),
                        spx.reindex(idx).ffill(limit=5)], axis=1).dropna()
        df["spx"] = df["spx"] * df["fx"]
        df = df.drop(columns=["fx"])
    elif layer == "etf":
        p500 = read_raw("etf_daily/etf_qfq_513500.parquet").set_index("date")["open"].rename("513500")
        p300 = read_raw("etf_daily/etf_qfq_510310.parquet").set_index("date")["open"].rename("510310")
        bond = _bond_leg().set_index("date")["close"].rename("511260")
        idx = p300.index                                # 骨架 = A股交易日
        df = pd.concat([p300, p500.reindex(idx).ffill(limit=5),
                        bond.reindex(idx).ffill(limit=5)], axis=1).dropna()
    else:
        raise ValueError(f"未知 layer: {layer}")

    if start is not None:
        df = df[df.index >= start]
    return df


def run_index_layer(cfg: StrategyConfig = StrategyConfig()) -> BacktestResult:
    """信号层回测(指数价格,2008-02 首执行)。"""
    sig = compute_gem_signals(cfg)
    panel = build_open_panel("index")
    exec_target = sig.set_index("exec_date")["position"].dropna()
    res = run_monthly_switch("双动量GEM·信号层(指数)", "index", panel, exec_target, cfg)
    res.trades = _attach_signal_dates(res.trades, sig, "position")
    return res


def run_etf_layer(cfg: StrategyConfig = StrategyConfig()) -> BacktestResult:
    """执行层回测(ETF qfq,2014-02 首执行;含 QDII 溢价买入门对照)。"""
    sig = apply_premium_gate(compute_gem_signals(cfg), cfg.premium_cap)
    panel = build_open_panel("etf")
    exec_target = sig.set_index("exec_date")["etf_target"].dropna()
    # 执行层受 ETF 上市约束:首个可用执行日 = 面板覆盖的最早执行日(2014-02)
    exec_target = exec_target[exec_target.index >= panel.index.min()]
    res = run_monthly_switch("双动量GEM·执行层(ETF)", "etf", panel, exec_target, cfg)
    res.trades = _attach_signal_dates(res.trades, sig, "etf_target")
    res.summary["blocked_months"] = int(sig["blocked_by_premium"].sum())
    return res


def _attach_signal_dates(trades: pd.DataFrame, sig: pd.DataFrame, col: str) -> pd.DataFrame:
    """给调仓记录补信号日与溢价信息。"""
    if trades.empty:
        return trades
    sig_map = sig.set_index("exec_date")
    trades = trades.copy()
    trades["signal_date"] = sig_map["date"].reindex(trades["exec_date"]).values
    if "premium_513500" in sig.columns:
        trades["premium_513500"] = sig_map["premium_513500"].reindex(trades["exec_date"]).values
        trades["blocked_by_premium"] = sig_map["blocked_by_premium"].reindex(trades["exec_date"]).values
    return trades


def compare_layers(a: BacktestResult, b: BacktestResult) -> pd.DataFrame:
    """两层共同区间对照:年化差/末端净值比/日收益差分位数/QDII 跳过月数。"""
    start = max(a.nav.index.min(), b.nav.index.min())
    ra, rb = a.ret[a.ret.index >= start], b.ret[b.ret.index >= start]
    n = min(len(ra), len(rb))
    diff = (ra.iloc[:n] - rb.iloc[:n]).dropna()

    def _cagr(nav: pd.Series, s: pd.Timestamp) -> float:
        seg = nav[nav.index >= s]
        yrs = len(seg) / 252.0
        return float(seg.iloc[-1] ** (1 / yrs) - 1) if yrs > 0 else float("nan")

    rows = {
        "共同区间起点": f"{start:%Y-%m-%d}",
        "年化(信号层)": _cagr(a.nav, start),
        "年化(执行层)": _cagr(b.nav, start),
        "年化差(执行−信号)": _cagr(b.nav, start) - _cagr(a.nav, start),
        "日收益差 p50": float(diff.median()),
        "日收益差 p95": float(diff.quantile(0.95)),
        "日收益差 p99": float(diff.quantile(0.99)),
        "QDII 溢价跳过月数": b.summary.get("blocked_months", 0),
    }
    return pd.DataFrame({"指标": list(rows.keys()), "值": list(rows.values())})


def run_all(cfg: StrategyConfig = StrategyConfig()) -> dict[str, BacktestResult]:
    """两层回测 + 对照 + derived/backtests/ 落盘(全量覆盖)。"""
    idx_res = run_index_layer(cfg)
    etf_res = run_etf_layer(cfg)

    for res, tag in [(idx_res, "index"), (etf_res, "etf")]:
        df = pd.DataFrame({
            "date": res.nav.index, "nav": res.nav.values,
            "ret": res.ret.values, "position": res.position.values,
            "drawdown": res.drawdown.values,
        })
        save_derived(df, f"backtests/gem_cn_{tag}.parquet")
        save_derived(res.trades, f"backtests/gem_cn_trades_{tag}.parquet")

    return {"index": idx_res, "etf": etf_res}
