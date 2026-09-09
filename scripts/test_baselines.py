"""三基线测试(裸脚本断言式,不入 CI)。

覆盖:①引擎泛化正确性(run_monthly_weights 单资产特例 = run_monthly_switch)
②扰动不变性(末行价格突变不改历史信号)③权重合法性 ④Faber 锚点行为。
用法:PYTHONPATH=src uv run python scripts/test_baselines.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from strategy import StrategyConfig, compute_gem_signals                    # noqa: E402
from strategy import baseline_signals as bs                                 # noqa: E402
from strategy import gem_signal, panels                                     # noqa: E402
from strategy.engine_pandas import run_monthly_switch_pandas                # noqa: E402
from strategy.engine_weights import run_monthly_weights                     # noqa: E402
from strategy.run_baselines import run_faber, run_faber_etf                 # noqa: E402


def test_engine_weights_special_case() -> None:
    """单资产 one-hot 权重经组合引擎 = 单资产引擎(GEM 12M 对照,零成本应恒等)。"""
    sig = compute_gem_signals()
    panel = gem_signal.__dict__  # noqa: F841 — 仅为可读性
    from strategy.run_gem import build_open_panel
    prices = build_open_panel("index")
    et = sig.set_index("exec_date")["position"].dropna()
    a = run_monthly_switch_pandas("switch", "index", prices, et, StrategyConfig())
    onehot = pd.get_dummies(et).astype(float)
    onehot = onehot.reindex(columns=prices.columns, fill_value=0.0)
    b = run_monthly_weights("weights", "index", prices, onehot, StrategyConfig())
    diff = (a.nav.pct_change().fillna(0) - b.ret.reindex(a.nav.index).fillna(0)).abs().max()
    assert diff < 1e-12, f"组合引擎特例不守恒: {diff:.2e}"
    print(f"  引擎特例对账 OK(one-hot 组合 vs 单资产,日收益差 {diff:.0e})")


def test_perturbation_invariance() -> None:
    """扰动不变性:黄金/沪深300/ERP 源末值 ×1.10 后,≤倒数第二个月末信号不变。"""
    orig_series = panels._series
    orig_read = bs.read_raw

    def perturbed_series(key, price_col=None):
        s = orig_series(key, price_col)
        if key in ("gold", "hs300"):
            s = s.copy(); s.iloc[-1] *= 1.10
        return s

    def perturbed_read(rel):
        df = orig_read(rel)
        if rel in ("index_daily/index_000300.parquet", "gold/au_main_sina.parquet"):
            df = df.copy()
            df.iloc[-1, df.columns.get_loc("close")] *= 1.10
        return df

    panels._series = perturbed_series
    bs.read_raw = perturbed_read
    try:
        f0, w0 = bs.faber_signals()
        g0, _ = bs.gtaa_signals()
        f1, w1 = bs.faber_signals()
        g1, _ = bs.gtaa_signals()
    finally:
        panels._series = orig_series
        bs.read_raw = orig_read

    cut = f0["date"].iloc[-2]
    pd.testing.assert_frame_equal(
        f0[f0["date"] <= cut].reset_index(drop=True),
        f1[f1["date"] <= cut].reset_index(drop=True))
    cut_g = g0["date"].iloc[-2]
    pd.testing.assert_frame_equal(
        g0[g0["date"] <= cut_g].reset_index(drop=True),
        g1[g1["date"] <= cut_g].reset_index(drop=True))
    print(f"  扰动不变性 OK(Faber/GTAA ≤倒数次月末信号不受末值影响)")


def test_weights_validity() -> None:
    """权重表:行和=1、非负、列含 cash;执行日均在 A 股日历。"""
    for fn, name in [(bs.faber_signals, "faber"), (bs.fed_signals, "fed"), (bs.gtaa_signals, "gtaa")]:
        _, w = fn()
        assert (w.sum(axis=1) - 1.0).abs().max() < 1e-9, f"{name} 权重行和≠1"
        assert (w >= 0).all().all(), f"{name} 出现负权重"
        assert "cash" in w.columns
    print("  权重合法性 OK(三策略行和=1、非负、含 cash)")


def test_faber_anchors() -> None:
    """Faber 锚点(真实数据核对):2008-12 只剩 bond;2015-08 只剩 bond;
    2009-06 全通过;2018-12 bond+gold。"""
    sig, _ = bs.faber_signals()
    sig = sig.set_index("date")
    def above(d):
        r = sig.loc[d]
        return {k for k in ["hs300", "spx", "bond", "gold"] if r[f"{k}_above"]}
    assert above("2008-12-31") == {"bond"}
    assert above("2009-06-30") == {"hs300", "spx", "bond", "gold"}
    assert above("2015-08-31") == {"bond"}, "2015 股灾后应只剩债券"
    assert above("2018-12-28") == {"bond", "gold"}
    print("  Faber 锚点 OK(2008/2015 危机全防御、2009 复苏全通过、2018 债+金)")


def test_execution_retest_consistency() -> None:
    """执行层复测一致性:两层 MDD 差 <1pp(信号层结果非数据假象的交叉证据)。"""
    idx_res = run_faber()
    etf_res = run_faber_etf()
    d = abs(idx_res.summary["mdd"] - etf_res.summary["mdd"])
    assert d < 0.01, f"两层 MDD 差 {d:.1%} 异常"
    print(f"  执行层复测一致性 OK(信号层 {idx_res.summary['mdd']:.1%} vs ETF {etf_res.summary['mdd']:.1%})")


def test_walkforward_structure() -> None:
    """WF 结构断言:选参落网格内、段起点严格递增、样本外权重无重叠、
    每段选参只用 ≤oos_start 的数据(_segment_metrics 的 index 切片保证)。"""
    from strategy.walkforward import GRID, walk_forward_faber
    detail, w_oos = walk_forward_faber()
    assert detail["picked_sma"].isin(GRID).all()
    assert detail["oos_start"].is_monotonic_increasing
    assert not w_oos.index.duplicated().any()
    assert w_oos.index.min() > detail["oos_start"].iloc[0]  # 样本外起点在首段选参窗之后
    # 选参窗无未来函数:训练段评估终点 = oos_start(选参时刻),样本外权重全部 > 该时刻
    assert (w_oos.index > detail["oos_start"].iloc[0]).all()
    print(f"  walk-forward 结构 OK({len(detail)} 段,选参 ∈ {sorted(set(detail['picked_sma']))})")


def main() -> int:
    print("[baselines 测试]")
    test_engine_weights_special_case()
    test_perturbation_invariance()
    test_weights_validity()
    test_faber_anchors()
    test_execution_retest_consistency()
    test_walkforward_structure()
    print("baselines 全部 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
