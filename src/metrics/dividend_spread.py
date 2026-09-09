"""股息差卡片(设计文档第六节:股息率 − 10Y 国债)。

口径:全 A 股息率(乐咕长历史)减 10Y 国债收益率——与 ERP 同构的股债性价比视角,
高值 = 股息相对债券有吸引力(INVERSE:高→绿=便宜)。沪深300 股息率源仅近月快照
(csindex 积累中),以全 A 口径替代并在此声明。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw

from .contract import INVERSE, MetricResult, RATING_LEVELS, direction_sign, rating_from_z
from .sigma import SigmaStats, compute_sigma_stats, monthly_sample

WINDOW_LABELS: dict[int | None, str] = {10: "近10年", None: "全历史"}

_TIER_DESC = {
    1: "股息率大幅高于债券收益率,股票分红维度异常便宜",
    2: "股息率相对债券偏有吸引力",
    3: "股息与债券收益大体均衡",
    4: "股息率相对债券偏没有吸引力",
    5: "股息率大幅低于债券收益率,分红维度昂贵",
}


def dividend_spread_daily() -> pd.DataFrame:
    """日频股息差及中间量:date, div_yield, yield_10y, spread(百分点)。"""
    div = read_raw("valuation/dividend_all_a.parquet")[["date", "div_yield"]]
    rates = read_raw("rates/cn10y.parquet")[["date", "yield_10y"]]
    df = div.merge(rates, on="date").dropna().sort_values("date").reset_index(drop=True)
    df["spread"] = df["div_yield"] - df["yield_10y"]
    return df


def dividend_spread(window_years: int | None = 10) -> MetricResult:
    """股息差主函数(全 A 口径)。window_years=None → 全历史。"""
    df = dividend_spread_daily()
    monthly = monthly_sample(df.set_index("date")["spread"])
    direction = INVERSE  # 股息差高 = 股票分红维度便宜(绿)
    stats: SigmaStats = compute_sigma_stats(monthly, direction_sign(direction), window_years)
    rating = rating_from_z(stats.val_z)
    row = df.iloc[-1]

    desc = (
        f"全 A 股息率({row.div_yield:.2f}%)减 10Y 国债收益率({row.yield_10y:.2f}%),股息差 "
        f"{row.spread:+.2f} 个百分点。按{WINDOW_LABELS[window_years]}口径({stats.start} 起 "
        f"{stats.n} 个月,均值 {stats.mean:.2f}、σ {stats.sd:.2f}),当前偏离均值 "
        f"{stats.val_z:+.2f}σ,评级「{RATING_LEVELS[rating]['label']}」——{_TIER_DESC[rating]}。"
        f"(口径:全 A 股息率,300 股息率长历史源缺失)"
    )
    return MetricResult(
        name="股息率 − 10Y 国债(全A)",
        current=float(row["spread"]),
        unit="个百分点",
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
