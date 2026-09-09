"""信用利差卡片(CMV 复刻 #12:Junk Bond Spreads)。

中债中短期票据收益率曲线(AAA)10Y 减中债国债 10Y,单位百分点。利差走阔 =
信用风险担忧上升 = 情绪偏冷(INVERSE:高→绿=便宜);利差极窄 = 乐观拥挤(红)。
中国无高收益债长历史源,用 AAA 中短票利差做代理(已在数据源 note 与卡面声明)。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw

from .contract import INVERSE, MetricResult, RATING_LEVELS, direction_sign, rating_from_z
from .sigma import SigmaStats, compute_sigma_stats, monthly_sample

WINDOW_LABELS: dict[int | None, str] = {10: "近10年", None: "全历史"}

_TIER_DESC = {
    1: "信用利差处于历史极窄位,风险偏好极端拥挤(逆向视角的警惕区)",
    2: "信用利差偏窄,市场乐观",
    3: "信用利差处于常态区间",
    4: "信用利差偏阔,市场担忧信用风险",
    5: "信用利差处于历史极阔位,信用风险担忧极盛(逆向视角的布局区)",
}


def credit_spread_daily() -> pd.DataFrame:
    """日频信用利差及中间量:date, ts_aaa_10y, yield_10y, spread(百分点)。"""
    ts = read_raw("rates/credit_ts_aaa.parquet")[["date", "ts_aaa_10y"]]
    gov = read_raw("rates/cn10y.parquet")[["date", "yield_10y"]]
    df = ts.merge(gov, on="date").dropna().sort_values("date").reset_index(drop=True)
    df["spread"] = df["ts_aaa_10y"] - df["yield_10y"]
    return df


def credit_spread(window_years: int | None = 10) -> MetricResult:
    """信用利差主函数。window_years=None → 全历史口径。"""
    df = credit_spread_daily()
    monthly = monthly_sample(df.set_index("date")["spread"])
    direction = INVERSE  # 利差阔 = 担忧盛 = 便宜侧(绿)
    stats: SigmaStats = compute_sigma_stats(monthly, direction_sign(direction), window_years)
    rating = rating_from_z(stats.val_z)
    row = df.iloc[-1]

    desc = (
        f"中短票 AAA 10Y 收益率({row.ts_aaa_10y:.2f}%)减国债 10Y({row.yield_10y:.2f}%),"
        f"信用利差 {row.spread:.2f} 个百分点。按{WINDOW_LABELS[window_years]}口径({stats.start} 起 "
        f"{stats.n} 个月,均值 {stats.mean:.2f}、σ {stats.sd:.2f}),当前偏离均值 "
        f"{stats.val_z:+.2f}σ,评级「{RATING_LEVELS[rating]['label']}」——{_TIER_DESC[rating]}。"
        f"(口径:AAA 中短票为高收益利差代理,中国无高收益债长历史)"
    )
    return MetricResult(
        name="信用利差(中短票AAA−国债)",
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
