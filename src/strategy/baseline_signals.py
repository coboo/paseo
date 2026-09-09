"""三基线信号层(设计文档第十一节):Faber 10月均线 / FED 分位 / GTAA 动量轮动。

统一输出:月度信号表(含中间量,落盘 derived/signals/)+ 执行日权重表(喂
engine_weights.run_monthly_weights)。锚点 = A 股日历月末,执行 = 次月首个交易日开盘。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw, save_derived

from .contract import StrategyConfig
from .gem_signal import _asof, _rf_compound
from .panels import ASSET_SPECS, _series, build_signal_panel, month_end_anchor_dates

# 各基线资产池(设计文档第十一节定稿)
FABER_ASSETS = ["hs300", "spx", "bond", "gold"]          # 四资产版(REITs 缺,已声明)
GTAA_ASSETS = ["hs300", "csi500", "hdlow", "spx", "gold", "bond"]


def _exec_dates(anchors: pd.DatetimeIndex) -> pd.Series:
    """锚点 → 次一交易日(calendar)。末锚点无次日则丢弃。"""
    cal = pd.DatetimeIndex(sorted(set(read_raw("calendar.parquet")["date"])))
    pos = cal.searchsorted(anchors.values, side="right")
    ok = pos < len(cal)
    return pd.Series(cal[pos[ok]], index=anchors[ok])


def _attach_exec(sig: pd.DataFrame) -> pd.DataFrame:
    """给信号表附执行日列(末锚点无次日的行丢弃)。"""
    ed = _exec_dates(pd.DatetimeIndex(sig["date"]))
    out = sig[sig["date"].isin(ed.index)].reset_index(drop=True)
    out["exec_date"] = out["date"].map(ed)
    return out


def _month_close(key: str) -> pd.Series:
    """资产收盘序列(信号用 close,口径与 GEM 一致;月末值由 _asof 取)。"""
    return _series(key, price_col="close")


# ================================================================ Faber
def faber_signals(sma_months: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Faber:月末收盘 > N 月均线 → 持有,否则现金;通过者等权。

    返回 (月度信号表, 执行日权重表[资产+cash 列])。
    """
    lb = pd.DateOffset(months=sma_months)
    anchors = month_end_anchor_dates()
    closes = {k: _month_close(k) for k in FABER_ASSETS}

    rows = []
    for a in anchors:
        start = a - lb
        vals, smas, above = {}, {}, {}
        for k, s in closes.items():
            cur = _asof(s, a)
            past = s[(s.index > start) & (s.index <= a)]
            if pd.isna(cur) or len(past) < _sma_min_days(sma_months):
                vals[k] = float("nan")
                continue
            sma = float(past.mean())
            vals[k] = cur
            smas[k] = sma
            above[k] = cur > sma
        if any(pd.isna(v) for v in vals.values()):
            continue  # 任一资产均线窗不完整(2008-11 前)不出信号
        n = sum(above.values())
        row = {"date": a}
        for k in FABER_ASSETS:
            row[f"{k}_close"] = vals[k]
            row[f"{k}_sma"] = smas[k]                      # 中间量保留(策略页展示距均线距离)
            row[f"{k}_above"] = above[k]
        row["n_above"] = n
        rows.append(row)

    sig = pd.DataFrame(rows)
    if sig.empty:
        return sig, pd.DataFrame()
    sig = _attach_exec(sig)

    cols = FABER_ASSETS + ["cash"]
    weights = []
    for _, r in sig.iterrows():
        w = {c: 0.0 for c in cols}
        n = r["n_above"]
        if n > 0:
            for k in FABER_ASSETS:
                if r[f"{k}_above"]:
                    w[k] = 1.0 / n
        else:
            w["cash"] = 1.0
        weights.append(w)
    weights = pd.DataFrame(weights, index=sig["exec_date"].values, columns=cols)
    return sig.reset_index(drop=True), weights


def _sma_min_days(months: int) -> int:
    """均线窗最少样本数(约 19 个工作日/月,容忍假日)。"""
    return max(20, 19 * months)


# ================================================================ FED 分位
def fed_signals(hi: float = 0.70, lo: float = 0.30, min_months: int = 36
                ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """FED 分位:ERP expanding 分位(无前视)≥hi → 股;≤lo → 债;中间维持。

    返回 (月度信号表, 执行日权重表[hs300/bond 列])。
    """
    from metrics.erp import erp_daily

    erp = erp_daily().set_index("date")["erp"].sort_index()
    anchors = month_end_anchor_dates()

    rows, state = [], None   # state: None=未入场 / "hs300" / "bond"
    for a in anchors:
        hist = erp[erp.index <= a].dropna()
        monthly = hist.resample("ME").last().dropna()   # 月频采样(σ 引擎同纪律,防日频自相关虚增)
        if len(monthly) < min_months:
            continue
        pct = float((monthly.iloc[-1] >= monthly).mean())   # expanding 分位(含当月)
        if pct >= hi:
            state = "hs300"
        elif pct <= lo:
            state = "bond"
        if state is None:
            continue
        rows.append({"date": a, "erp": float(hist.iloc[-1]), "erp_pct": pct,
                     "state": state, "n_months": len(monthly)})

    sig = pd.DataFrame(rows)
    if sig.empty:
        return sig, pd.DataFrame()
    sig = _attach_exec(sig)

    weights = pd.DataFrame(
        [{"hs300": 1.0 if s == "hs300" else 0.0, "bond": 1.0 if s == "bond" else 0.0,
          "cash": 0.0} for s in sig["state"]],
        index=sig["exec_date"].values, columns=["hs300", "bond", "cash"])
    return sig.reset_index(drop=True), weights


# ================================================================ GTAA
def gtaa_signals(lookback_months: int = 12, top_n: int = 2
                 ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """GTAA:12M 总回报绝对动量过滤(> 3M 复利)→ 排名 TopN 等权;全负停泊 cash。

    返回 (月度信号表, 执行日权重表[6 资产+cash 列])。
    """
    lb = pd.DateOffset(months=lookback_months)
    anchors = month_end_anchor_dates()
    closes = {k: _month_close(k) for k in GTAA_ASSETS}
    rf = read_raw("rates/cn10y.parquet").set_index("date")["yield_3m"].astype(float)

    rows = []
    for a in anchors:
        start = a - lb
        rets = {k: _asof(s, a) / _asof(s, start) - 1.0 for k, s in closes.items()}
        rf_lb = _rf_compound(rf, start, a)
        if any(pd.isna(v) for v in rets.values()) or pd.isna(rf_lb):
            continue
        ranked = sorted(rets.items(), key=lambda kv: kv[1], reverse=True)
        passed = [(k, r) for k, r in ranked if r > rf_lb]
        rows.append({"date": a, "rf_12m": rf_lb,
                     **{f"{k}_ret": r for k, r in rets.items()},
                     "top1": ranked[0][0], "top1_ret": ranked[0][1],
                     "n_pass": len(passed),
                     "picked": [k for k, _ in passed[:top_n]]})

    sig = pd.DataFrame(rows)
    if sig.empty:
        return sig, pd.DataFrame()
    sig = _attach_exec(sig)

    cols = GTAA_ASSETS + ["cash"]
    weights = []
    for _, r in sig.iterrows():
        w = {c: 0.0 for c in cols}
        if r["n_pass"] > 0:
            for k in r["picked"]:
                w[k] = 1.0 / min(top_n, r["n_pass"])
        else:
            w["cash"] = 1.0   # 全负停泊(不参与排名,执行规范第 1 条)
        weights.append(w)
    weights = pd.DataFrame(weights, index=sig["exec_date"].values, columns=cols)
    return sig.reset_index(drop=True), weights


def save_baseline_signals(tag: str, sig: pd.DataFrame) -> object:
    return save_derived(sig, f"signals/{tag}_monthly.parquet")
