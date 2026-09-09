"""Faber walk-forward 滚动校准 + 最后一年 holdout 一次性终验(设计文档第八节 3)。

walk-forward:8 年训练窗在 SMA 网格内按 Calmar 选参 → 次年样本外用该参数,滚动推进;
全部样本外段拼接成 WF 净值。判读(事前定死,防事后合理化):
  ① WF 样本外拼接 vs 同区间沪深300 买入持有:回撤砍 40%+ 且年化 ≥70%(主通过线同构);
  ② WF vs 固定 10M(信息性,检验对参数选择的依赖)。
holdout:最后一年(2025-08-15 → 2026-08-14)untouched,只看一次:
  ① 年化 ≥ 基准 70% ② MDD 严格小于基准 ③ 无异常换手(<15 次)。

用法:PYTHONPATH=src uv run python -m strategy.walkforward
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from data_module.storage import save_derived

from .baseline_signals import FABER_ASSETS, faber_signals
from .contract import StrategyConfig
from .engine_weights import run_monthly_weights
from .panels import build_signal_panel
from .run_baselines import _benchmark

GRID = [6, 8, 10, 12, 15]
TRAIN_YEARS = 8
STEP_MONTHS = 12
HOLDOUT_START = "2025-08-15"   # 最后一年 untouched(数据止 2026-08-14)


def _signals_cache() -> dict[int, pd.DataFrame]:
    """网格内各 SMA 的信号权重表(一次算好复用)。"""
    return {sma: faber_signals(sma)[1] for sma in GRID}


def _segment_metrics(weights: pd.DataFrame, panel: pd.DataFrame,
                     start, end) -> tuple[float, float]:
    """一段区间的 (Calmar, )——训练窗选参标准;返回 (calmar, mdd)。"""
    w = weights[(weights.index > start) & (weights.index <= end)]
    res = run_monthly_weights("seg", "index", panel, w, StrategyConfig())
    nav = res.nav
    if len(nav) < 126:
        return float("-inf"), float("nan")
    yrs = len(nav) / 252.0
    cagr = float(nav.iloc[-1] ** (1 / yrs) - 1)
    mdd = float((nav / nav.cummax() - 1).min())
    return (cagr / abs(mdd) if mdd < 0 else float("inf")), mdd


def walk_forward_faber(train_years: int = TRAIN_YEARS,
                       step_months: int = STEP_MONTHS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """滚动选参 → 样本外拼接。返回 (WF 明细含每段选参, 拼接权重表)。"""
    panel = build_signal_panel(FABER_ASSETS)
    cache = _signals_cache()

    anchors = sorted(cache[GRID[0]].index)
    start = anchors[0]
    segs = []
    cur = pd.Timestamp(start) + pd.DateOffset(years=train_years)
    while cur + pd.DateOffset(months=step_months) <= anchors[-1]:
        oos_end = cur + pd.DateOffset(months=step_months)
        # 训练窗:全部历史 ≤ cur(锚点即执行日,选参只用 ≤cur 的执行段,无未来函数)
        best, best_calmar = GRID[0], float("-inf")
        for sma in GRID:
            calmar, _ = _segment_metrics(cache[sma], panel, start, cur)
            if calmar > best_calmar:
                best, best_calmar = sma, calmar
        w = cache[best]
        w = w[(w.index > cur) & (w.index <= oos_end)]
        segs.append({"oos_start": cur, "oos_end": oos_end, "picked_sma": best,
                     "train_calmar": best_calmar, "weights": w})
        cur = oos_end

    detail = pd.DataFrame([{k: v for k, v in s.items() if k != "weights"} for s in segs])
    weights_oos = pd.concat([s["weights"] for s in segs])
    weights_oos = weights_oos[~weights_oos.index.duplicated(keep="first")].sort_index()
    return detail, weights_oos


def holdout_faber(weights_10m: pd.DataFrame, panel: pd.DataFrame) -> dict:
    """最后一年 untouched 终验(只做一次)。"""
    hs = panel["hs300"]
    w = weights_10m[(weights_10m.index > HOLDOUT_START)]
    res = run_monthly_weights("holdout", "index", panel.loc[panel.index >= HOLDOUT_START],
                              w, StrategyConfig())
    nav, ret = res.nav, res.ret
    yrs = len(nav) / 252.0
    cagr = float(nav.iloc[-1] ** (1 / yrs) - 1)
    mdd = float((nav / nav.cummax() - 1).min())
    hs_seg = hs[hs.index >= HOLDOUT_START]
    bh_cagr = float((hs_seg.iloc[-1] / hs_seg.iloc[0]) ** (252 / len(hs_seg)) - 1)
    bh_mdd = float((hs_seg / hs_seg.cummax() - 1).min())
    switches = int(res.summary["switch_count"])
    return {
        "holdout 年化": cagr, "基准年化": bh_cagr,
        "holdout MDD": mdd, "基准 MDD": bh_mdd,
        "换手次数": switches,
        "判①收益≥基准70%": cagr >= 0.7 * bh_cagr,
        "判②回撤绝对值严格小于基准": abs(mdd) < abs(bh_mdd),   # 回撤为负数,比绝对值(浅)
        "判③无异常换手(<15)": switches < 15,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Faber walk-forward + holdout 终验")
    parser.parse_args(argv)

    panel = build_signal_panel(FABER_ASSETS)
    detail, weights_oos = walk_forward_faber()
    print("=== walk-forward 滚动选参(8 年训练,1 年步进)===")
    print(detail.to_string(index=False))

    res = run_monthly_weights("Faber WF 样本外", "index", panel, weights_oos, StrategyConfig())
    nav = res.nav
    cagr = res.summary["cagr"]
    mdd = res.summary["mdd"]
    bh_cagr, bh_mdd = _benchmark(nav.index)
    dd_cut = 1 - abs(mdd) / abs(bh_mdd)
    wf_pass = bool(dd_cut >= 0.4 and cagr >= 0.7 * bh_cagr)
    print(f"\nWF 样本外({nav.index.min():%Y-%m} → {nav.index.max():%Y-%m}):"
          f"年化 {cagr:+.2%}  MDD {mdd:.1%}  回撤削减 {dd_cut:.0%}  → "
          f"主通过线 {'✅' if wf_pass else '❌'}")

    # 对照:固定 10M 在同区间
    w10 = faber_signals(10)[1]
    w10 = w10[(w10.index >= nav.index.min())]
    fixed = run_monthly_weights("Faber 固定10M", "index", panel, w10, StrategyConfig())
    print(f"固定 10M 同区间:年化 {fixed.summary['cagr']:+.2%}  MDD {fixed.summary['mdd']:.1%}"
          f"(WF − 固定 = {cagr - fixed.summary['cagr']:+.2%},检验参数选择依赖)")

    print(f"\n=== holdout 终验({HOLDOUT_START} → 今,untouched,只看一次)===")
    h = holdout_faber(faber_signals(10)[1], panel)
    for k, v in h.items():
        print(f"  {k}: {v if not isinstance(v, float) else f'{v:+.2%}' if '年化' in k or 'MDD' in k else f'{v:.4f}'}")
    holdout_pass = all(h[k] for k in h if k.startswith("判"))
    print(f"  → holdout {'✅ 通过' if holdout_pass else '❌ 未通过'}")

    save_derived(detail, "backtests/faber_wf_detail.parquet")
    df = pd.DataFrame({"date": nav.index, "nav": nav.values, "ret": res.ret.values,
                       "position": res.position.values, "drawdown": res.drawdown.values})
    save_derived(df, "backtests/faber_wf_oos.parquet")
    verdict = {"wf_pass": wf_pass, "holdout_pass": holdout_pass,
               "final": wf_pass and holdout_pass}
    print(f"\n最终裁决:{'✅ Faber 通过全部终验,进入第 4 步策略卡片化' if verdict['final'] else '❌ 未完全通过,按纪律处置'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
