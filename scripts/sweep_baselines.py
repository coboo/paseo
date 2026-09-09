"""三基线敏感性扫描(第 3 步验证:参数高原 vs 孤峰)。

Faber:SMA ∈ {6,8,10,12,15} 月;
FED:阈值对 ∈ {0.6/0.4 … 0.8/0.2} × 分位窗口 ∈ {expanding, 滚动60M}
    ——expanding 在 ERP 结构性抬升下退化为永续持股(第一轮换仓 0 次),
    滚动窗口作对照维度是敏感性分析的自然扩展(非改策略定义);
GTAA:TopN ∈ {1,2,3} × 回望 ∈ {6,12} 月。
统一共同区间 2009-02 起。用法:uv run python scripts/sweep_baselines.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from strategy.baseline_signals import (            # noqa: E402
    FABER_ASSETS, GTAA_ASSETS, faber_signals, gtaa_signals,
)
from strategy.contract import StrategyConfig       # noqa: E402
from strategy.engine_weights import run_monthly_weights  # noqa: E402
from strategy.panels import build_signal_panel     # noqa: E402
from strategy.run_baselines import _benchmark, run_fed  # noqa: E402
from data_module.storage import read_raw, save_derived  # noqa: E402

COMMON = pd.Timestamp("2009-02-01")


def _metrics(prices, weights, label):
    res = run_monthly_weights(label, "index", prices, weights, StrategyConfig())
    nav = res.nav[res.nav.index >= COMMON]
    ret = res.ret[res.ret.index >= COMMON]
    if len(nav) < 252:
        return None
    yrs = len(nav) / 252.0
    cagr = float(nav.iloc[-1] ** (1 / yrs) - 1)
    mdd = float((nav / nav.cummax() - 1).min())
    bh_cagr, bh_mdd = _benchmark(nav.index)
    return {"cagr": cagr, "mdd": mdd, "dd_cut": 1 - abs(mdd) / abs(bh_mdd),
            "sharpe": float(ret.mean() / ret.std() * 252 ** 0.5) if ret.std() > 0 else float("nan"),
            "pass": bool(1 - abs(mdd) / abs(bh_mdd) >= 0.4 and cagr >= 0.7 * bh_cagr)}


def sweep_faber(panel):
    rows = []
    for sma in [6, 8, 10, 12, 15]:
        m = _metrics(panel, faber_signals(sma)[1], f"faber{sma}")
        if m:
            rows.append({"strategy": "faber", "param": f"SMA={sma}M", **m})
    return rows


def sweep_fed(panel):
    rows = []
    for hi, lo in [(0.6, 0.4), (0.65, 0.35), (0.7, 0.3), (0.75, 0.25), (0.8, 0.2)]:
        m = _metrics(panel, __import__("strategy.baseline_signals", fromlist=["fed_signals"])
                     .fed_signals(hi, lo)[1], f"fed{hi}")
        if m:
            rows.append({"strategy": "fed", "param": f"exp {hi}/{lo}", **m})
    # 滚动 60M 分位对照(内联实现,与 fed_signals 同规则仅分位窗口不同)
    from metrics.erp import erp_daily
    erp = erp_daily().set_index("date")["erp"].sort_index().resample("ME").last().dropna()
    cal = read_raw("calendar.parquet")["date"]
    anchors = pd.DatetimeIndex(sorted(cal.groupby(cal.dt.to_period("M")).max().values))
    for hi, lo in [(0.6, 0.4), (0.7, 0.3), (0.8, 0.2)]:
        state, ws = None, []
        for a in anchors:
            hist = erp[(erp.index <= a)].tail(60)
            if len(hist) < 36:
                continue
            pct = float((hist.iloc[-1] >= hist).mean())
            if pct >= hi:
                state = "hs300"
            elif pct <= lo:
                state = "bond"
            if state:
                nxt = cal[cal > a]
                if len(nxt):
                    ws.append((pd.Timestamp(nxt.iloc[0]),
                               {"hs300": 1.0 if state == "hs300" else 0.0,
                                "bond": 1.0 if state == "bond" else 0.0, "cash": 0.0}))
        weights = pd.DataFrame([w for _, w in ws], index=pd.DatetimeIndex([d for d, _ in ws]))
        m = _metrics(panel, weights, f"fed_roll{hi}")
        if m:
            rows.append({"strategy": "fed", "param": f"roll60 {hi}/{lo}", **m})
    return rows


def sweep_gtaa(panel):
    rows = []
    for top_n in [1, 2, 3]:
        for lb in [6, 12]:
            m = _metrics(panel, gtaa_signals(lb, top_n)[1], f"gtaa{top_n}_{lb}")
            if m:
                rows.append({"strategy": "gtaa", "param": f"Top{top_n}×{lb}M", **m})
    return rows


def main() -> int:
    panel_f = build_signal_panel(FABER_ASSETS)
    panel_g = build_signal_panel(GTAA_ASSETS)
    panel_fd = build_signal_panel(["hs300", "bond"])
    rows = sweep_faber(panel_f) + sweep_fed(panel_fd) + sweep_gtaa(panel_g)
    df = pd.DataFrame(rows)
    print(df.to_string(index=False, formatters={"cagr": "{:.2%}".format,
                                                "mdd": "{:.1%}".format,
                                                "dd_cut": "{:.0%}".format,
                                                "sharpe": "{:.2f}".format}))
    for strat, grp in df.groupby("strategy"):
        n_pass = int(grp["pass"].sum())
        print(f"\n[{strat}] {n_pass}/{len(grp)} 达标:"
              + (", ".join(grp.loc[grp['pass'], 'param']) if n_pass else " 无"))
    save_derived(df, "backtests/baselines_sweep.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
