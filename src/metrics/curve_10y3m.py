"""收益率曲线卡片(CMV 复刻 #7:10Y−3M 国债利差)。

CMV 原版口径是 10Y−3M 利差(短端用 3 个月),初版实现误用了 1Y,本文件
修正为 3M 并保留中间量。10Y 减 3M 利差,单位百分点。曲线倒挂(负值)
历史上对应衰退/紧缩风险区,方向取 INVERSE(利差高→估值z 低→绿档=低风险;
倒挂→红档=风险区)。中间量(yield_10y/yield_3m)同结构保留、不落盘。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw

from .contract import INVERSE, MetricResult, RATING_LEVELS, direction_sign, rating_from_z
from .sigma import SigmaStats, compute_sigma_stats, monthly_sample

WINDOW_LABELS: dict[int | None, str] = {10: "近10年", None: "全历史"}

_TIER_DESC = {
    1: "曲线异常陡峭,历史上多见于宽松后段或复苏早段",
    2: "曲线偏陡",
    3: "曲线斜率处于常态区间",
    4: "曲线偏平",
    5: "曲线极度平坦乃至倒挂,历史上对应紧缩/衰退风险区",
}


def curve_daily() -> pd.DataFrame:
    """日频曲线利差及中间量:date, yield_3m, yield_10y, spread。"""
    rates = read_raw("rates/cn10y.parquet")[["date", "yield_3m", "yield_10y"]]
    df = rates.dropna().sort_values("date").reset_index(drop=True)
    df["spread"] = df["yield_10y"] - df["yield_3m"]
    return df


def curve_10y3m(window_years: int | None = 10) -> MetricResult:
    """曲线利差主函数(CMV 原版 10Y−3M 口径)。window_years=None → 全历史口径。"""
    df = curve_daily()
    monthly = monthly_sample(df.set_index("date")["spread"])
    direction = INVERSE  # 利差高(陡)= 低风险侧(绿);倒挂 = 风险侧(红)
    stats: SigmaStats = compute_sigma_stats(monthly, direction_sign(direction), window_years)
    rating = rating_from_z(stats.val_z)
    row = df.iloc[-1]

    desc = (
        f"10Y 国债收益率({row.yield_10y:.2f}%)减 3M({row.yield_3m:.2f}%),曲线利差 "
        f"{row.spread:+.2f} 个百分点。按{WINDOW_LABELS[window_years]}口径({stats.start} 起 "
        f"{stats.n} 个月,均值 {stats.mean:.2f}、σ {stats.sd:.2f}),当前偏离均值 "
        f"{stats.val_z:+.2f}σ,评级「{RATING_LEVELS[rating]['label']}」——{_TIER_DESC[rating]}。"
        f"(口径:CMV 原版 10Y−3M;初版曾用 1Y,已修正)"
    )
    return MetricResult(
        name="收益率曲线(10Y−3M)",
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
