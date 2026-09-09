"""回测三库冒烟探针(一次性,不进主管道)。

验证 vectorbt / bt / quantstats 在 pandas 3.0.5 + numpy 2.5.2 下的真实可用性,
输出各库冒烟结论,供 fallback 决策(设计方案「基线 1」小节记录)。

用法:PYTHONPATH=src uv run python scripts/probe_backtest_libs.py
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


def probe_vectorbt() -> tuple[bool, str]:
    """2 资产 × 500 日随机面板:from_signals + rolling 动量。"""
    try:
        import vectorbt as vbt
    except Exception as e:  # noqa: BLE001
        return False, f"import 失败 {type(e).__name__}: {str(e)[:120]}"

    try:
        rng = np.random.default_rng(42)
        px = pd.DataFrame(
            100 * np.cumprod(1 + rng.normal(0, 0.01, (500, 2)), axis=0),
            columns=["a", "b"], index=pd.bdate_range("2024-01-01", periods=500),
        )
        mom = px / px.shift(252) - 1          # 12M 动量(滚动批量)
        pf = vbt.Portfolio.from_signals(      # 简单信号组合
            close=px["a"], entries=mom["a"] > 0.02, exits=mom["a"] < 0,
            init_cash=100_000,
        )
        nav = pf.value()
        ok = nav.notna().all() and (nav.iloc[-1] > 0)
        return ok, f"vbt {vbt.__version__}: from_signals+rolling 动量 OK,末端净值 {nav.iloc[-1]:,.0f}"
    except Exception as e:  # noqa: BLE001
        return False, f"运行失败 {type(e).__name__}: {str(e)[:120]}"


def probe_bt() -> tuple[bool, str]:
    """官方 quickstart 风格:月度再平衡,与手算逐日净值对照。"""
    try:
        import bt
    except Exception as e:  # noqa: BLE001
        return False, f"import 失败 {type(e).__name__}: {str(e)[:120]}"

    try:
        rng = np.random.default_rng(7)
        idx = pd.bdate_range("2024-01-01", periods=500)
        px = pd.DataFrame(
            100 * np.cumprod(1 + rng.normal(0, 0.008, (500, 2)), axis=0),
            columns=["a", "b"], index=idx,
        )
        # 权重表:每月首个交易日 100% a(固定目标,验证 WeighTarget 语义)
        monthly_first = pd.Series(idx, index=idx).groupby(idx.to_period("M")).min()
        weights = pd.DataFrame({"a": 1.0}, index=pd.DatetimeIndex(monthly_first.values))
        s = bt.Strategy("probe", [
            bt.algos.RunMonthly(),
            bt.algos.WeighTarget(weights),
            bt.algos.Rebalance(),
        ])
        res = bt.run(bt.Backtest(s, px), progress_bar=False)  # 模块级 run 才返回 Result
        nav_bt = res.prices["probe"] if hasattr(res.prices, "columns") else res.prices
        # 手算:等价于全程持有 a(目标从未变过);bt 净值以 100 为基数,两侧归一到首日=1 再比
        nav_hand = px["a"] / px["a"].iloc[0]
        nav_bt_n = nav_bt / nav_bt.iloc[0]
        diff = (nav_bt_n / nav_hand - 1).abs().max()
        # 阈值 1e-4:bt 在索引前自动加一天前置行、内部份额按整数取整,
        # 与连续手算存在 ~1e-5 量级的复利舍入差,属正常口径差而非错误
        ok = diff < 1e-4
        return ok, f"bt {bt.__version__}: 月度 WeighTarget 与手算净值 max|Δ|={diff:.2e}"
    except Exception as e:  # noqa: BLE001
        return False, f"运行失败 {type(e).__name__}: {str(e)[:120]}"


def probe_quantstats() -> tuple[bool, str]:
    """501 天随机收益 → html 报告写临时路径并读回。"""
    try:
        import quantstats as qs
    except Exception as e:  # noqa: BLE001
        return False, f"import 失败 {type(e).__name__}: {str(e)[:120]}"

    try:
        rng = np.random.default_rng(3)
        ret = pd.Series(rng.normal(0.0004, 0.01, 501),
                        index=pd.bdate_range("2024-01-01", periods=501))
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "probe.html"
            qs.reports.html(ret, output=str(out), title="probe")
            ok = out.exists() and out.stat().st_size > 10_000
            size_kb = out.stat().st_size // 1024 if out.exists() else 0
        cagr = qs.stats.cagr(ret)
        return ok, f"quantstats {qs.__version__}: html 报告生成 OK({size_kb}KB),cagr={cagr:.3f}"
    except Exception as e:  # noqa: BLE001
        return False, f"运行失败 {type(e).__name__}: {str(e)[:120]}"


def main() -> int:
    print(f"环境:pandas {pd.__version__} / numpy {np.__version__}")
    results = {}
    for name, fn in [("vectorbt", probe_vectorbt), ("bt", probe_bt),
                     ("quantstats", probe_quantstats)]:
        try:
            ok, msg = fn()
        except Exception as e:  # noqa: BLE001
            ok, msg = False, f"探针自身异常 {type(e).__name__}: {str(e)[:120]}"
        results[name] = ok
        print(f"  [{'✅' if ok else '❌'}] {name}: {msg}")
    n_ok = sum(results.values())
    print(f"\n结论:{n_ok}/3 可用" + ("" if n_ok == 3 else f",不可用:{[k for k, v in results.items() if not v]}"))
    return 0 if n_ok == 3 else 1


if __name__ == "__main__":
    sys.exit(main())
