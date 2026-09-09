"""EPU 政策不确定性卡片(CMV 复刻 #14:Economic Policy Uncertainty)。

中国 EPU 指数(policyuncertainty.com),月频。不确定性高 = 市场情绪悲观 =
逆向视角的便宜侧(INVERSE:高→绿)。注意官方更新停滞(数据止于 2023-11),
当前读数滞后约 3 年,卡面必须声明;σ 历史分析不受影响。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw

from .contract import INVERSE, MetricResult, RATING_LEVELS, direction_sign, rating_from_z
from .sigma import SigmaStats, compute_sigma_stats

WINDOW_LABELS: dict[int | None, str] = {10: "近10年", None: "全历史"}

_TIER_DESC = {
    1: "政策不确定性处于历史极高位,悲观情绪极盛(逆向视角的布局区)",
    2: "政策不确定性偏高,情绪悲观",
    3: "政策不确定性处于常态区间",
    4: "政策不确定性偏低,情绪平静乐观",
    5: "政策不确定性处于历史极低位,情绪极度乐观(逆向视角的警惕区)",
}


def epu_monthly() -> pd.DataFrame:
    """月频 EPU:date(月末), epu。"""
    df = read_raw("macro/epu_china.parquet")[["date", "epu"]].dropna()
    df["date"] = pd.to_datetime(df["date"]) + pd.offsets.MonthEnd(0)
    return df.sort_values("date").reset_index(drop=True)


def epu_china(window_years: int | None = 10) -> MetricResult:
    """EPU 主函数。window_years=None → 全历史口径。"""
    df = epu_monthly()
    monthly = df.set_index("date")["epu"]
    direction = INVERSE  # 不确定性高 = 悲观 = 逆向便宜侧(绿)
    stats: SigmaStats = compute_sigma_stats(monthly, direction_sign(direction), window_years)
    rating = rating_from_z(stats.val_z)
    row = df.iloc[-1]

    desc = (
        f"中国 EPU 指数 {row.epu:.0f}(基期 1985–2010=100)。按{WINDOW_LABELS[window_years]}口径"
        f"({stats.start} 起 {stats.n} 个月,均值 {stats.mean:.0f}、σ {stats.sd:.0f}),"
        f"当前偏离均值 {stats.val_z:+.2f}σ,评级「{RATING_LEVELS[rating]['label']}」"
        f"——{_TIER_DESC[rating]}。"
        f"⚠️ 官方数据更新停滞,当前读数截至 {row['date']:%Y-%m},滞后约 3 年。"
    )
    return MetricResult(
        name="EPU 政策不确定性(逆向)",
        current=float(row["epu"]),
        unit="点",
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
