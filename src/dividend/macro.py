"""宏观因子检验（dividend-research macro_test.py 迁移版，只读消费）。

数据：data/raw/macro/macro_monthly.parquet（M1M2 剪刀差 + PPI 同比，月度，
已滞后一月防发布日泄漏），由 data_module 数据集 macro_monthly 维护。
**不再在线抓取覆写 raw**（原 macro_test.py 的覆写行为已删除）。

结论（HANDOFF §5.3 已否决，此处留档复验）：
- M1M2 剪刀差：负增量；PPI 同比：零增量 → 不入模。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

from data_module.storage import read_raw

INSAMPLE_END = "2023-12-31"
OOS_START = "2024-01-01"

_TEST_CODES = ["H30269", "930955", "515450"]  # 159545 历史太短，原研究未检
_INCREMENT_CODES = ["H30269", "930955"]


def load_macro() -> pd.DataFrame:
    """宏观月度序列（DatetimeIndex）：m1m2 / ppi_yoy。"""
    m = read_raw("macro/macro_monthly.parquet")
    return m.set_index("date")[["m1m2", "ppi_yoy"]].sort_index()


def _rolling_icir(x: pd.Series, y: pd.Series, win: int = 504, h: int = 126) -> dict | None:
    """滚动 win 日 Spearman IC 的 ICIR（全样本秩变换，与原研究实现一致，仅诊断用）。"""
    sub = pd.DataFrame({"x": x, "y": y}).dropna()
    rx, ry = sub["x"].rank(), sub["y"].rank()
    ic = rx.rolling(win).corr(ry).dropna()
    if len(ic) < 60:
        return None
    ann = np.sqrt(252 / h)
    oos = ic.loc[OOS_START:]
    return {"ICIR": ic.mean() / ic.std() * ann, "pos": (ic > 0).mean(),
            "ICIR_oos": (oos.mean() / oos.std() * ann) if len(oos) > 30 else np.nan}


def macro_independent(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """宏观因子独立检验：滚动504日ICIR(样本内/OOS) vs fwd_126/252。"""
    macro = load_macro()
    rows = []
    for code in _TEST_CODES:
        mx = macro.reindex(panels[code].index).ffill()
        for f in ["m1m2", "ppi_yoy"]:
            for lab, col in [("126d", "fwd_126"), ("252d", "fwd_252")]:
                r = _rolling_icir(mx[f], panels[code][col])
                if r:
                    rows.append({"instrument": code, "factor": f, "label": lab,
                                 **{k: round(v, 2) for k, v in r.items()}})
    return pd.DataFrame(rows)


def _expanding_z(s: pd.Series, min_periods: int = 504) -> pd.Series:
    return (s - s.expanding(min_periods).mean()) / s.expanding(min_periods).std()


def _icir_w(df: pd.DataFrame, factors: dict[str, int], h: int = 126, win: int = 504) -> dict[str, float]:
    """样本内 ICIR 权重（与原研究 macro_test 同实现，勿改）。"""
    w = {}
    for f, d in factors.items():
        sub = pd.DataFrame({"x": df[f] * d, "y": df[f"fwd_{h}"]}).dropna().loc[:INSAMPLE_END]
        rx, ry = sub["x"].rank(), sub["y"].rank()
        ic = rx.rolling(win).corr(ry).dropna()
        if len(ic) >= 100:
            w[f] = max(abs(ic.mean() / ic.std()) * np.sqrt(252 / h), 0.0)
    t = sum(w.values())
    return {k: v / t for k, v in w.items()} if t else {}


def _oos_pred_eval(score: pd.Series, fwd: pd.Series) -> dict | None:
    """OOS 预测-实现相关(降重叠抽样) + 频率法 Brier。"""
    sub = pd.DataFrame({"z": score, "y": fwd}).dropna()
    te = sub.loc[OOS_START:]
    if len(te) < 200:
        return None
    tes = te.iloc[::12]  # ~季度抽样降重叠
    r = tes["z"].corr(tes["y"], method="spearman")
    tr = sub.loc[:INSAMPLE_END]
    fp = []
    for zv in tes["z"]:
        near = tr.loc[abs(tr["z"] - zv) <= 0.5, "y"]
        fp.append((near > 0).mean() if len(near) >= 20 else (tr["y"] > 0).mean())
    brier = brier_score_loss((tes["y"] > 0).astype(int), fp)
    return {"corr": round(r, 3), "brier": round(brier, 3), "n": len(tes)}


def macro_increment(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """增量检验：合成打分(±宏观) OOS 表现（corr/brier，每组合一行）。"""
    macro = load_macro()
    rows = []
    for code in _INCREMENT_CODES:
        mx = macro.reindex(panels[code].index).ffill()
        df = panels[code].copy()
        df["m1m2_z"] = _expanding_z(mx["m1m2"])
        df["ppi_z"] = _expanding_z(mx["ppi_yoy"])
        base_facs = {"ey_spread": 1, "pe_ttm": -1, "mom_252": -1, "dv_pct": 1, "erp_pct": 1}
        for label, facs in [("原模型", base_facs),
                            ("+M1M2", dict(base_facs, **{"m1m2_z": 1})),
                            ("+PPI", dict(base_facs, **{"ppi_z": 1})),
                            ("+两者", dict(base_facs, **{"m1m2_z": 1, "ppi_z": 1}))]:
            w = _icir_w(df, facs)
            zdf = pd.DataFrame({f: _expanding_z(df[f] * d) for f, d in facs.items()})
            avail = [f for f in facs if f in w and zdf[f].notna().iloc[-1]]
            s = sum(zdf[f] * w[f] for f in avail) / sum(w[f] for f in avail)
            e126 = _oos_pred_eval(s, df["fwd_126"])
            e252 = _oos_pred_eval(s, df["fwd_252"])
            rows.append({"instrument": code, "model": label,
                         "corr126": e126["corr"], "brier126": e126["brier"],
                         "corr252": e252["corr"], "brier252": e252["brier"],
                         "weights": {k: round(v, 2) for k, v in w.items()}})
    return pd.DataFrame(rows)
