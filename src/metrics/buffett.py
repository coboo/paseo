"""巴菲特指标卡片(CMV 复刻 #1:Buffett Indicator)。

A股两市总市值 / 近四季度 GDP 之和,单位 %。分子取东财数据中心月度总市值
(2008-01 起,交易所官网无长历史,已验证并弃用);分母 GDP 季度累计值差分后
滚动四季度求和。市值相对经济规模越大 = 越贵(POSITIVE:高→红档)。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw

from .contract import POSITIVE, MetricResult, RATING_LEVELS, direction_sign, rating_from_z
from .sigma import SigmaStats, compute_sigma_stats

WINDOW_LABELS: dict[int | None, str] = {10: "近10年", None: "全历史"}

_TIER_DESC = {
    1: "总市值相对 GDP 处于历史极低位,股票资产相对经济规模异常便宜",
    2: "总市值相对 GDP 偏低",
    3: "总市值相对 GDP 处于常态区间",
    4: "总市值相对 GDP 偏高,股票相对经济规模偏贵",
    5: "总市值相对 GDP 处于历史极高位,泡沫区",
}


def buffett_monthly() -> pd.DataFrame:
    """月频巴菲特指标:date(月末), mv_gdp(总市值/近四季 GDP, %)。"""
    mv = read_raw("valuation/a_market_cap.parquet")[["date", "mv_total"]].dropna()
    gdp = read_raw("macro/gdp_quarterly.parquet")[["date", "gdp_cum"]].dropna()
    # 季度累计 → 单季值 → 滚动四季求和
    gdp = gdp.sort_values("date")
    gdp["year"] = gdp["date"].dt.year
    gdp["gdp_q"] = gdp["gdp_cum"] - gdp.groupby("year")["gdp_cum"].shift(1)
    gdp["gdp_q"] = gdp["gdp_q"].fillna(gdp["gdp_cum"])  # 一季度累计即单季
    gdp["gdp_ttm"] = gdp["gdp_q"].rolling(4).sum()
    g = gdp.dropna(subset=["gdp_ttm"])[["date", "gdp_ttm"]]
    # 月频总市值 asof 对齐到季末 GDP 日期,再按月展开
    mv_m = mv.set_index("date")["mv_total"]
    df = pd.DataFrame({"gdp_ttm": g.set_index("date")["gdp_ttm"]})
    df = df.sort_index()
    monthly = mv_m.resample("ME").last().dropna().to_frame("mv_total")
    combined = monthly.join(df, how="left").ffill()
    combined = combined.dropna(subset=["gdp_ttm"])
    combined["mv_gdp"] = combined["mv_total"] / combined["gdp_ttm"] * 100.0
    out = combined.reset_index()[["date", "mv_gdp"]]
    return out


def buffett_indicator(window_years: int | None = 10) -> MetricResult:
    """巴菲特指标主函数。window_years=None → 全历史口径。"""
    df = buffett_monthly()
    monthly = df.set_index("date")["mv_gdp"]
    direction = POSITIVE  # 市值/GDP 高 = 贵(红)
    stats: SigmaStats = compute_sigma_stats(monthly, direction_sign(direction), window_years)
    rating = rating_from_z(stats.val_z)
    row = df.iloc[-1]

    desc = (
        f"A股两市总市值相当于近四季度 GDP 之和的 {row.mv_gdp:.0f}%。按{WINDOW_LABELS[window_years]}"
        f"口径({stats.start} 起 {stats.n} 个月,均值 {stats.mean:.0f}、σ {stats.sd:.0f}),"
        f"当前偏离均值 {stats.val_z:+.2f}σ,评级「{RATING_LEVELS[rating]['label']}」"
        f"——{_TIER_DESC[rating]}。(口径:CMV Buffett Indicator,总市值 2008-01 起)"
    )
    return MetricResult(
        name="巴菲特指标(总市值/GDP)",
        current=float(row["mv_gdp"]),
        unit="%",
        sigma=stats.val_z,
        rating=rating,
        color=RATING_LEVELS[rating]["color"],
        direction=direction,
        window=WINDOW_LABELS[window_years],
        series=monthly,
        stats=stats,
        desc=desc,
        updated=f"{row['date']:%Y-%m-%d}",
    )
