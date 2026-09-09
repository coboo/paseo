"""Sahm 规则卡片(CMV 复刻 #9:Sahm Rule)。

CMV 口径:失业率 3 个月均值较过去 12 个月低点上升 ≥0.5pp = 衰退触发。
实现:gap = 失业率3MMA − 3MMA 的过去12个月最低值(百分点),gap 越大 =
衰退风险越高(POSITIVE:高→红=风险区,与曲线卡倒挂=红的语义一致)。
数据 2018-01 起(城镇调查失业率发布史短),expanding σ 前期样本不足,
卡面声明短样本限制。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw

from .contract import POSITIVE, MetricResult, RATING_LEVELS, direction_sign, rating_from_z
from .sigma import SigmaStats, compute_sigma_stats

WINDOW_LABELS: dict[int | None, str] = {10: "近10年", None: "全历史"}

_TIER_DESC = {
    1: "失业率远低于周期低点阈值,经济过热侧",
    2: "失业率偏低,劳动力市场紧俏",
    3: "失业率变化处于常态区间",
    4: "失业率上升偏快,接近 Sahm 关注区",
    5: "Sahm 规则触发区(3M 均值升破 12M 低点 +0.5pp),历史上对应衰退",
}


def unemployment_monthly() -> pd.DataFrame:
    """月频失业率:date(月末), urate(%)。"""
    return read_raw("macro/urban_unemployment.parquet")[["date", "urate"]].dropna()


def sahm_monthly() -> pd.DataFrame:
    """月频 Sahm gap:date(月末), gap(百分点)。"""
    df = unemployment_monthly().sort_values("date").reset_index(drop=True)
    s = df.set_index("date")["urate"]
    u3 = s.rolling(3).mean()
    gap = u3 - u3.rolling(12, min_periods=12).min()
    out = gap.dropna().reset_index().rename(columns={"index": "date", "urate": "gap"})
    return out[["date", "gap"]]


def sahm_rule(window_years: int | None = 10) -> MetricResult:
    """Sahm 规则主函数。window_years=None → 全历史口径。"""
    df = sahm_monthly()
    monthly = df.set_index("date")["gap"]
    direction = POSITIVE  # gap 大 = 衰退风险 = 红档
    stats: SigmaStats = compute_sigma_stats(monthly, direction_sign(direction), window_years)
    rating = rating_from_z(stats.val_z)
    row = df.iloc[-1]
    triggered = "已触发(≥+0.5pp)" if row.gap >= 0.5 else "未触发(<+0.5pp)"

    desc = (
        f"失业率 3M 均值较 12M 低点 +{row.gap:.2f} 个百分点,Sahm 规则{triggered}。"
        f"按{WINDOW_LABELS[window_years]}口径({stats.start} 起 {stats.n} 个月,均值 "
        f"{stats.mean:.2f}、σ {stats.sd:.2f}),当前偏离均值 {stats.val_z:+.2f}σ,"
        f"评级「{RATING_LEVELS[rating]['label']}」——{_TIER_DESC[rating]}。"
        f"(口径:城镇调查失业率 2018-01 起,样本短,评级可靠性弱于其他卡)"
    )
    return MetricResult(
        name="Sahm 规则(失业率缺口)",
        current=float(row["gap"]),
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
