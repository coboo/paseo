"""红利低波簇打分轮动 walk-forward + holdout 终验（设计文档十三节，复刻 Faber 流程）。

协议（第八节 3）：
- WF：训练窗 5 年（滚动）/ 测试 1 年，首段测试 2020 起；网格 enter{30,40,50} ×
  exit{50,60,70} × hyst{0,2}pp 全交叉 18 组，按 Calmar（训练窗年化/|MDD|）机械选参
  → 样本外拼接；WF 止于 holdout 起点 2025-09-15。
- holdout：冻结规则 = 末段 WF 选参，2025-09-15 → 2026-09-14 只跑一次。
- 通过线（第八节 4，均值回归类）：样本外夏普 > 1 且 MDD 显著浅于簇等权 B&H
  （"显著"机械口径 = 回撤削减 ≥ 40%，事前定死）；另报对沪深300 全收益对比。
- 诚实声明：打分权重 2024+ 曾被研究阶段 OOS 见过（弱污染，设计文档十三节）；
  且 score_pct 为全样本 rank（非 expanding 当时视角，见 PROGRESS 记录）——
  主检验用冻结序列（纪律：一个参数不改），另跑 PIT（当时视角）分位作敏感性对照。

用法：PYTHONPATH=src uv run --no-sync python -m dividend.walkforward
"""
from __future__ import annotations

import argparse
import sys
from itertools import product

import pandas as pd

from data_module.storage import save_derived

from . import factors, score
from .backtest import (benchmark_stats, build_execution_panel, build_signal_panel,
                       cluster_equal_bh, hs300_tr, month_end_anchors,
                       run_dividend_backtest)
from .cards import compute_cards
from .strategy import CODES, DEFAULT_WEIGHTS, compute_target_weights

GRID_ENTER = (30.0, 40.0, 50.0)
GRID_EXIT = (50.0, 60.0, 70.0)
GRID_HYST = (0.0, 2.0)
GRID = [(e, x, h) for e, x, h in product(GRID_ENTER, GRID_EXIT, GRID_HYST)]  # 18 组全交叉

TRAIN_YEARS = 5
FIRST_TEST = pd.Timestamp("2020-01-01")
HOLDOUT_START = pd.Timestamp("2025-09-15")   # 最后一年 untouched（设计文档十三节）
HOLDOUT_END = pd.Timestamp("2026-09-14")
COST_BPS = 5.0
STRESS_WINDOWS = [("2024-01-01", "2024-02-29")]  # OOS 内压力期（2015/2018 在 OOS 窗之前）


def load_pct_series() -> dict[str, pd.Series]:
    """冻结口径打分分位序列（compute_cards("valuation").series，0-100，一个参数不改）。"""
    cards = compute_cards("valuation")
    return {code: cards[code].series for code in CODES}


def pit_pct_series() -> dict[str, pd.Series]:
    """敏感性对照：当时视角（PIT）分位——score_z 截至前一日的 expanding 历史分位。

    非冻结口径，仅用于量化 score_pct 全样本 rank 前视的影响，不进通过线判读。
    """
    panels = factors.build_panels()
    scores, _ = score.score_valuation_only(panels)
    out = {}
    for code in CODES:
        sc = scores[code]["score_z"]
        pit = sc.shift(1).expanding(min_periods=252).apply(
            lambda x: (x[:-1] <= x[-1]).mean(), raw=True)
        out[code] = (pit * 100).dropna()
    return out


def grid_weights(pct: dict[str, pd.Series],
                 anchors: pd.DatetimeIndex) -> dict[tuple[float, float, float], pd.DataFrame]:
    """网格内各参数组的全历史目标权重（每档只算一次，选参与样本外复用）。"""
    return {(e, x, h): compute_target_weights(pct, enter=e, exit=x, hyst=h,
                                              weights=DEFAULT_WEIGHTS, anchors=anchors)
            for e, x, h in GRID}


def _segment_calmar(w_train: pd.DataFrame, panel: pd.DataFrame) -> float:
    """训练窗选参标准：Calmar = 年化/|MDD|（含 5bps 成本）。

    无风险证据（|MDD| < 1e-4，即训练窗几乎全现金）返回 -inf，不参与选参；
    有效数据不足 126 日同样 -inf。
    """
    if len(w_train) == 0:
        return float("-inf")
    res = run_dividend_backtest("seg", "index", panel, w_train, cost_bps=COST_BPS)
    nav = res.nav
    if len(nav) < 126:
        return float("-inf")
    mdd = float((nav / nav.cummax() - 1).min())
    if mdd > -1e-4:
        return float("-inf")
    yrs = len(nav) / 252.0
    cagr = float(nav.iloc[-1] ** (1 / yrs) - 1)
    return cagr / abs(mdd)


def walk_forward(pct: dict[str, pd.Series],
                 panel: pd.DataFrame,
                 weights_by_params: dict[tuple[float, float, float], pd.DataFrame]
                 | None = None,
                 ) -> tuple[pd.DataFrame, pd.DataFrame, tuple[float, float, float]]:
    """滚动选参 → 样本外拼接。返回 (逐段选参表, 样本外权重表, 冻结参数=末段选参)。"""
    data_end = min(panel.index.max(), min(s.index.max() for s in pct.values()))
    anchors = month_end_anchors(data_end)
    if weights_by_params is None:
        weights_by_params = grid_weights(pct, anchors)

    segs = []
    cur = FIRST_TEST
    while cur < HOLDOUT_START:
        oos_end = min(cur + pd.DateOffset(months=12), HOLDOUT_START)
        train_start = cur - pd.DateOffset(years=TRAIN_YEARS)
        # 选参只用训练窗（w.index > train_start & <= cur），无未来函数
        best, best_calmar = None, float("-inf")
        for g in GRID:
            w = weights_by_params[g]
            calmar = _segment_calmar(w[(w.index > train_start) & (w.index <= cur)], panel)
            if calmar > best_calmar:
                best, best_calmar = g, calmar
        w_oos = weights_by_params[best][(weights_by_params[best].index > cur)
                                        & (weights_by_params[best].index <= oos_end)]
        segs.append({"oos_start": cur, "oos_end": oos_end,
                     "enter": best[0], "exit": best[1], "hyst": best[2],
                     "train_calmar": best_calmar, "weights": w_oos})
        cur = oos_end

    detail = pd.DataFrame([{k: v for k, v in s.items() if k != "weights"} for s in segs])
    weights_oos = pd.concat([s["weights"] for s in segs])
    weights_oos = weights_oos[~weights_oos.index.duplicated(keep="first")].sort_index()
    frozen = (segs[-1]["enter"], segs[-1]["exit"], segs[-1]["hyst"])
    return detail, weights_oos, frozen


def _stress_mdd(nav: pd.Series, start: str, end: str) -> float:
    """压力子窗内最大回撤（子窗起点重置高点）。"""
    seg = nav[(nav.index >= start) & (nav.index <= end)]
    if len(seg) < 2:
        return float("nan")
    return float((seg / seg.cummax() - 1).min())


def _fmt_pct(x: float) -> str:
    return f"{x:+.2%}" if pd.notna(x) else "  — "


def run_report(tag: str, res, panel: pd.DataFrame) -> dict:
    """打印某次回测的判读表（对簇等权 B&H 与沪深300 全收益），返回指标 dict。"""
    s = res.summary
    idx = res.nav.index
    bh = cluster_equal_bh(panel, idx.min(), idx.max())
    bh_s = benchmark_stats(bh)
    hs = hs300_tr()
    hs_seg = hs[(hs.index >= idx.min()) & (hs.index <= idx.max())]
    hs_nav = hs_seg / hs_seg.iloc[0]
    hs_s = benchmark_stats(hs_nav)
    dd_cut = 1 - abs(s["mdd"]) / abs(bh_s["mdd"]) if bh_s["mdd"] < 0 else float("nan")

    print(f"\n── {tag}（{idx.min():%Y-%m-%d} → {idx.max():%Y-%m-%d}，{len(idx)} 日）──")
    print(f"  策略 : 年化 {_fmt_pct(s['cagr'])}  MDD {_fmt_pct(s['mdd'])}  "
          f"夏普 {s['sharpe']:.2f}  年化换手 {s['turnover_annual']:.2f}x  "
          f"平均簇仓位 {s['gross_avg']:.1%}")
    print(f"  簇B&H: 年化 {_fmt_pct(bh_s['cagr'])}  MDD {_fmt_pct(bh_s['mdd'])}  "
          f"夏普 {bh_s['sharpe']:.2f}")
    print(f"  沪深300: 年化 {_fmt_pct(hs_s['cagr'])}  MDD {_fmt_pct(hs_s['mdd'])}  "
          f"夏普 {hs_s['sharpe']:.2f}")
    print(f"  回撤削减(vs 簇B&H) {dd_cut:.0%}")
    for st, en in STRESS_WINDOWS:
        if idx.min() <= pd.Timestamp(st):
            print(f"  压力期 {st}~{en}: 策略 MDD {_fmt_pct(_stress_mdd(res.nav, st, en))}"
                  f" vs 簇B&H {_fmt_pct(_stress_mdd(bh, st, en))}")
    return {"cagr": s["cagr"], "mdd": s["mdd"], "sharpe": s["sharpe"],
            "turnover_annual": s["turnover_annual"], "gross_avg": s["gross_avg"],
            "bh_cagr": bh_s["cagr"], "bh_mdd": bh_s["mdd"], "bh_sharpe": bh_s["sharpe"],
            "hs_cagr": hs_s["cagr"], "hs_mdd": hs_s["mdd"], "hs_sharpe": hs_s["sharpe"],
            "dd_cut": dd_cut}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="红利低波簇打分轮动 walk-forward + holdout 终验")
    parser.parse_args(argv)

    pct = load_pct_series()
    panel = build_signal_panel()
    print("=== 数据覆盖（如实报告）===")
    for code in CODES:
        s = pct[code]
        print(f"  {code}: 分位 {s.index.min():%Y-%m-%d} → {s.index.max():%Y-%m-%d}"
              f"（{len(s)} 日）")
    print(f"  信号层面板: {panel.index.min():%Y-%m-%d} → {panel.index.max():%Y-%m-%d}")

    weights_by_params = grid_weights(pct, month_end_anchors(
        min(panel.index.max(), min(s.index.max() for s in pct.values()))))

    print(f"\n=== walk-forward（训练 {TRAIN_YEARS} 年滚动 / 测试 1 年，"
          f"网格 {len(GRID)} 组，Calmar 机械选参）===")
    detail, weights_oos, frozen = walk_forward(pct, panel, weights_by_params)
    print(detail.to_string(index=False))
    print(f"冻结规则（末段选参）: enter={frozen[0]:.0f} exit={frozen[1]:.0f} hyst={frozen[2]:.0f}pp")

    res_wf = run_dividend_backtest("dividend WF 样本外", "index",
                                   panel[(panel.index >= FIRST_TEST)
                                         & (panel.index <= HOLDOUT_START)],
                                   weights_oos, cost_bps=COST_BPS)
    wf = run_report("WF 样本外拼接", res_wf, panel)
    wf_pass = bool(wf["sharpe"] > 1 and wf["dd_cut"] >= 0.4)
    print(f"  → 通过线（样本外夏普>1 且回撤削减≥40%）: {'✅' if wf_pass else '❌'}")

    print(f"\n=== holdout 终验（{HOLDOUT_START:%Y-%m-%d} → {HOLDOUT_END:%Y-%m-%d}，"
          f"untouched，只看一次）===")
    w_ho = weights_by_params[frozen][(weights_by_params[frozen].index > HOLDOUT_START)
                                     & (weights_by_params[frozen].index <= HOLDOUT_END)]
    res_ho = run_dividend_backtest("dividend holdout", "index",
                                   panel[(panel.index >= HOLDOUT_START)
                                         & (panel.index <= HOLDOUT_END)],
                                   w_ho, cost_bps=COST_BPS)
    ho = run_report("holdout", res_ho, panel)
    ho_pass = bool(ho["sharpe"] > 1 and ho["dd_cut"] >= 0.4)
    print(f"  → 通过线（夏普>1 且回撤削减≥40%）: {'✅' if ho_pass else '❌'}")

    print("\n=== 执行层复测（ETF 前复权，义务性验证；159545 溢价门控不回测，"
          "已知保守偏差）===")
    ep = build_execution_panel()
    print(f"  共同区间实际起点: {ep.index.min():%Y-%m-%d}（数据交集，如实报告）")
    e_anchors = month_end_anchors(min(ep.index.max(), min(s.index.max() for s in pct.values())))
    w_etf = compute_target_weights(pct, enter=frozen[0], exit=frozen[1], hyst=frozen[2],
                                   anchors=e_anchors)
    res_etf = run_dividend_backtest("dividend ETF", "etf", ep, w_etf, cost_bps=COST_BPS)
    etf = run_report("执行层 ETF", res_etf, ep)

    print("\n=== 敏感性对照：当时视角（PIT）分位替换 score_pct 全样本 rank（非冻结口径）===")
    pct_pit = pit_pct_series()
    detail_pit, weights_oos_pit, frozen_pit = walk_forward(pct_pit, panel)
    res_pit = run_dividend_backtest("dividend WF PIT", "index",
                                   panel[(panel.index >= FIRST_TEST)
                                         & (panel.index <= HOLDOUT_START)],
                                   weights_oos_pit, cost_bps=COST_BPS)
    pit = run_report("WF 样本外（PIT 口径）", res_pit, panel)
    print(f"  PIT 口径逐段选参: {[(int(r.enter), int(r.exit), int(r.hyst)) for r in detail_pit.itertuples()]}")

    # ── 落盘（derived 全量重算覆盖）──
    save_derived(detail.assign(frozen_enter=frozen[0], frozen_exit=frozen[1],
                               frozen_hyst=frozen[2]),
                 "backtests/dividend_wf_detail.parquet")
    df_wf = pd.DataFrame({"date": res_wf.nav.index, "nav": res_wf.nav.values,
                          "ret": res_wf.ret.values, "drawdown": res_wf.drawdown.values,
                          "position": res_wf.position.values,
                          "gross": weights_oos.reindex(res_wf.nav.index).ffill()
                                                          .sum(axis=1).values})
    save_derived(df_wf, "backtests/dividend_wf.parquet")
    df_ho = pd.DataFrame({"date": res_ho.nav.index, "nav": res_ho.nav.values,
                          "ret": res_ho.ret.values, "drawdown": res_ho.drawdown.values,
                          "position": res_ho.position.values})
    save_derived(df_ho, "backtests/dividend_holdout.parquet")
    df_etf = pd.DataFrame({"date": res_etf.nav.index, "nav": res_etf.nav.values,
                           "ret": res_etf.ret.values, "drawdown": res_etf.drawdown.values,
                           "position": res_etf.position.values})
    save_derived(df_etf, "backtests/dividend_etf.parquet")

    print("\n最终判读（通过线：样本外夏普>1 且回撤削减≥40%）：")
    print(f"  WF 样本外 : {'✅' if wf_pass else '❌'}  夏普 {wf['sharpe']:.2f}  削减 {wf['dd_cut']:.0%}")
    print(f"  holdout   : {'✅' if ho_pass else '❌'}  夏普 {ho['sharpe']:.2f}  削减 {ho['dd_cut']:.0%}")
    print("  （处置按设计文档十三节：全过 → 升级实盘候选；否则保持信号观察，死因如实上页）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
