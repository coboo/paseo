"""预测能力样本外检验（dividend-research validate_predictions.py /
validate_logistic.py 合并迁移版）。

validate_predictions：冻结模型逐周模拟历史预测（预测日 t 只用 t-h 前已兑现标签，
无未来函数），对比朴素 expanding 均值基准；评估相关/MAE/偏差/方向命中/分档校准。
validate_logistic：① 降重叠抽样的相关显著性（n_eff = n × 21/h）；② Logistic 概率
模型 vs 频率统计对照（训练 ≤2023，评估 2024+；Brier/LogLoss/分档校准）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

NAMES = {"H30269": "红利低波(563020)", "930955": "红利低波100(159307)",
         "515450": "标普红利低波50(515450)", "159545": "恒生红利低波(159545)"}
HOR = {21: "1月", 63: "1季", 252: "1年"}
OOS_START = "2024-01-01"
INSAMPLE_END = "2023-12-31"
FEATS = {"H30269": ["ey_spread", "pe_ttm", "mom_252", "dv_pct", "erp_pct"],
         "930955": ["ey_spread", "pe_ttm", "mom_252", "dv_pct", "erp_pct"],
         "515450": ["dv_pct", "erp_pct", "mom_126"],
         "159545": ["dv", "erp", "mom_126"]}


# ---------------------------------------------------------------- 预测回测
def backtest_pred(z: pd.Series, fwd: pd.Series, h: int, band: float = 0.5) -> pd.DataFrame:
    """逐周（每 5 交易日）模拟历史预测：预测 = t-h 前已兑现历史中 |z-z_t|≤band 的 fwd_h 均值。"""
    idx = z.dropna().index
    idx = idx[idx >= OOS_START]
    idx = idx[::5]
    recs = []
    for t in idx:
        know = fwd.loc[:t].index[fwd.loc[:t].index <= t - pd.Timedelta(days=int(h * 1.6))]
        hist = pd.DataFrame({"z": z, "f": fwd}).loc[know].dropna()
        if len(hist) < 300:
            continue
        near = hist[abs(hist["z"] - z.loc[t]) <= band]
        if len(near) < 20:
            near = hist.iloc[-500:]
        pred = near["f"].mean()
        naive = hist["f"].mean()
        recs.append({"date": t, "pred": pred, "naive": naive, "real": fwd.loc[t]})
    if not recs:
        return pd.DataFrame(columns=["pred", "naive", "real"])
    return pd.DataFrame(recs).set_index("date").dropna()


def eval_pred(r: pd.DataFrame) -> dict:
    """预测 vs 实现：Spearman 相关 / MAE / 相对朴素基准的改善 / 偏差 / 方向命中 / 校准斜率。"""
    corr = r["pred"].corr(r["real"], method="spearman")
    mae = (r["pred"] - r["real"]).abs().mean()
    bias = r["pred"].mean() - r["real"].mean()
    naive_mae = (r["naive"] - r["real"]).abs().mean()
    hit = ((r["pred"] > 0) == (r["real"] > 0)).mean()
    try:
        q = pd.qcut(r["pred"], 5, labels=False, duplicates="drop")
        cal = r.groupby(q).apply(
            lambda g: pd.Series({"pred": g["pred"].mean(), "real": g["real"].mean()}),
            include_groups=False)
        slope = np.polyfit(cal["pred"], cal["real"], 1)[0] if len(cal) >= 3 else np.nan
    except Exception:  # noqa: BLE001 - 分档失败仅影响诊断列
        slope = np.nan
    return {"corr": corr, "MAE": mae, "naive_MAE": naive_mae, "bias": bias,
            "sign_hit": hit, "calib_slope": slope, "n": len(r)}


def validate_predictions(panels: dict[str, pd.DataFrame],
                         scores: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """冻结模型样本外预测检验汇总表（等价 prediction_validation.csv）。"""
    rows = []
    for code in NAMES:
        z = scores[code]["score_z"]
        for h, lab in HOR.items():
            r = backtest_pred(z, panels[code][f"fwd_{h}"], h)
            if len(r) < 15:
                continue
            m = eval_pred(r)
            rows.append({"标的": NAMES[code], "期限": lab,
                         **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()}})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 显著性 + logistic 对照
def significance_table(panels: dict[str, pd.DataFrame],
                       scores: dict[str, pd.DataFrame],
                       horizons: dict[int, str] | None = None) -> pd.DataFrame:
    """重叠调整后的相关显著性（全样本 Spearman → 近似 t 检验，每 h/21 降重叠取点）。"""
    horizons = {63: "1季", 126: "半年", 252: "1年"} if horizons is None else horizons
    rows = []
    for code in NAMES:
        for h, lab in horizons.items():
            sub = pd.DataFrame({"z": scores[code]["score_z"],
                                "y": panels[code][f"fwd_{h}"]}).dropna()
            step = max(int(h / 21), 1)
            sub_s = sub.iloc[::step]
            r = sub_s["z"].corr(sub_s["y"], method="spearman")
            n_eff = len(sub_s)
            t = r * np.sqrt((n_eff - 2) / max(1e-9, 1 - r ** 2))
            p = 2 * (1 - norm.cdf(abs(t)))
            rows.append({"标的": NAMES[code], "期限": lab, "r": round(r, 3),
                         "n_eff": n_eff, "t": round(t, 2),
                         "p": ("<0.01" if p < 0.01 else f"{p:.2f}")})
    return pd.DataFrame(rows)


def _zscore_train(X: pd.DataFrame, train_mask: pd.Series) -> pd.DataFrame:
    mu = X[train_mask].mean()
    sd = X[train_mask].std().replace(0, np.nan)
    return (X - mu) / sd


def logistic_vs_freq(panels: dict[str, pd.DataFrame],
                     scores: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Logistic 概率模型 vs 频率统计对照（训练 ≤2023，评估 2024+）。

    每行：标的/期限/Brier(logistic/freq/base)/LogLoss/校准(预测→实现)/系数。
    训练期单一类别时 logistic 不可训练，记录朴素频率 Brier。
    """
    rows = []
    for code in NAMES:
        pn = panels[code]
        feats = FEATS[code]
        X = pn[feats].copy()
        for f in feats:
            X[f] = X[f] * (-1 if f.startswith("mom") or f == "pe_ttm" else 1)
        X = _zscore_train(X, X.index <= INSAMPLE_END)
        z_col = scores[code]["score_z"]
        for h, lab in {63: "1季", 126: "半年", 252: "1年"}.items():
            y = (pn[f"fwd_{h}"] > 0).astype(float)
            dfm = X.join(y.rename("y")).join(z_col.rename("z")).dropna()
            tr = dfm.index <= INSAMPLE_END
            te = dfm.index > INSAMPLE_END
            base: dict = {"标的": NAMES[code], "期限": lab}
            if te.sum() < 40:
                rows.append({**base, "note": f"OOS样本不足({te.sum()})"})
                continue
            if dfm.loc[tr, "y"].nunique() < 2:
                ptr = dfm.loc[tr, "y"].mean()
                rows.append({**base, "note": "训练期单一类别",
                             "brier_base": round(brier_score_loss(
                                 dfm.loc[te, "y"], np.full(int(te.sum()), ptr)), 3)})
                continue
            lr = LogisticRegression(max_iter=1000, C=1.0).fit(dfm.loc[tr, feats], dfm.loc[tr, "y"])
            p_log = lr.predict_proba(dfm.loc[te, feats])[:, 1]
            # 频率法: 相似状态概率作为预测
            yte, zte = dfm.loc[te, "y"].values, dfm.loc[te, "z"].values
            ztr, ytr = dfm.loc[tr, "z"].values, dfm.loc[tr, "y"].values
            freq_p = [near.mean() if len(near := ytr[np.abs(ztr - zv) <= 0.5]) >= 20 else ytr.mean()
                      for zv in zte]
            q = pd.qcut(p_log, 3, labels=False, duplicates="drop")
            cal = pd.DataFrame({"q": q, "p": p_log, "y": yte}).groupby("q").agg(
                pred=("p", "mean"), real=("y", "mean"))
            cal_s = " | ".join(f"{r.pred:.0%}→{r.real:.0%}" for r in cal.itertuples())
            rows.append({**base,
                         "brier_log": round(brier_score_loss(yte, p_log), 3),
                         "brier_freq": round(brier_score_loss(yte, freq_p), 3),
                         "brier_base": round(brier_score_loss(yte, np.full(len(yte), ytr.mean())), 3),
                         "logloss": round(log_loss(yte, p_log), 3),
                         "calib": cal_s,
                         "coef": dict(zip(feats, lr.coef_[0].round(2)))})
    return pd.DataFrame(rows)
