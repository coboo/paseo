"""分层回测 + 滚动 IC 显著性（dividend-research backtest_layered.py 迁移版）。

- 分层：expanding 历史分位切五档（不含当日，与原实现一致）
- 指标：各档未来 h 日全收益均值、Q5-Q1 年化价差、滚动504日IC的均值/ICIR/正占比
- rolling_ic 修复前视：原实现先全样本秩变换再滚动相关（未来数据进入秩），
  改为滚动窗内（504 日）分别秩变换后再算 Pearson（= 窗内 Spearman）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from scipy.stats import rankdata

INSAMPLE_END = "2023-12-31"

# 因子 -> 方向(+1 值越大越看多, -1 取反后越大越看多)（原研究四重验证候选，冻结）
CANDIDATES = {
    "H30269": {"ey_spread": 1, "pe_ttm": -1, "mom_252": -1, "dv": 1, "erp": 1, "rel_pe": -1, "mom_63": -1},
    "930955": {"ey_spread": 1, "pe_ttm": -1, "mom_252": -1, "dv": 1, "erp": 1, "rel_pe": -1},
    "515450": {"dv_pct": 1, "erp_pct": 1, "mom_252": -1, "dv": 1},
    "159545": {"dv_pct": 1, "erp_pct": 1, "mom_126": -1},
}
HORIZONS = [63, 126, 252]


def quintile_expanding(s: pd.Series, min_periods: int = 504) -> pd.Series:
    """expanding 历史分位(不含当日) → 0..4 五档，-1 = 预热期。"""
    pct = s.expanding(min_periods=min_periods).apply(lambda x: (x[:-1] <= x[-1]).mean(), raw=True)
    return np.minimum((pct * 5).fillna(-1).astype(int), 4)


def layered(df: pd.DataFrame, fac: str, direction: int, h: int) -> dict:
    """单因子分档单调性：各档 fwd_h 均值 + 加权回归斜率（年化顶底差）。"""
    x = df[fac] * direction
    q = quintile_expanding(x)
    fwd = df[f"fwd_{h}"]
    res: dict = {}
    valid = q >= 0
    qs = fwd[valid].groupby(q[valid]).agg(["mean", "count"])
    res["q_means"] = qs["mean"]
    if len(qs) >= 3:
        w = qs["count"]
        slope = np.polyfit(qs.index.values.astype(float), qs["mean"].values, 1, w=w.values)[0]
        res["mono_slope"] = slope                    # 每升一档的平均收益改善(per h 日)
        res["ls_ann"] = slope * 4 * (252 / h)        # 顶底档差年化
    return res


def rolling_ic(df: pd.DataFrame, fac: str, direction: int, h: int, win: int = 504) -> dict | None:
    """滚动 win 日 Spearman IC 序列的统计（窗内秩变换，修复前视）。

    与原实现的差异：秩只在滚动窗内计算，窗口外数据不影响任何一期 IC。
    """
    sub = pd.DataFrame({"x": df[fac] * direction, "y": df[f"fwd_{h}"]}).dropna()
    x = sub["x"].to_numpy()
    y = sub["y"].to_numpy()
    if len(x) < win + 100:
        return None
    # 滑动窗展开 → 窗内秩变换（average 法，与 pandas rank 一致）→ 行向 Pearson
    xs = sliding_window_view(x, win)
    ys = sliding_window_view(y, win)
    rx = rankdata(xs, axis=1)
    ry = rankdata(ys, axis=1)
    rx = rx - rx.mean(axis=1, keepdims=True)
    ry = ry - ry.mean(axis=1, keepdims=True)
    cov = (rx * ry).mean(axis=1)
    ic = cov / (rx.std(axis=1) * ry.std(axis=1))
    ics = pd.Series(ic, index=sub.index[win - 1:])
    if len(ics) < 100:
        return None
    ann = np.sqrt(252 / h)
    return {"IC_mean": ics.mean(), "IC_std": ics.std(),
            "ICIR_ann": ics.mean() / ics.std() * ann, "pos_pct": (ics > 0).mean(),
            "n": len(ics)}


def run_layered(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """全标的分层 + 滚动 IC 表，等价原 backtest_layered.py 产物 layered_backtest。"""
    rows = []
    for name, facs in CANDIDATES.items():
        df = panels[name]
        if name in ("H30269", "930955"):
            bench = panels["000300"]
            df = df.copy()
            df["rel_pe"] = df["pe_ttm"] / bench["pe_ttm"].reindex(df.index).ffill()
        for fac, direc in facs.items():
            for h in HORIZONS:
                if f"fwd_{h}" not in df.columns:
                    continue
                r = layered(df, fac, direc, h)
                ic = rolling_ic(df, fac, direc, h)
                qm = r.get("q_means")
                if qm is None or len(qm) < 3:
                    continue
                rows.append({
                    "instrument": name, "factor": fac, "dir": direc, "h": h,
                    "Q1_mean": qm.get(0, np.nan), "Q5_mean": qm.get(4, np.nan),
                    "mono_slope": r.get("mono_slope", np.nan), "LS_ann": r.get("ls_ann", np.nan),
                    **(ic or {}),
                })
    return pd.DataFrame(rows)
