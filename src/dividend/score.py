"""合成打分模型 + 历史相似状态盈利概率（dividend-research score_model.py /
score_valuation_only.py 合并迁移版）。

双口径：
- full：含动量版（ey_spread+−PE+−mom+dv_pct/erp_pct）回答"赢面"
- valuation：纯估值版（去动量）回答"贵贱"

纪律（HANDOFF §5.2，全部冻结不可改）：
- 特征：因子 expanding z-score（min 504 日，159545 用 126）
- 权重：各因子 126 日滚动 ICIR（年化）绝对值归一化，仅用 ≤2023 样本内估计，永久冻结
  （注意：权重估计保留原研究实现——样本内全样本秩变换 + 滚动相关——以保证冻结权重
  一个数都不变；被修复的只有消费侧分位数因子 pct_rank 的前视）
- 概率：相似状态（|Δz|≤0.5，最少20样本）的历史频率；不足 20 退化取末 500 行，
  并在产物中打 degraded 标记（159545 概率"不可外推"必须落在数据里）
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

INSAMPLE_END = "2023-12-31"

# 含动量版因子（方向已调为正=看多），冻结
MODELS = {
    "H30269": {"ey_spread": 1, "pe_ttm": -1, "mom_252": -1, "dv_pct": 1, "erp_pct": 1},
    "930955": {"ey_spread": 1, "pe_ttm": -1, "mom_252": -1, "dv_pct": 1, "erp_pct": 1},
    "515450": {"dv_pct": 1, "erp_pct": 1, "mom_126": -1},
    "159545": {"dv": 1, "erp": 1, "mom_126": -1},
}
# 纯估值版（去动量），冻结
VAL_MODELS = {
    "H30269": {"ey_spread": 1, "pe_ttm": -1, "dv_pct": 1, "erp_pct": 1},
    "930955": {"ey_spread": 1, "pe_ttm": -1, "dv_pct": 1, "erp_pct": 1},
    "515450": {"dv_pct": 1, "erp_pct": 1},
    "159545": {"dv": 1, "erp": 1},
}
MINP = {"H30269": 504, "930955": 504, "515450": 504, "159545": 126}

INSTRUMENTS = list(MODELS)


def expanding_z(s: pd.Series, min_periods: int) -> pd.Series:
    mu = s.expanding(min_periods).mean()
    sd = s.expanding(min_periods).std()
    return (s - mu) / sd


def icir_weights(df: pd.DataFrame, factors: dict[str, int], h: int = 126, win: int = 504) -> dict[str, float]:
    """样本内估计各因子126日滚动ICIR(ann)作权重（冻结实现，勿改）。"""
    w = {}
    for f, d in factors.items():
        sub = pd.DataFrame({"x": df[f] * d, "y": df[f"fwd_{h}"]}).dropna()
        sub = sub.loc[:INSAMPLE_END]
        rx, ry = sub["x"].rank(), sub["y"].rank()
        ic = rx.rolling(win).corr(ry).dropna()
        if len(ic) < 100:
            continue
        v = abs(ic.mean() / ic.std()) * np.sqrt(252 / h)
        w[f] = max(v, 0.0)
    tot = sum(w.values())
    return {k: v / tot for k, v in w.items()} if tot else {k: 1 / len(factors) for k in factors}


def prob_by_state(z: pd.Series, fwd: pd.Series, band: float = 0.5,
                  hist_days: int | None = None) -> dict:
    """当前z附近(±band)的历史状态: 正收益频率与分位。

    退化分支：相似状态<20 时取末 500 行，打 degraded 标记。
    不可外推标记：degraded、相似状态样本偏少(<60) 或标的可用历史过短(<5年，
    约 1260 交易日) 任一成立即标 non_extrapolatable——159545 概率"不可外推"
    必须落在产物数据里，不能只写在 HANDOFF 文字中。
    """
    cur = z.iloc[-1]
    hist = pd.DataFrame({"z": z, "fwd": fwd}).dropna()
    near = hist[abs(hist["z"] - cur) <= band]
    degraded = len(near) < 20
    if degraded:
        warnings.warn(
            f"prob_by_state 退化：相似状态样本 {len(near)}<20，取末 500 行，概率不可外推",
            stacklevel=2)
        near = hist.iloc[-500:]
    non_extra = degraded or len(near) < 60 or (hist_days is not None and hist_days < 1260)
    return {
        "state_n": len(near),
        "degraded": degraded,
        "non_extrapolatable": non_extra,
        "p_pos": (near["fwd"] > 0).mean(),
        "fwd_mean": near["fwd"].mean(), "fwd_median": near["fwd"].median(),
        "fwd_p25": near["fwd"].quantile(0.25), "fwd_p75": near["fwd"].quantile(0.75),
    }


def compute_scores(panels: dict[str, pd.DataFrame],
                   models: dict[str, dict[str, int]] | None = None,
                   minp: dict[str, int] | None = None) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """单口径打分。返回 (打分序列 dict, 当前读数汇总表)。

    打分序列：score_z / score_pct / fwd_126 / fwd_252（与原 score_*.csv 同构）。
    汇总表列：instrument / weights / score_z / score_pctile / P(fwd126>0) / P(fwd252>0) /
    fwd126_mean / fwd126_median / fwd126_p25 / fwd126_p75 / state_n / state_degraded。
    """
    models = MODELS if models is None else models
    minp = MINP if minp is None else minp
    scores: dict[str, pd.DataFrame] = {}
    summary_rows = []
    for name, factors in models.items():
        df = panels[name]
        zdf = pd.DataFrame({f: expanding_z(df[f] * d, minp[name]) for f, d in factors.items()})
        w = icir_weights(df, factors)
        # 打分: 权重×z 求和, 缺因子按权重重分配
        avail = [f for f in factors if zdf[f].notna().iloc[-1] and f in w]
        wsum = sum(w[f] for f in avail)
        score = sum(zdf[f] * (w[f] / wsum) for f in avail)
        score_pct = score.rank(pct=True)  # 当前值在全历史中的分位

        out = pd.DataFrame({"score_z": score, "score_pct": score_pct})
        for h in (126, 252):
            out[f"fwd_{h}"] = df[f"fwd_{h}"]
        scores[name] = out

        p126 = prob_by_state(score, df["fwd_126"], hist_days=len(df))
        p252 = prob_by_state(score, df["fwd_252"], hist_days=len(df))
        summary_rows.append({
            "instrument": name, "weights": {k: round(v, 3) for k, v in w.items()},
            "score_z": round(score.iloc[-1], 2), "score_pctile": round(score_pct.iloc[-1], 3),
            "P(fwd126>0)": round(p126["p_pos"], 3), "P(fwd252>0)": round(p252["p_pos"], 3),
            "fwd126_mean": round(p126["fwd_mean"], 4), "fwd126_median": round(p126["fwd_median"], 4),
            "fwd126_p25": round(p126["fwd_p25"], 4), "fwd126_p75": round(p126["fwd_p75"], 4),
            "state_n": p126["state_n"],
            "state_degraded": bool(p126["degraded"] or p252["degraded"]),
            "non_extrapolatable": bool(p126["non_extrapolatable"] or p252["non_extrapolatable"]),
        })
    return scores, pd.DataFrame(summary_rows)


def score_full(panels: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """含动量版打分（回答"赢面"）。"""
    return compute_scores(panels, MODELS, MINP)


def score_valuation_only(panels: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """纯估值版打分（去动量，回答"贵贱"）。"""
    return compute_scores(panels, VAL_MODELS, MINP)
