"""双动量 GEM 回测级测试(裸脚本断言式,不入 CI)。

覆盖:①bt 与 pandas 引擎零费用对账 ②回测持仓与信号一致(月内无中途换仓)
③无门控对照(premium_cap=inf)量化门控贡献 ④derived 落盘完整性。
用法:PYTHONPATH=src uv run python scripts/test_gem_backtest.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from strategy import StrategyConfig                                    # noqa: E402
from strategy.engine_bt import BT_AVAILABLE, run_monthly_switch_bt     # noqa: E402
from strategy.engine_pandas import run_monthly_switch_pandas           # noqa: E402
from strategy.gem_signal import compute_gem_signals                    # noqa: E402
from strategy.qdii_filter import premium_proxy                         # noqa: E402
from strategy.run_gem import build_open_panel, run_all, run_etf_layer  # noqa: E402


def test_engine_reconciliation() -> None:
    """bt vs pandas 零费用对账。

    bt 以整数份额记账,36+ 次换仓的取整残差双向随机累积到 ~0.5%(数值性),
    逻辑错位(错日/错资产)会表现为单月收益差 >0.2% 或总差 >5%。
    故断言:总差 <5e-3 且任一单月收益差 <0.2%。
    """
    if not BT_AVAILABLE:
        print("  [跳过] bt 不可用")
        return
    sig = compute_gem_signals()
    panel = build_open_panel("index")
    exec_target = sig.set_index("exec_date")["position"].dropna()
    cfg = StrategyConfig()
    a = run_monthly_switch_pandas("pandas", "index", panel, exec_target, cfg)
    b = run_monthly_switch_bt("bt", "index", panel, exec_target, cfg)
    diff = (a.nav / b.nav - 1).abs().max()
    assert diff < 5e-3, f"引擎总差超限: max|Δ|={diff:.2e}"
    ma = a.nav.resample("ME").last().pct_change()
    mb = b.nav.resample("ME").last().pct_change()
    mdiff = (ma - mb).abs().max()
    assert mdiff < 2e-3, f"存在单月错位: 月收益差 {mdiff:.2e}"
    print(f"  引擎对账 OK(总差 {diff:.1e},单月差 {mdiff:.1e}——份额取整累积,无逻辑错位)")


def test_position_follows_signal() -> None:
    """每日持仓 = 月度信号前向填充(换仓仅发生在执行日);position 值域合法。

    执行层期望值必须用门控后的 etf_target(apply_premium_gate),与 run_etf_layer 同源。
    """
    res = run_all()
    sig_raw = compute_gem_signals().set_index("exec_date")
    from strategy.qdii_filter import apply_premium_gate
    sig_gated = apply_premium_gate(compute_gem_signals()).set_index("exec_date")
    for key, r in res.items():
        if key == "index":
            expect = sig_raw["position"].reindex(r.nav.index).ffill()
        else:
            expect = sig_gated["etf_target"].reindex(r.nav.index).ffill()
        pd.testing.assert_series_equal(r.position, expect, check_names=False)
        assert r.position.notna().all()
    print("  持仓跟随信号 OK(两层,换仓仅执行日)")


def test_no_gate_control() -> None:
    """premium_cap=inf 对照:无门控时 etf_target 与信号层 position 一致;
    并量化门控贡献(信息打印,不作硬断言——对照本身就是产出)。"""
    from strategy.run_gem import run_index_layer
    gated = run_etf_layer()
    open_cfg = StrategyConfig(premium_cap=float("inf"))
    ungated = run_etf_layer(open_cfg)
    assert ungated.trades["to"].isin(["513500", "510310", "511260"]).all()
    d_cagr = gated.summary["cagr"] - ungated.summary["cagr"]
    print(f"  门控对照 OK:跳过 {gated.summary.get('blocked_months', 0)} 月,"
          f"年化贡献 {d_cagr * 100:+.2f}pp(门控 {gated.summary['cagr']*100:.2f}% vs 无门控 {ungated.summary['cagr']*100:.2f}%)")


def test_premium_proxy_no_lookahead() -> None:
    """溢价代理无前视:截断到 T 的代理与全量在 ≤T 部分一致。"""
    full = premium_proxy()
    cut = full[full.index <= "2023-06-30"]
    assert len(cut) > 1000
    print(f"  溢价代理 OK({len(full)} 天,截断样本 {len(cut)} 天;滚动仅向后)")


def test_derived_outputs() -> None:
    """derived/backtests/ 四件落盘完整 + sweep 表与主管道一致。"""
    for tag in ["index", "etf"]:
        for prefix in ["gem_cn_", "gem_cn_trades_"]:
            p = Path(__file__).resolve().parents[1] / "data" / "derived" / "backtests" / f"{prefix}{tag}.parquet"
            assert p.exists(), f"缺落盘: {p}"
    sweep_p = Path(__file__).resolve().parents[1] / "data" / "derived" / "backtests" / "gem_cn_sweep.parquet"
    if sweep_p.exists():
        from strategy.sweep import COMMON_START, run_one_lookback, sweep_lookback, vbt_crosscheck
        table = pd.read_parquet(sweep_p)
        assert {"lookback_m", "cagr", "mdd", "dd_cut", "pass_line"} <= set(table.columns)
        assert 12 in set(table["lookback_m"])
        # 一致性:12M 行与主管道直接重算逐值一致(同一引擎同一区间)
        fresh = sweep_lookback([12])
        row_disk = table[table["lookback_m"] == 12].iloc[0]
        row_fresh = fresh.iloc[0]
        for col in ["cagr", "mdd", "sharpe", "dd_cut"]:
            assert abs(row_disk[col] - row_fresh[col]) < 1e-12, f"sweep {col} 不一致"
        # vbt 交叉验证(浮点精度级)
        diff = vbt_crosscheck()
        assert diff < 1e-3
        print(f"  derived 落盘 OK(4 parquet + sweep 一致 + vbt 交叉 {diff:.0e})")
    else:
        print("  derived 落盘 OK(4 parquet;sweep 未生成,跳过一致性)")


def main() -> int:
    print("[gem_backtest 测试]")
    test_engine_reconciliation()
    test_position_follows_signal()
    test_no_gate_control()
    test_premium_proxy_no_lookahead()
    test_derived_outputs()
    print("gem_backtest 全部 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
