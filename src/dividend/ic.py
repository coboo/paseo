"""因子 IC 回测（dividend-research backtest_ic.py 迁移版）。

Spearman 秩相关 + 样本内/外分段。标签为未来 h 日全收益。
rel_pe_pct 修复前视：与 pct_rank 同法，shift(1) 后取 expanding 分位（不含当日）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

INSAMPLE_END = "2023-12-31"
HORIZONS = [21, 63, 126, 252]

BASE_FACTORS = ["pe_ttm", "pe_pct", "dv", "dv_pct", "erp", "erp_pct", "ey_spread",
                "mom_21", "mom_63", "mom_126", "mom_252", "vol_20", "vol_60"]

INSTRUMENTS = ["H30269", "930955", "515450", "159545"]


def add_rel_pe(df: pd.DataFrame, bench_pe: pd.Series) -> pd.DataFrame:
    """相对沪深300 PE 及其 expanding 分位（不含当日，修复前视）。"""
    df = df.copy()
    df["rel_pe"] = df["pe_ttm"] / bench_pe.reindex(df.index).ffill()
    past = df["rel_pe"].shift(1)
    df["rel_pe_pct"] = past.expanding(min_periods=252).apply(
        lambda x: (x[:-1] <= x[-1]).mean(), raw=True)
    return df


def ic_table(df: pd.DataFrame) -> pd.DataFrame:
    """单标的 16 因子 × 4 期限 Spearman IC（全样本/样本内/样本外）。"""
    rows = []
    facs = [f for f in BASE_FACTORS + ["rel_pe", "rel_pe_pct"] if f in df.columns]
    for fac in facs:
        for h in HORIZONS:
            sub = df[[fac, f"fwd_{h}"]].dropna()
            if len(sub) < 300:
                continue
            ic_all = sub[fac].corr(sub[f"fwd_{h}"], method="spearman")
            is_sub = sub.loc[:INSAMPLE_END]
            oos_sub = sub.loc[INSAMPLE_END:]
            ic_is = is_sub[fac].corr(is_sub[f"fwd_{h}"], method="spearman")
            ic_oos = oos_sub[fac].corr(oos_sub[f"fwd_{h}"], method="spearman") \
                if len(oos_sub) > 60 else np.nan
            rows.append({"factor": fac, "horizon": h, "n": len(sub),
                         "IC_all": ic_all, "IC_insample": ic_is, "IC_oosample": ic_oos})
    return pd.DataFrame(rows)


def run_ic(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """全标的 IC 表（instrument 列前置），等价原 backtest_ic.py 产物 ic_summary。"""
    bench_pe = panels["000300"]["pe_ttm"]
    all_rows = []
    for name in INSTRUMENTS:
        df = panels[name]
        if name in ("H30269", "930955"):
            df = add_rel_pe(df, bench_pe)
        t = ic_table(df)
        t.insert(0, "instrument", name)
        all_rows.append(t)
    return pd.concat(all_rows, ignore_index=True)
