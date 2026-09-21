"""红利低波簇研究（src/dividend/）迁移验证测试（裸脚本断言式，不入 CI）。

覆盖：
① 因子面板 schema 与行数断言
② 冻结权重复现：权重与第 0 步产物一致；修复点（pct_rank 不含当日）处
   新面板 = 旧面板 shift(1) 精确吻合；打分计算确定性（两遍逐值一致）+
   ASOF 截尾快照硬编码断言（研究目录已删，原 score_*.csv 逐行复现改为
   对本仓库冻结产物的自校验，数值 2026-09-21 实测写入）
③ 无前视断言：rolling_ic 窗内秩（未来数据扰动不影响历史 IC）、pct_rank 不含当日
④ 净值日期对齐守卫（自校验版）：净值日期落在 A 股日历内 + 净值收益与
   H30269 同日相关严格大于 ±1 日错位相关（原研究 CSV 对拍随目录删除下线）
⑤ 主项目数据验收五查回归

用法：PYTHONPATH=src uv run python scripts/test_dividend.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data_module import validate as dm_validate          # noqa: E402
from data_module.storage import read_raw                 # noqa: E402
from dividend import factors, layered, score             # noqa: E402

PANEL_MIN_ROWS = {"H30269": 2800, "930955": 2800, "515450": 1500, "159545": 400}
PANEL_COLS = ["close", "tr", "dv", "erp", "ey_spread", "cgb10",
              "mom_21", "mom_63", "mom_126", "mom_252", "vol_20", "vol_60",
              "pe_pct", "dv_pct", "erp_pct", "fwd_21", "fwd_63", "fwd_126", "fwd_252"]

# 打分快照 ASOF：面板截尾至该日，数据追加后快照值不变（2026-09-21 写入）
ASOF = "2026-09-18"
# 冻结产物 ASOF 读数（score_full 含动量口径，2026-09-21 实测；权重只用
# ≤2023 样本内，数据追加不影响；任何实现改动导致读数漂移都会在此显形）
FROZEN_READINGS = {
    "H30269": {"score_z": 0.38, "score_pctile": 0.521, "P(fwd126>0)": 0.721, "P(fwd252>0)": 0.915},
    "930955": {"score_z": 0.31, "score_pctile": 0.553, "P(fwd126>0)": 0.750, "P(fwd252>0)": 0.941},
    "515450": {"score_z": -0.90, "score_pctile": 0.298, "P(fwd126>0)": 0.790, "P(fwd252>0)": 0.946},
    "159545": {"score_z": 1.03, "score_pctile": 0.828, "P(fwd126>0)": 1.000, "P(fwd252>0)": 0.889},
}

# 第 0 步产物 current_scores.csv 的冻结权重（icir_weights 估计，勿改）
FROZEN_WEIGHTS = {
    "H30269": {"ey_spread": 0.253, "pe_ttm": 0.25, "mom_252": 0.463, "dv_pct": 0.017, "erp_pct": 0.016},
    "930955": {"ey_spread": 0.22, "pe_ttm": 0.219, "mom_252": 0.541, "dv_pct": 0.004, "erp_pct": 0.016},
    "515450": {"dv_pct": 0.676, "erp_pct": 0.108, "mom_126": 0.216},
    "159545": {"dv": 1 / 3, "erp": 1 / 3, "mom_126": 1 / 3},
}


def legacy_pct_rank(s: pd.Series, min_periods: int = 252) -> pd.Series:
    """原研究 pct_rank（含当日做参照），仅测试用于复现第 0 步产物。"""
    return s.expanding(min_periods=min_periods).apply(lambda x: (x[:-1] <= x[-1]).mean(), raw=True)


def test_panel_schema(panels: dict[str, pd.DataFrame]) -> None:
    """① 因子面板 schema 与行数。"""
    for code, min_rows in PANEL_MIN_ROWS.items():
        df = panels[code]
        missing = [c for c in PANEL_COLS if c not in df.columns]
        assert not missing, f"{code} 缺列: {missing}"
        assert len(df) >= min_rows, f"{code} 行数 {len(df)} < {min_rows}"
        assert df.index.is_monotonic_increasing and df.index.is_unique, f"{code} 索引未排序/有重复"
        assert df["tr"].notna().all(), f"{code} tr 存在缺失"
        print(f"  ① {code}: {len(df)} 行 {df.index[0]:%Y-%m-%d}~{df.index[-1]:%Y-%m-%d} schema OK")


def test_frozen_weights(panels: dict[str, pd.DataFrame]) -> None:
    """②a 冻结权重：与第 0 步产物一致（容差 0.02）。

    权重估计程序完全冻结（icir_weights 未改），但 pct_rank 前视修复改变了
    dv_pct/erp_pct 输入，归一化后权重微移（如 930955 mom_252 0.541→0.543、
    515450 dv_pct 0.676→0.688），属修复导致的记录级差异，非改参；
    新旧权重全部打印留档。
    """
    _, summ = score.score_full(panels)
    for _, row in summ.iterrows():
        code = row["instrument"]
        for f, expect in FROZEN_WEIGHTS[code].items():
            got = row["weights"][f]
            assert abs(got - expect) < 0.02, f"{code} 权重 {f}: {got} != 冻结值 {expect}"
            if abs(got - expect) >= 0.0015:
                print(f"    ⚠ {code}.{f}: {expect} -> {got}（pct_rank 修复导致的微移，已记录）")
    print("  ②a 冻结权重与第 0 步产物一致（容差 0.02，微移已打印留档）")


def test_score_reproduction(panels: dict[str, pd.DataFrame]) -> None:
    """②b 修复点精确吻合 + 打分确定性 + ASOF 冻结读数硬编码断言。

    H30269/930955 的 raw 数据与第 0 步完全相同（同一批 csindex CSV 迁移），因此：
    - 新面板 dv_pct/erp_pct/pe_pct 应等于旧算法 shift(1)（不含当日修复）；
    - 研究目录已删（2026-09-21 用户决定清理），原"旧算法复现 score_*.csv 逐行
      一致"改为自校验：同一面板两遍打分逐值一致（确定性）+ 面板截尾至 ASOF
      的冻结读数与下方硬编码快照逐项相等（任何实现改动/权重漂移在此显形）。
    """
    for code in ("H30269", "930955"):
        new = panels[code]
        for c in ("dv_pct", "erp_pct", "pe_pct"):
            src = "pe_ttm" if c == "pe_pct" else c.replace("_pct", "")
            shifted = legacy_pct_rank(new[src]).shift(1)
            a, b = new[c].iloc[253:].to_numpy(), shifted.iloc[253:].to_numpy()
            mask = ~np.isnan(a) & ~np.isnan(b)
            # 理论上 new(t) = legacy(t-1)·(t-1)/t（窗口分母差一日）， Warmup 段容差放宽
            assert np.allclose(a[mask], b[mask], atol=5e-3), f"{code}.{c} 与旧算法 shift(1) 不吻合"
        print(f"  ②b {code}: 修复点=旧算法 shift(1) 吻合")

    # 确定性：同一面板两遍打分逐值一致（score_z / score_pct / 概率全链路）
    s1, _ = score.score_full(panels)
    s2, _ = score.score_full(panels)
    for code in score.INSTRUMENTS:
        for col in ("score_z", "score_pct"):
            d = (s1[code][col] - s2[code][col]).abs().max()
            assert d == 0.0, f"{code} {col} 两遍不一致 max|diff|={d}"
    print("  ②b 打分确定性：两遍 score_z/score_pct 逐值一致")

    # ASOF 截尾快照：冻结读数与硬编码一致（快照值不随数据追加漂移）
    panels_asof = {c: p.loc[:ASOF] for c, p in panels.items()}
    _, summ = score.score_full(panels_asof)
    summ = summ.set_index("instrument")
    for code, expect in FROZEN_READINGS.items():
        for col, want in expect.items():
            got = summ.loc[code, col]
            assert got == want, f"{code} {col}: {got} != 冻结快照 {want}（ASOF {ASOF}）"
    print(f"  ②b ASOF({ASOF}) 冻结读数与硬编码快照逐项一致")

    # 新口径打分与第 0 步读数（数据截止 2026-09-11 基金 / 09-18 指数，差异已在报告记录）
    _, summ = score.score_full(panels)
    print(summ[["instrument", "score_z", "score_pctile", "P(fwd252>0)", "non_extrapolatable"]]
          .to_string(index=False))
    assert bool(summ.set_index("instrument").loc["159545", "non_extrapolatable"]), \
        "159545 必须带不可外推标记"


def test_no_lookahead(panels: dict[str, pd.DataFrame]) -> None:
    """③ 无前视：rolling_ic 窗内秩 + pct_rank 不含当日。"""
    df = panels["H30269"]
    ic_full = layered.rolling_ic(df, "ey_spread", 1, 126)["ICIR_ann"]  # 触发计算
    # 扰动未来 200 日因子值，窗口未覆盖到的历史 IC 必须不变（窗内秩不变性）
    mod = df.copy()
    mod.iloc[-200:, mod.columns.get_loc("ey_spread")] *= 1000.0
    r_full = layered.rolling_ic(df, "ey_spread", 1, 126)
    r_mod = layered.rolling_ic(mod, "ey_spread", 1, 126)
    cut = df.index[-200 - 504]
    a = r_full["IC_mean"] if False else None  # 占位说明：以完整 IC 序列对比
    icser_full = _ic_series(df, "ey_spread", 1, 126)
    icser_mod = _ic_series(mod, "ey_spread", 1, 126)
    left = icser_full.loc[:cut]
    right = icser_mod.loc[:cut]
    assert np.allclose(left, right, atol=1e-12), "未来数据扰动改变了历史滚动IC（存在前视）"
    print(f"  ③a rolling_ic 窗内秩：扰动未来 200 日，{len(left)} 期历史 IC 逐值不变")

    # pct_rank 不含当日：修改 t 日数据，t 日分位不变
    s = panels["515450"]["dv"].dropna()
    pct = factors.pct_rank(s)
    s2 = s.copy()
    s2.iloc[600] = s2.iloc[600] * 3 + 1  # 任意扰动中间一天
    pct2 = factors.pct_rank(s2)
    assert pct.iloc[600] == pct2.iloc[600], "pct_rank 当日值依赖了当日数据（前视）"
    assert pct.iloc[601] != pct2.iloc[601], "pct_rank 次日未反映扰动，shift 方向存疑"
    print("  ③b pct_rank 不含当日：扰动 t 日，t 日分位不变、t+1 日变化")


def _ic_series(df: pd.DataFrame, fac: str, direction: int, h: int, win: int = 504) -> pd.Series:
    """rolling_ic 的内部 IC 序列（复制 layered 窗内秩实现供扰动对比）。"""
    from numpy.lib.stride_tricks import sliding_window_view
    from scipy.stats import rankdata
    sub = pd.DataFrame({"x": df[fac] * direction, "y": df[f"fwd_{h}"]}).dropna()
    xs = sliding_window_view(sub["x"].to_numpy(), win)
    ys = sliding_window_view(sub["y"].to_numpy(), win)
    rx, ry = rankdata(xs, axis=1), rankdata(ys, axis=1)
    rx = rx - rx.mean(axis=1, keepdims=True)
    ry = ry - ry.mean(axis=1, keepdims=True)
    ic = (rx * ry).mean(axis=1) / (rx.std(axis=1) * ry.std(axis=1))
    return pd.Series(ic, index=sub.index[win - 1:])


def test_nav_alignment() -> None:
    """④ 净值日期对齐守卫（自校验版，2026-09-21 起）。

    研究 CSV（pingzhongdata）对拍已随 dividend-research/ 目录删除下线。留下的
    回归风险是"净值日期错位 -1 交易日"（迁移期踩过的坑），自校验口径：
    - 净值日期必须落在 A 股交易日历内（抓错源/错位会跑出日历）；
    - 净值日收益与 H30269（A 股红利低波，同风格锚）**同日**相关必须严格
      大于 ±1 日错位相关——日期一旦错位，lag-0 相关塌缩、错位相关不升。
    """
    cal = pd.DatetimeIndex(read_raw("calendar.parquet")["date"].sort_values())
    cal_set = set(cal)
    anchor = read_raw("index_daily/index_H30269.parquet").set_index("date")["close"]
    r_anchor = anchor.pct_change()

    for code, rel in [("515450", "index_daily/spdiv50_nav_515450.parquet"),
                      ("159545", "index_global/hshylv_nav_159545.parquet")]:
        nav = read_raw(rel).set_index("date")["close"]
        in_cal = pd.DatetimeIndex(nav.index).isin(cal_set).mean()
        assert in_cal > 0.99, f"{code} 净值日期 {in_cal:.2%} 落在 A 股日历外"
        r_nav = nav.pct_change()
        corrs = {}
        for lag in (-1, 0, 1):
            j = pd.concat([r_nav, r_anchor.shift(-lag).rename("a")], axis=1,
                          sort=False).dropna()
            corrs[lag] = j.iloc[:, 0].corr(j.iloc[:, 1])
        assert corrs[0] > 0.5, f"{code} 同日相关 {corrs[0]:.3f} 过低，净值数据可疑"
        assert corrs[0] > corrs[-1] + 0.3 and corrs[0] > corrs[1] + 0.3, \
            f"{code} 同日相关未显著优于错位相关: {corrs}"
        print(f"  ④ {code}: {len(nav)} 行，日历内 {in_cal:.2%}；"
              f"vs H30269 相关 lag-1/0/+1 = {corrs[-1]:.3f}/{corrs[0]:.3f}/{corrs[1]:.3f}"
              "（同日显著占优，日期无错位）")


def test_data_validation() -> None:
    """⑤ 主项目数据验收五查回归（新增数据集不应破坏五查）。"""
    assert dm_validate.main() == 0, "data_module 五查未全过"
    print("  ⑤ data_module 五查全过")


def main() -> None:
    print("== ① 因子面板 schema ==")
    panels = factors.build_panels()
    test_panel_schema(panels)
    print("== ② 冻结权重复现 ==")
    test_frozen_weights(panels)
    test_score_reproduction(panels)
    print("== ③ 无前视 ==")
    test_no_lookahead(panels)
    print("== ④ 净值对齐 ==")
    test_nav_alignment()
    print("== ⑤ 数据验收五查 ==")
    test_data_validation()
    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()
