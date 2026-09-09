"""双动量 GEM 信号层测试(裸脚本断言式,对齐 test_frontend_alignment 惯例,不入 CI)。

覆盖:①截断不变性(无未来函数)②扰动不变性(末行价格突变不改历史信号)
③历史锚点行为(设计文档第十节锚点预期表)④执行日对齐⑤落盘 schema。
用法:PYTHONPATH=src uv run python scripts/test_gem_signal.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from strategy import compute_gem_signals, save_signals          # noqa: E402
from strategy import gem_signal                                  # noqa: E402
from data_module.storage import read_raw                         # noqa: E402


def test_truncation_invariance() -> None:
    """截断不变性:只用 ≤2015-12-31 的数据,历史信号与全量计算逐行一致。"""
    full = compute_gem_signals()
    trunc = compute_gem_signals(gem_signal.StrategyConfig(as_of="2015-12-31"))
    left = full[full["date"] <= "2015-12-31"].reset_index(drop=True)
    pd.testing.assert_frame_equal(left, trunc, check_exact=True)
    assert not trunc.empty and len(left) == len(trunc)
    print(f"  截断不变性 OK({len(trunc)} 行逐行一致)")


def test_perturbation_invariance() -> None:
    """扰动不变性:spx/hs300 最后一行收盘 ×1.10 后,≤倒数第二个月末的信号不变。"""
    full = compute_gem_signals()
    cut = full["date"].iloc[-2]  # 倒数第二个月末(末月信号允许变)

    orig_read = gem_signal.read_raw
    def perturbed_read(rel: str):
        df = orig_read(rel)
        if rel in ("index_global/spx_inx.parquet", "index_daily/index_000300.parquet"):
            df = df.copy()
            df.iloc[-1, df.columns.get_loc("close")] *= 1.10
        return df
    gem_signal.read_raw = perturbed_read
    try:
        perturbed = compute_gem_signals()
    finally:
        gem_signal.read_raw = orig_read

    a = full[full["date"] <= cut].reset_index(drop=True)
    b = perturbed[perturbed["date"] <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    print(f"  扰动不变性 OK(≤{cut:%Y-%m-%d} 的 {len(a)} 行信号不受末行价格影响)")


def test_anchor_behaviour() -> None:
    """历史锚点(设计文档第十节,方向断言 + 宽松数值区间)。"""
    sig = compute_gem_signals().set_index("date")
    expect = [  # (月末, 预期持仓)
        ("2008-01-31", "hs300"), ("2008-04-30", "hs300"),
        ("2008-05-30", "bond"), ("2008-12-31", "bond"),
        ("2009-12-31", "hs300"), ("2014-12-31", "hs300"),
        ("2018-12-28", "bond"), ("2022-10-31", "bond"),
    ]
    for d, want in expect:
        got = sig.loc[d, "position"]
        assert got == want, f"锚点 {d}: 预期 {want}, 实得 {got}"
    # 年度持仓月数:2013/2024 全年标普,2015 全年沪深300
    pos = sig["position"]
    assert (pos.loc["2013"] == "spx").all()
    assert (pos.loc["2024"] == "spx").all()
    assert (pos.loc["2015"] == "hs300").all()
    # 宽松数值:2009-12 沪深300 12M 回报应在 0.8~1.1
    assert 0.8 < sig.loc["2009-12-31", "ret_hs300_12m"] < 1.1
    print("  锚点行为 OK(8 个单点 + 3 个全年 + 1 个数值区间)")


def test_exec_date_alignment() -> None:
    """执行日 = 信号日的次一交易日(calendar 推导),且均晚于信号日。"""
    sig = compute_gem_signals()
    cal = pd.DatetimeIndex(sorted(set(read_raw("calendar.parquet")["date"])))
    for _, row in sig.iterrows():
        nxt = cal[cal > row["date"]]
        assert len(nxt) and row["exec_date"] == nxt[0], \
            f"{row['date']} 的执行日 {row['exec_date']} ≠ 次一交易日 {nxt[0] if len(nxt) else None}"
    print(f"  执行日对齐 OK({len(sig)} 条全部 = 次一交易日)")


def test_schema() -> None:
    """落盘 schema:13 列齐全,值域合法。"""
    sig = compute_gem_signals()
    want_cols = {"date", "exec_date", "ret_spx_cny_12m", "ret_hs300_12m", "rf_12m",
                 "winner", "winner_ret_12m", "abs_excess", "position",
                 "etf_target", "premium_513500", "blocked_by_premium"}
    assert want_cols <= set(sig.columns), f"缺列: {want_cols - set(sig.columns)}"
    assert set(sig["position"].unique()) <= {"spx", "hs300", "bond"}
    assert (sig["abs_excess"] == sig["winner_ret_12m"] - sig["rf_12m"]).all()
    path = save_signals(sig)
    assert Path(path).exists()
    print(f"  schema OK({len(sig)} 行落盘 {path})")


def main() -> int:
    print("[gem_signal 测试]")
    test_truncation_invariance()
    test_perturbation_invariance()
    test_anchor_behaviour()
    test_exec_date_alignment()
    test_schema()
    print("gem_signal 全部 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
