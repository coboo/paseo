"""双动量 GEM 信号层(设计文档第十节,2026-08-25 定稿)。

规则:每月末比较 标普500(×usdcny 折人民币) 与 沪深300 的过去 12 个月回报选强者
(相对动量,平手取沪深300);胜者回报跑不赢中债 3M 复利基准则转债券防御腿(绝对动量)。
锚点 = A股日历每月最后交易日,执行 = 次月首个交易日开盘(严禁未来函数)。

信号中间面板不落盘;月度信号表落 derived/signals/(AGENTS.md 规则 4/5 对 derived 的约定)。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_module.storage import DERIVED_DIR, read_raw, save_derived

from .contract import BOND, HS300, SPX, StrategyConfig

SIGNALS_PATH = DERIVED_DIR / "signals" / "gem_cn_monthly.parquet"

# 首个信号月:yield_3m(2006-03 起)+ 12M 完整回望与债券腿(2007-01 起)双约束下,
# 回望窗完整且防御腿可持有的首个完整信号月(设计文档第十节锚点预期表同口径)
SIGNAL_START = pd.Timestamp("2008-01-31")

# 执行层 ETF 映射(信号-执行分离:信号用指数,执行用 ETF qfq)
ETF_MAP = {SPX: "513500", HS300: "510310", BOND: "511260"}


def _source_dates() -> dict[str, pd.Timestamp]:
    """各数据源最后日期(信号新鲜度截断用,防未来日历锚点取到陈旧价)。"""
    out = {k: read_raw(rel)["date"].max() for k, rel in {
        "spx": "index_global/spx_inx.parquet",
        "hs300": "index_daily/index_000300.parquet",
        "usdcny": "fx/usdcny.parquet",
        "rates": "rates/cn10y.parquet",
    }.items()}
    bond = pd.read_parquet(DERIVED_DIR / "aligned" / "bond_leg_spliced_511260.parquet")
    out["bond_leg"] = bond["date"].max()
    return out


def month_end_anchors(cfg: StrategyConfig = StrategyConfig()) -> pd.DatetimeIndex:
    """A股市历每月最后交易日锚点;有效性 = anchor ≤ min(各源最后日期, as_of)。"""
    cal = read_raw("calendar.parquet")["date"]
    if cfg.as_of is not None:
        cal = cal[cal <= pd.Timestamp(cfg.as_of)]
    anchors = cal.groupby(cal.dt.to_period("M")).max()
    last = min(_source_dates().values())
    if cfg.as_of is not None:
        last = min(last, pd.Timestamp(cfg.as_of))
    return pd.DatetimeIndex(anchors[anchors <= last])


def build_index_panel(cfg: StrategyConfig = StrategyConfig()) -> pd.DataFrame:
    """日频中间面板(中间量同结构保留,不落盘):date, spx, fx, spx_cny, hs300, rf_3m。"""
    spx = read_raw("index_global/spx_inx.parquet")[["date", "close"]].rename(columns={"close": "spx"})
    fx = read_raw("fx/usdcny.parquet")[["date", "close"]].rename(columns={"close": "fx"})
    hs = read_raw("index_daily/index_000300.parquet")[["date", "close"]].rename(columns={"close": "hs300"})
    rf = read_raw("rates/cn10y.parquet")[["date", cfg.rf_col]].rename(columns={cfg.rf_col: "rf_3m"})
    df = spx.merge(fx, on="date", how="outer").merge(hs, on="date", how="outer") \
            .merge(rf, on="date", how="outer").sort_values("date").reset_index(drop=True)
    if cfg.as_of is not None:
        df = df[df["date"] <= pd.Timestamp(cfg.as_of)]
    # 折人民币:汇率在美股交易日缺失时前向填充(假日错位 ≤1 日,口径见设计文档第十节)
    df["fx"] = df["fx"].ffill()
    df["spx_cny"] = df["spx"] * df["fx"]
    return df


def _asof(series: pd.Series, d: pd.Timestamp) -> float:
    """取 d 日或之前最近一个有效值(向后看,无前视)。"""
    s = series.dropna()
    s = s[s.index <= d]
    return float(s.iloc[-1]) if len(s) else float("nan")


def _rf_compound(rf: pd.Series, start: pd.Timestamp, end: pd.Timestamp,
                 min_days: int | None = None) -> float:
    """3M 日利率在 (start, end] 窗口 ACT/365 复利。

    min_days 默认按窗口长度自适应(约 20 个中债工作日/月,容忍假日),
    样本不足返回 NaN——不完整的利率窗口会扭曲绝对动量基准。"""
    if min_days is None:
        months = max(1, round((end - start).days / 30.44))
        min_days = max(60, 20 * months)
    seg = rf[(rf.index > start) & (rf.index <= end)].dropna()
    if len(seg) < min_days:
        return float("nan")
    return float((1.0 + seg / 100.0 / 365.0).prod() - 1.0)


def compute_gem_signals(cfg: StrategyConfig = StrategyConfig()) -> pd.DataFrame:
    """月度信号表(= derived/signals/ 落盘 schema)。"""
    panel = build_index_panel(cfg).set_index("date")
    spx_cny, hs, rf = panel["spx_cny"], panel["hs300"], panel["rf_3m"]
    lb = pd.DateOffset(months=cfg.lookback_months)

    rows = []
    for anchor in month_end_anchors(cfg):
        if anchor < SIGNAL_START:
            continue  # 12M 回望窗不完整(设计文档第十节,首个信号 = 2008-01 月末)
        start = anchor - lb
        ret_spx = _asof(spx_cny, anchor) / _asof(spx_cny, start) - 1.0
        ret_hs = _asof(hs, anchor) / _asof(hs, start) - 1.0
        rf_12m = _rf_compound(rf, start, anchor)
        if pd.isna(ret_spx) or pd.isna(ret_hs) or pd.isna(rf_12m):
            continue  # 回望窗数据不足(2008-01 前无 yield_3m/bond_leg 历史)
        # 相对动量:胜者取大;平手取沪深300(本土资产)
        winner, winner_ret = (HS300, ret_hs) if ret_hs >= ret_spx else (SPX, ret_spx)
        position = winner if winner_ret > rf_12m else BOND
        rows.append({
            "date": anchor,
            "ret_spx_cny_12m": ret_spx,
            "ret_hs300_12m": ret_hs,
            "rf_12m": rf_12m,
            "winner": winner,
            "winner_ret_12m": winner_ret,
            "abs_excess": winner_ret - rf_12m,
            "position": position,
        })

    sig = pd.DataFrame(rows)
    if sig.empty:
        return sig
    # 执行日 = 锚点的次一交易日(=次月首个交易日);锚点已是最末有效月时为 NaT(信号未执行)
    cal = pd.DatetimeIndex(sorted(set(read_raw("calendar.parquet")["date"])))
    pos = cal.searchsorted(sig["date"].values, side="right")
    sig["exec_date"] = pd.NaT
    has_next = pos < len(cal)
    sig.loc[has_next, "exec_date"] = cal[pos[has_next]]
    # 溢价门控列(默认透传,qdii_filter.apply_premium_gate 在执行层改写)
    sig["etf_target"] = sig["position"].map(ETF_MAP)
    sig["premium_513500"] = float("nan")
    sig["blocked_by_premium"] = False
    return sig.reset_index(drop=True)


def save_signals(sig: pd.DataFrame) -> Path:
    """信号表落盘 derived/signals/(全量覆盖)。返回路径。"""
    return save_derived(sig, "signals/gem_cn_monthly.parquet")
