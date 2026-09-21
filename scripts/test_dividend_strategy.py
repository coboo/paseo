"""红利低波簇打分轮动验证链路测试（裸脚本断言式，不入 CI）。

覆盖（对应设计文档十三节验证协议）：
①档位边界（39/40/41、59/60/61，hyst=0）与迟滞方向性（升档需越界+2pp、降档即触发）
②权重合法性（真实打分序列：每标的 ≤ 建议权重、簇和 ≤ 32.6%；强制满配的缩容）
③无未来函数（扰动 2024 年后分位，2024 年前逐月权重逐项不变）
④WF 无泄漏（扰动末段测试窗分位，所有段选参不变——训练窗与扰动窗不相交）
⑤引擎特例（单标的 100% 权重、零成本 = 直接持有该标的净值）

用法:PYTHONPATH=src uv run --no-sync python scripts/test_dividend_strategy.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dividend.strategy import (CLUSTER_CAP, CODES, DEFAULT_WEIGHTS,   # noqa: E402
                               compute_target_weights, next_gear)
from dividend.backtest import (build_signal_panel, run_dividend_backtest,  # noqa: E402
                               weights_at_exec)
from dividend.walkforward import (GRID, grid_weights, load_pct_series,  # noqa: E402
                                  month_end_anchors, walk_forward)

PASS = "✅"


def _mk_pct(values: dict[str, list[float]], start: str = "2018-01-31") -> dict[str, pd.Series]:
    """构造月末锚点分位序列（值列表逐月）；未给值的标的默认 99（零配区）。"""
    n = max(len(v) for v in values.values())
    anchors = pd.date_range(start, periods=n, freq="ME")
    out = {}
    for code in CODES:
        vals = values.get(code, [99.0] * n)
        out[code] = pd.Series(vals, index=anchors[: len(vals)]).astype(float)
    return out


def test_gear_boundaries() -> None:
    """档位边界（hyst=0）：39→全配 40/41→半配 59→半配 60/61→零配。"""
    w = {c: 0.25 for c in CODES}
    for pct_v, expect in [(39.0, 0.25), (40.0, 0.125), (41.0, 0.125),
                          (59.0, 0.125), (60.0, 0.0), (61.0, 0.0)]:
        pct = _mk_pct({"H30269": [pct_v] * 6})
        out = compute_target_weights(pct, enter=40, exit=60, hyst=0, weights=w)
        got = float(out["H30269"].iloc[-1])
        assert abs(got - expect) < 1e-12, f"pct={pct_v}: got {got}, expect {expect}"
    print(f"{PASS} 档位边界 39/40/41、59/60/61（hyst=0）")


def test_hysteresis_direction() -> None:
    """迟滞方向性：升档需越界+2pp，降档即触发（graduated 跨级升档语义固定）。"""
    w = {c: 0.25 for c in CODES}
    # 迟滞带（hyst=2, enter=40, exit=60）：升档阈值 = 界−2pp → 零配维持区 [58,100)，
    # 半配区 [38,58)，全配区 (-∞,38)；降档用原界（40→半、60→零）立即触发。
    seq = [58.0] * 3 + [57.0] * 2 + [37.0] * 2 + [45.0] * 2 + [39.0] * 2 + [37.0] * 2 + [61.0] * 2
    pct = _mk_pct({"H30269": seq})
    out = compute_target_weights(pct, enter=40, exit=60, hyst=2, weights=w)["H30269"]
    #           58×3     57×2     37×2     45×2     39×2     37×2     61×2
    expect = [0.0] * 3 + [0.125] * 2 + [0.25] * 2 + [0.125] * 2 + [0.125] * 2 + [0.25] * 2 + [0.0] * 2
    for i, (got, exp) in enumerate(zip(out.tolist(), expect)):
        assert abs(got - exp) < 1e-12, f"step {i}: got {got}, expect {exp}"
    # 状态机单元断言：38 不满足 full（需 <38），41 降档立即触发
    assert next_gear("zero", 38.0, 40, 60, 2) == "half"
    assert next_gear("zero", 37.999, 40, 60, 2) == "full"
    assert next_gear("full", 40.0, 40, 60, 2) == "half"   # 降档无迟滞
    assert next_gear("half", 39.0, 40, 60, 2) == "half"   # 升档差 1pp 不够
    assert next_gear("half", 37.0, 40, 60, 2) == "full"
    print(f"{PASS} 迟滞方向性（升档需 +2pp、降档即触发、graduated 跨级）")


def test_weight_legality() -> None:
    """真实打分序列（冻结口径）：每标的 ≤ 建议权重、簇和 ≤ 32.6%；缩容生效。"""
    pct = load_pct_series()
    out = compute_target_weights(pct)  # 默认 enter=40 exit=60 hyst=2 建议权重 0.326 上限
    for c in CODES:
        assert float(out[c].max()) <= DEFAULT_WEIGHTS[c] + 1e-9, f"{c} 超建议权重"
    assert float(out.sum(axis=1).max()) <= CLUSTER_CAP + 1e-9, "簇和超上限"
    # 满配之和恰 = 上限（32.6%），不缩
    full = compute_target_weights(_mk_pct({c: [10.0] * 6 for c in CODES}))
    assert abs(float(full.sum(axis=1).max()) - CLUSTER_CAP) < 1e-9
    # 强制四标的建议权重提到 25%（和 100%）→ 缩容到上限
    w = {c: 0.25 for c in CODES}
    forced = compute_target_weights(_mk_pct({c: [10.0] * 6 for c in CODES}),
                                    weights=w, cap=0.2)
    assert abs(float(forced.sum(axis=1).max()) - 0.2) < 1e-9
    assert abs(float(forced["H30269"].iloc[-1]) - 0.2 * 0.25) < 1e-9  # 等比例缩
    print(f"{PASS} 权重合法性（≤建议权重、簇和≤32.6%、等比例缩容）")


def test_no_lookahead() -> None:
    """无未来函数：扰动 2024 年后分位值，2024 年前的逐月权重逐项不变。"""
    rng = np.random.default_rng(7)
    anchors = pd.date_range("2018-01-31", periods=104, freq="ME")
    base = {c: pd.Series(rng.uniform(5, 95, len(anchors)), index=anchors) for c in CODES}
    w_base = compute_target_weights(base, anchors=anchors)
    perturbed = {c: s.copy() for c, s in base.items()}
    for c in CODES:
        perturbed[c].loc[perturbed[c].index >= "2024-01-01"] += 50.0
    w_pert = compute_target_weights(perturbed, anchors=anchors)
    hist = w_base.index < "2024-01-01"
    pd.testing.assert_frame_equal(w_base[hist], w_pert[hist], check_exact=True)
    print(f"{PASS} 无未来函数（扰动 2024 后分位，2024 前权重逐项不变）")


def test_walkforward_no_leak() -> None:
    """WF 无泄漏：扰动末段测试窗（2025-01→2025-09-15）分位，所有段选参不变。

    末段测试窗与所有段的训练窗均不相交（各训练窗止于 ≤2025-01），
    若选参泄漏用到测试窗数据，选参将随扰动变化。
    """
    pct = load_pct_series()
    panel = build_signal_panel()
    data_end = min(panel.index.max(), min(s.index.max() for s in pct.values()))
    anchors = month_end_anchors(data_end)
    detail0, _, frozen0 = walk_forward(pct, panel, grid_weights(pct, anchors))

    perturbed = {c: s.copy() for c, s in pct.items()}
    for c in CODES:
        mask = (perturbed[c].index > "2025-01-01") & (perturbed[c].index <= "2025-09-15")
        perturbed[c].loc[mask] = 0.0  # 极端扰动：全部打到"极低估"
    detail1, _, frozen1 = walk_forward(perturbed, panel, grid_weights(perturbed, anchors))

    cols = ["enter", "exit", "hyst"]
    pd.testing.assert_frame_equal(detail0[cols].reset_index(drop=True),
                                  detail1[cols].reset_index(drop=True), check_exact=True)
    assert frozen0 == frozen1
    assert len(detail0) >= 5, f"WF 段数异常: {len(detail0)}"
    print(f"{PASS} WF 无泄漏（扰动末段测试窗，{len(detail0)} 段选参逐项不变，冻结规则 {frozen0}）")


def test_engine_single_asset_identity() -> None:
    """引擎特例：单标的 100% 权重（零成本）= 直接持有该标的净值（容差内）。"""
    rng = np.random.default_rng(11)
    days = pd.bdate_range("2023-01-02", periods=80)
    panel = pd.DataFrame({"cash": np.ones(len(days))}, index=days)
    for c in CODES:
        r = rng.normal(0.0004, 0.01, len(days))
        panel[c] = 100 * np.cumprod(1.0 + r)
    anchor = days[20]
    w_anchor = pd.DataFrame([{**{c: 0.0 for c in CODES}, "H30269": 1.0}],
                            index=pd.DatetimeIndex([anchor]))
    # 锚点 → 次一交易日执行
    w_exec = weights_at_exec(w_anchor, panel.index)
    assert w_exec.index[0] == days[21], "锚点未映射到次一交易日"

    res = run_dividend_backtest("id", "index", panel, w_anchor, cost_bps=0.0)
    exec_day = days[21]
    bench = panel["H30269"] / panel["H30269"].loc[exec_day]
    got = res.nav[res.nav.index >= exec_day]
    exp = bench.loc[got.index]
    assert np.allclose(got, exp, rtol=1e-10, atol=1e-12), "单标的恒等失败"
    # 建仓前净值 = 1（从现金开始）
    assert float(res.nav.loc[: days[20]].iloc[-1]) == 1.0
    print(f"{PASS} 引擎特例（单标的 100% 零成本 = 直接持有，恒等通过）")


if __name__ == "__main__":
    test_gear_boundaries()
    test_hysteresis_direction()
    test_weight_legality()
    test_no_lookahead()
    test_walkforward_no_leak()
    test_engine_single_asset_identity()
    print("\n全部通过 ✅")
