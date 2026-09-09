"""三基线(Faber / FED 分位 / GTAA)信号层回测编排(设计文档第十一节)。

第一轮仅信号层(干净价格),通过线达标者再换 ETF qfq 复测执行层。
CLI:PYTHONPATH=src uv run python -m strategy.baselines [faber|fed|gtaa|all]
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from data_module.storage import DERIVED_DIR, read_raw, save_derived

from .baseline_signals import FABER_ASSETS, GTAA_ASSETS, faber_signals, fed_signals, gtaa_signals
from .contract import BacktestResult, StrategyConfig
from .engine_weights import run_monthly_weights
from .panels import build_signal_panel


def _panel_for(keys: list[str]) -> pd.DataFrame:
    return build_signal_panel(keys, with_cash=True)


def run_faber(cfg: StrategyConfig = StrategyConfig()):
    sig, weights = faber_signals()
    panel = _panel_for(FABER_ASSETS)
    res = run_monthly_weights("Faber 10月均线·信号层", "index", panel, weights, cfg)
    save_derived(sig, "signals/faber_monthly.parquet")
    return res


def run_fed(cfg: StrategyConfig = StrategyConfig()):
    sig, weights = fed_signals()
    panel = _panel_for(["hs300", "bond"])
    res = run_monthly_weights("FED 分位·信号层", "index", panel, weights, cfg)
    save_derived(sig, "signals/fed_monthly.parquet")
    return res


def run_gtaa(cfg: StrategyConfig = StrategyConfig()):
    sig, weights = gtaa_signals()
    panel = _panel_for(GTAA_ASSETS)
    res = run_monthly_weights("GTAA 动量轮动·信号层", "index", panel, weights, cfg)
    save_derived(sig, "signals/gtaa_monthly.parquet")
    return res


def run_all(cfg: StrategyConfig = StrategyConfig()) -> dict[str, object]:
    out = {"faber": run_faber(cfg), "fed": run_fed(cfg), "gtaa": run_gtaa(cfg)}
    for tag, res in out.items():
        df = pd.DataFrame({
            "date": res.nav.index, "nav": res.nav.values, "ret": res.ret.values,
            "position": res.position.values, "drawdown": res.drawdown.values,
        })
        save_derived(df, f"backtests/{tag}_index.parquet")
    return out


# Faber 执行层资产映射(信号-执行分离:信号用指数,执行用 ETF qfq 开盘价)
FABER_ETF_MAP = {"hs300": "510310", "spx": "513500", "bond": "511260", "gold": "518880"}


def run_faber_etf(cfg: StrategyConfig = StrategyConfig()) -> BacktestResult:
    """Faber 执行层复测(通过线达标者的义务,第八节第 5 条)。

    信号层权重表不变;价格载体换 ETF qfq 开盘(511260 沿用拼接腿序列);
    QDII 溢价门控:执行日 513500 溢价代理 >cap → 其权重转 cash(只挡买入)。
    """
    from .qdii_filter import premium_proxy

    _, weights = faber_signals()
    idx = weights.index[weights.index >= "2014-02-01"]  # 受 513500 上市约束
    weights = weights.loc[idx]

    cols = {code: read_raw(f"etf_daily/etf_qfq_{code}.parquet").set_index("date")["open"].rename(code)
            for code in ["510310", "513500", "518880"]}
    bond = pd.read_parquet(
        DERIVED_DIR / "aligned" / "bond_leg_spliced_511260.parquet").set_index("date")["close"]
    frame = cols["510310"].to_frame()
    for c in ["513500", "518880"]:
        frame[c] = cols[c].reindex(frame.index).ffill(limit=5)
    frame["511260"] = bond.reindex(frame.index).ffill(limit=5)
    from .panels import cash_price
    frame["cash"] = cash_price().reindex(frame.index).ffill(limit=10)
    panel = frame.dropna()

    prem = premium_proxy()
    gated = weights.copy()
    blocked = []
    for d in gated.index:
        p = float(prem.asof(d)) if len(prem[prem.index <= d]) else float("nan")
        w_qdii = gated.at[d, "spx"]
        if w_qdii > 0 and not pd.isna(p) and p > cfg.premium_cap:
            # 溢价超限:该资产权重转 cash(只挡买入;权重来自指数信号,门控仅执行层)
            gated.at[d, "cash"] += w_qdii
            gated.at[d, "spx"] = 0.0
            blocked.append((d, p))
    gated = gated.rename(columns=FABER_ETF_MAP)[list(panel.columns)]

    res = run_monthly_weights("Faber 10月均线·执行层(ETF)", "etf", panel, gated, cfg)
    res.summary["blocked_months"] = len(blocked)
    df = pd.DataFrame({
        "date": res.nav.index, "nav": res.nav.values, "ret": res.ret.values,
        "position": res.position.values, "drawdown": res.drawdown.values,
    })
    save_derived(df, "backtests/faber_etf.parquet")
    return res


def _benchmark(idx: pd.DatetimeIndex) -> tuple[float, float]:
    hs = read_raw("index_daily/index_000300.parquet").set_index("date")["close"]
    hs = hs[hs.index >= idx.min()]
    return (float((hs.iloc[-1] / hs.iloc[0]) ** (252 / len(hs)) - 1),
            float((hs / hs.cummax() - 1).min()))


def verdict_table(results: dict) -> pd.DataFrame:
    """各策略全区间 + 共同区间(2009-02 起)指标与通过线判读。"""
    common = pd.Timestamp("2009-02-01")
    rows = []
    for tag, r in results.items():
        for scope, nav, ret in [("全区间", r.nav, r.ret),
                                ("共同区间", r.nav[r.nav.index >= common], r.ret[r.ret.index >= common])]:
            if len(nav) < 252:
                continue
            yrs = len(nav) / 252.0
            cagr = float(nav.iloc[-1] ** (1 / yrs) - 1)
            mdd = float((nav / nav.cummax() - 1).min())
            bh_cagr, bh_mdd = _benchmark(nav.index)
            dd_cut = 1 - abs(mdd) / abs(bh_mdd)
            rows.append({
                "策略": r.name.replace("·信号层", ""), "区间": scope,
                "起": f"{nav.index.min():%Y-%m}", "止": f"{nav.index.max():%Y-%m}",
                "年化": cagr, "最大回撤": mdd,
                "夏普": float(ret.mean() / ret.std() * 252 ** 0.5) if ret.std() > 0 else float("nan"),
                "回撤削减": dd_cut, "年化/基准": cagr / bh_cagr,
                "通过线": bool(dd_cut >= 0.4 and cagr >= 0.7 * bh_cagr),
            })
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="三基线信号层回测(Faber/FED/GTAA)")
    parser.add_argument("which", nargs="*", choices=["faber", "fed", "gtaa", "all"])
    args = parser.parse_args(argv)
    which = list(args.which) if args.which else ["all"]
    which = ["faber", "fed", "gtaa"] if "all" in which else which

    runners = {"faber": run_faber, "fed": run_fed, "gtaa": run_gtaa}
    cfg = StrategyConfig()
    results = {}
    for w in which:
        print(f"\n>>> {w}")
        results[w] = runners[w](cfg)
        s = results[w].summary
        print(f"    区间 {results[w].nav.index.min():%Y-%m-%d} → {results[w].nav.index.max():%Y-%m-%d}"
              f"  年化 {s['cagr']:+.2%}  MDD {s['mdd']:.1%}  夏普 {s['sharpe']:.2f}  换仓 {s['switch_count']}")

    if len(results) >= 2:
        print("\n=== 判读表 ===")
        print(verdict_table(results).to_string(index=False,
              formatters={"年化": "{:.2%}".format, "最大回撤": "{:.1%}".format,
                          "回撤削减": "{:.0%}".format, "年化/基准": "{:.1f}".format, "夏普": "{:.2f}".format}))
    save_derived(verdict_table(results), "backtests/baselines_verdict.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
