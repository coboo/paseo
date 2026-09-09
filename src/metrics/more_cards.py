"""四张数据就位的估值/状态卡片(设计文档第六节 12 卡片清单)。

PE 分位(POSITIVE:高 PE=贵=红)、250 日均线趋势温度(POSITIVE:过度偏离=过热=红)、
10Y 国债水平(POSITIVE:利率高=股承压=红)、QVIX 情绪(INVERSE:高恐慌=逆向机会=绿)。
全部复刻 erp.py 模式走 σ 引擎;中间量同结构保留、不落盘。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw

from .contract import INVERSE, MetricResult, POSITIVE, RATING_LEVELS, direction_sign, rating_from_z
from .sigma import SigmaStats, compute_sigma_stats, monthly_sample

WINDOW_LABELS: dict[int | None, str] = {10: "近10年", None: "全历史"}


def _card(name: str, daily: pd.DataFrame, col: str, direction: str,
          unit: str, fmt: str, tier_desc: dict[int, str],
          window_years: int | None = 10,
          extra_note: str = "") -> MetricResult:
    """卡片模板:日频中间量 → 月频 σ → 五档。"""
    monthly = monthly_sample(daily.set_index("date")[col])
    stats: SigmaStats = compute_sigma_stats(monthly, direction_sign(direction), window_years)
    rating = rating_from_z(stats.val_z)
    row = daily.iloc[-1]
    desc = (
        f"{fmt.format(cur=row[col])}。按{WINDOW_LABELS[window_years]}口径({stats.start} 起 "
        f"{stats.n} 个月,均值 {stats.mean:.2f}、σ {stats.sd:.2f}),当前偏离均值 "
        f"{stats.val_z:+.2f}σ,评级「{RATING_LEVELS[rating]['label']}」——{tier_desc[rating]}。"
        + extra_note
    )
    return MetricResult(
        name=name, current=float(row[col]), unit=unit, sigma=stats.val_z,
        rating=rating, color=RATING_LEVELS[rating]["color"], direction=direction,
        window=WINDOW_LABELS[window_years], series=monthly, stats=stats,
        desc=desc, updated=f"{row['date']:%Y-%m-%d}",
    )


# ── PE 分位(沪深300) ──────────────────────────────────────────
_PE_DESC = {
    1: "PE 处于历史极低位,历史上对应长期布局区域", 2: "PE 偏低于历史常态",
    3: "PE 处于常态区间", 4: "PE 偏高于历史常态", 5: "PE 处于历史极高位,风险区",
}


def pe_daily() -> pd.DataFrame:
    return read_raw("valuation/pe_000300.parquet")[["date", "pe_ttm"]].dropna()


def pe_000300(window_years: int | None = 10) -> MetricResult:
    """沪深300 PE(TTM)。高 PE = 贵(POSITIVE)。"""
    return _card("沪深300 PE(TTM)", pe_daily(), "pe_ttm", POSITIVE, "倍",
                 "沪深300 滚动市盈率 {cur:.1f} 倍", _PE_DESC, window_years,
                 "(口径:乐咕 pe_ttm,2005-04 起)")


# ── 250 日均线趋势温度 ────────────────────────────────────────
_MA_DESC = {
    1: "价格深度低于年线,超卖区", 2: "价格低于年线",
    3: "价格贴近年线,趋势中性", 4: "价格高于年线偏多", 5: "价格大幅偏离年线,过热区",
}


def ma250_daily() -> pd.DataFrame:
    """日频:沪深300 收盘、250 日均线、偏离 %。"""
    hs = read_raw("index_daily/index_000300.parquet")[["date", "close"]]
    hs["sma250"] = hs["close"].rolling(250).mean()
    df = hs.dropna(subset=["sma250"]).reset_index(drop=True)
    df["dev"] = (df["close"] / df["sma250"] - 1.0) * 100.0
    return df


def ma250_dev(window_years: int | None = 10) -> MetricResult:
    """价格偏离 250 日均线(%)。过度偏离 = 过热(POSITIVE)。"""
    return _card("沪深300 偏离 250 日均线", ma250_daily(), "dev", POSITIVE, "%",
                 "收盘价高于 250 日均线 {cur:+.1f}%", _MA_DESC, window_years)


# ── 10Y 国债水平 ─────────────────────────────────────────────
_R_DESC = {
    1: "利率处于历史极低位(宽松极端)", 2: "利率偏低",
    3: "利率处于常态区间", 4: "利率偏高", 5: "利率处于历史极高位(紧缩极端,股承压)",
}


def rates_daily() -> pd.DataFrame:
    return read_raw("rates/cn10y.parquet")[["date", "yield_10y"]].dropna()


def rates_10y(window_years: int | None = 10) -> MetricResult:
    """10Y 国债收益率水平。利率高 = 股承压(POSITIVE)。"""
    return _card("10Y 国债收益率", rates_daily(), "yield_10y", POSITIVE, "%",
                 "10Y 国债收益率 {cur:.2f}%", _R_DESC, window_years)


# ── QVIX 情绪(逆向) ─────────────────────────────────────────
_Q_DESC = {
    1: "恐慌情绪处于历史极高位,逆向视角的布局区", 2: "恐慌情绪偏高",
    3: "情绪处于常态区间", 4: "情绪偏平静", 5: "情绪极度平静,逆向视角的警惕区(常伴顶部)",
}


def qvix_daily() -> pd.DataFrame:
    return read_raw("qvix/qvix_50etf.parquet")[["date", "close"]].rename(
        columns={"close": "qvix"}).dropna()


def qvix_50etf(window_years: int | None = 10) -> MetricResult:
    """50ETF QVIX。高恐慌 = 逆向机会(INVERSE:高值→绿)。"""
    return _card("QVIX 情绪(50ETF,逆向)", qvix_daily(), "qvix", INVERSE, "点",
                 "50ETF 期权隐含波动率 {cur:.1f} 点", _Q_DESC, window_years)
