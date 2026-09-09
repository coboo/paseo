"""双动量 GEM 敏感性扫描(第 3 步验证,设计文档第八节纪律 2:要参数高原不要孤峰)。

主网格:回望窗口(日历月){3,6,9,12,15,18,24,30},统一共同区间 2009-02 起
(30M 窗口完整利率窗的自然起点),信号层口径(干净价格)。
vectorbt 做 12M 窗口的净值级交叉验证(from_orders + targetpercent + 现金共享,
喂开盘面板即开盘成交)——满足工具栈定稿,并对 pandas 主管道形成三库互证。

用法:PYTHONPATH=src uv run python -m strategy.sweep
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from data_module.storage import read_raw, save_derived

from .contract import BacktestResult, StrategyConfig
from .engine_pandas import run_monthly_switch_pandas
from .gem_signal import compute_gem_signals
from .run_gem import build_open_panel

# 回望网格(月):原版 12 居中,两侧各 3-4 档覆盖高原检验所需邻域
LOOKBACKS = [3, 6, 9, 12, 15, 18, 24, 30]
# 全窗口可比区间起点(执行日):30M 窗口在 2008 内利率窗不完整,首个完整信号 2008-09
COMMON_START = pd.Timestamp("2009-02-01")


def _benchmark_stats(idx: pd.DatetimeIndex) -> tuple[float, float]:
    """共同区间沪深300 买入持有的 (cagr, mdd)。"""
    hs = read_raw("index_daily/index_000300.parquet").set_index("date")["close"]
    hs = hs[hs.index >= idx.min()]
    cagr = float((hs.iloc[-1] / hs.iloc[0]) ** (252 / len(hs)) - 1)
    mdd = float((hs / hs.cummax() - 1).min())
    return cagr, mdd


def run_one_lookback(lb: int, panel: pd.DataFrame | None = None) -> BacktestResult:
    """单窗口信号层回测(BacktestResult)。"""
    cfg = StrategyConfig(lookback_months=lb)
    if panel is None:
        panel = build_open_panel("index")
    sig = compute_gem_signals(cfg)
    exec_target = sig.set_index("exec_date")["position"].dropna()
    return run_monthly_switch_pandas(f"GEM lookback={lb}M", "index", panel, exec_target, cfg)


def sweep_lookback(lookbacks: list[int] = LOOKBACKS) -> pd.DataFrame:
    """主网格扫描:每窗口在共同区间算指标,附通过线判读列。"""
    panel = build_open_panel("index")
    rows = []
    for lb in lookbacks:
        r = run_one_lookback(lb, panel)
        nav = r.nav[r.nav.index >= COMMON_START]
        ret = r.ret[r.ret.index >= COMMON_START]
        if len(nav) < 252:
            continue
        yrs = len(nav) / 252.0
        cagr = float(nav.iloc[-1] ** (1 / yrs) - 1)
        mdd = float((nav / nav.cummax() - 1).min())
        sharpe = float(ret.mean() / ret.std() * 252 ** 0.5) if ret.std() > 0 else float("nan")
        bh_cagr, bh_mdd = _benchmark_stats(nav.index)
        dd_cut = 1 - abs(mdd) / abs(bh_mdd)
        rows.append({
            "lookback_m": lb,
            "n_signals": int(r.position.groupby(r.position.index.to_period("M")).first().count()),
            "cagr": cagr, "mdd": mdd, "sharpe": sharpe,
            "calmar": cagr / abs(mdd) if mdd < 0 else float("nan"),
            "dd_cut": dd_cut,
            "cagr_ratio": cagr / bh_cagr,
            "pass_line": bool(dd_cut >= 0.4 and cagr >= 0.7 * bh_cagr),
        })
    return pd.DataFrame(rows)


def vbt_crosscheck(lb: int = 12, tol: float = 1e-3) -> float:
    """vectorbt 净值级交叉验证:from_orders + targetpercent + cash_sharing。

    喂开盘面板 → 以开盘价成交,与主管道同口径。返回最大日收益差(相对)。
    差异来源:vbt 的 targetpercent 按当期市值再平衡、残差现金计息口径;
    量级应在 1e-4~1e-3(远小于任何参数敏感度)。
    """
    import vectorbt as vbt

    panel = build_open_panel("index")
    r = run_one_lookback(lb, panel)
    pos = r.position.reindex(panel.index).ffill().dropna().astype(str)

    # 目标权重:每日 one-hot(执行日切换;vbt 以 targetpercent=1 全仓、=0 清仓表达)
    weights = pd.get_dummies(pos).astype(float)
    weights = weights.reindex(columns=panel.columns, fill_value=0.0)
    pf = vbt.Portfolio.from_orders(
        close=panel.loc[pos.index], size=weights.loc[pos.index],
        size_type="targetpercent", group_by=True, cash_sharing=True,
        call_seq="auto", init_cash=1_000_000,
    )
    vbt_nav = pf.value() / pf.value().iloc[0]
    start = max(vbt_nav.index.min(), r.nav.index.min())
    a = r.nav[r.nav.index >= start].iloc[:len(vbt_nav)]
    b = vbt_nav[vbt_nav.index >= start].iloc[:len(a)]
    diff = float((a.pct_change().fillna(0) - b.pct_change().fillna(0)).abs().max())
    assert diff < tol, f"vbt 交叉验证失败: 最大日收益差 {diff:.2e} ≥ {tol:.0e}"
    return diff


def plateau_verdict(table: pd.DataFrame) -> str:
    """高原/孤峰/结构性失败判读(验证纪律 2)。"""
    passed = table[table["pass_line"]]
    near = table[table["lookback_m"].between(9, 15)]  # 原版 12M 邻域
    n_pass_near = int(near["pass_line"].sum())

    if len(passed) == 0:
        return ("结构性失败:全域 {0} 个窗口无一达到通过线(回撤砍 40%+ 且年化 ≥70%)——"
                "不是参数选择问题,是 12 月级别动量轮动在 A 股急牛急熊环境的结构性水土不服。"
                "按验证纪律,本土化 GEM 判放弃(或降级为反面参照)。").format(len(table))
    if n_pass_near >= 3:
        return (f"参数高原:12M 邻域(9-15){n_pass_near}/4 达标,通过窗口 "
                f"{passed['lookback_m'].tolist()},参数取高原中心稳健。")
    if passed["lookback_m"].min() <= 6:
        return (f"短回望强于长回望:达标窗口 {passed['lookback_m'].tolist()} 全部远离原版 12M——"
                "12M 本身在孤峰之外,原参数复现结论(未通过)稳健;短窗达标提示 A 股需要更快"
                "的趋势识别,属策略变体而非 GEM 本土化,须过 walk-forward+holdout 才可采信。")
    return (f"参数孤峰嫌疑:达标窗口 {passed['lookback_m'].tolist()} 不构成以 12M 为中心的"
            "连续高原,按纪律视为噪音拟合,不采纳。")


def save_sweep(table: pd.DataFrame) -> Path:
    return save_derived(table, "backtests/gem_cn_sweep.parquet")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="双动量 GEM 回望窗口敏感性扫描")
    parser.add_argument("--lookbacks", type=int, nargs="*", default=LOOKBACKS)
    args = parser.parse_args(argv)

    print(f"敏感性扫描:回望 {args.lookbacks} 月,共同区间 {COMMON_START:%Y-%m} 起\n")
    table = sweep_lookback(args.lookbacks)
    print(table.to_string(index=False,
                          formatters={"cagr": "{:.2%}".format, "mdd": "{:.1%}".format,
                                      "dd_cut": "{:.0%}".format, "cagr_ratio": "{:.1f}".format,
                                      "sharpe": "{:.2f}".format, "calmar": "{:.2f}".format}))
    print()
    verdict = plateau_verdict(table)
    print(f"判读:{verdict}")

    try:
        diff = vbt_crosscheck()
        print(f"\nvectorbt 交叉验证(12M):最大日收益差 {diff:.1e} < 1e-3 OK")
    except Exception as e:  # noqa: BLE001 — 交叉验证失败不阻断扫描
        print(f"\n[warn] vbt 交叉验证未通过:{type(e).__name__}: {str(e)[:120]}")

    path = save_sweep(table)
    print(f"\n落盘 → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
