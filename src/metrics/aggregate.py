"""σ 加权综合分(设计文档第六节:综合 | 股债性价比总分 Aggregate)。

11 张卡片的估值z **等权平均**,再走 rating_from_z 五档。诚实声明:ERP/PE/股息差
强相关(同源估值),综合分目前偏"股债估值+情绪"画像;等权是当前唯一无先验的选择。
历史序列 = 各卡 expanding 估值z(无前视)按月对齐后等权平均,任一卡缺失则该月不输出。

EPU(官方数据停滞于 2023-11)与 Sahm(失业率 2018 起样本过短)**不参与**综合分:
前者会使序列末端整体缺失,后者会把有效历史起点拖到 2019——两卡仅独立展示。
"""
from __future__ import annotations

import pandas as pd

from .buffett import buffett_indicator, buffett_monthly
from .contract import INVERSE, MetricResult, RATING_LEVELS, direction_sign, rating_from_z
from .credit_spread import credit_spread, credit_spread_daily
from .curve_10y3m import curve_10y3m, curve_daily
from .dividend_spread import dividend_spread, dividend_spread_daily
from .erp import erp_000300, erp_daily
from .margin_debt import margin_debt, margin_debt_monthly
from .more_cards import ma250_dev, ma250_daily, pe_000300, pe_daily, qvix_50etf, qvix_daily, rates_10y, rates_daily
from .pmi_momentum import pmi_momentum, pmi_momentum_monthly
from .sigma import SigmaStats, expanding_val_z, monthly_sample

# 参与综合的卡片:(key, 主函数, 日频函数, 列名, 方向)
# 日频函数列:月频卡片(margin/buffett/pmi)返回月频表,monthly_sample 恒等通过
CARDS: list[tuple[str, object, object, str, str]] = [
    ("erp", erp_000300, erp_daily, "erp", "inverse"),
    ("curve", curve_10y3m, curve_daily, "spread", "inverse"),
    ("divspread", dividend_spread, dividend_spread_daily, "spread", "inverse"),
    ("pe", pe_000300, pe_daily, "pe_ttm", "positive"),
    ("ma250", ma250_dev, ma250_daily, "dev", "positive"),
    ("rates10y", rates_10y, rates_daily, "yield_10y", "positive"),
    ("qvix", qvix_50etf, qvix_daily, "qvix", "inverse"),
    ("margin", margin_debt, margin_debt_monthly, "ratio", "positive"),
    ("buffett", buffett_indicator, buffett_monthly, "mv_gdp", "positive"),
    ("credit", credit_spread, credit_spread_daily, "spread", "inverse"),
    ("pmi", pmi_momentum, pmi_momentum_monthly, "mom", "inverse"),
]


def composite_series(window_years: int | None = 10) -> pd.Series:
    """综合分历史月频序列(各卡 expanding 估值z 等权平均,无前视)。"""
    cols = {}
    for key, _, daily_fn, col, direction in CARDS:
        df = daily_fn()
        monthly = monthly_sample(df.set_index("date")[col])
        cols[key] = expanding_val_z(monthly, direction_sign(direction))
    wide = pd.DataFrame(cols).dropna()   # 任一卡缺失则该月不输出(口径一致性优先)
    return wide.mean(axis=1)


def composite(window_years: int | None = 10) -> MetricResult:
    """综合分主函数:当前 = 各卡当前估值z 等权平均。"""
    zs = {}
    for key, fn, _, _, _ in CARDS:
        zs[key] = fn(window_years).sigma
    s = pd.Series(zs)
    val = float(s.mean())
    rating = rating_from_z(val)
    hist = composite_series(window_years)
    label = RATING_LEVELS[rating]["label"]

    desc = (
        f"11 张卡片估值z 等权平均 = {val:+.2f}σ({', '.join(f'{k} {v:+.2f}' for k, v in zs.items())})。"
        f"综合评级「{label}」——各卡偏离互相抵消时接近公允,同向偏离时放大。"
        f"(注意:ERP/PE/股息差同源强相关,综合分当前偏股债估值+情绪画像;"
        f"历史序列自 {hist.index.min():%Y-%m} 起,受最晚可用卡片约束)"
    )
    stats = SigmaStats(
        mean=float(hist.mean()), sd=float(hist.std()), n=len(hist),
        start=hist.index.min(), end=hist.index.max(),
        z_raw=float((hist.iloc[-1] - hist.mean()) / hist.std()) if hist.std() > 0 else 0.0,
        val_z=val,
        lo2=float(hist.mean() - 2 * hist.std()), lo1=float(hist.mean() - hist.std()),
        hi1=float(hist.mean() + hist.std()), hi2=float(hist.mean() + 2 * hist.std()),
    )
    return MetricResult(
        name="股债性价比综合分(11 卡等权)",
        current=val, unit="σ", sigma=val, rating=rating,
        color=RATING_LEVELS[rating]["color"], direction=INVERSE,  # 与卡片同约定:负=便宜
        window={10: "近10年", None: "全历史"}[window_years],
        series=hist, stats=stats, desc=desc,
        updated=f"{hist.index.max():%Y-%m-%d}",
    )
