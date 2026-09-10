"""PMI 景气动量卡片(CMV 复刻 #8:Leading Economic Indicator 降级替代)。

CMV 用 Conference Board LEI 对标自身 12M 均线;中国无对应物,用官方制造业 PMI
对标自身 12 个月均线替代:PMI − 12MMA(百分点)。景气动量强 = 经济扩张 =
风险低(INVERSE:高→绿=安全侧;跌破均线=红=风险区)。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw

from .contract import INVERSE, MetricResult, RATING_LEVELS, direction_sign, rating_from_z
from .sigma import SigmaStats, compute_sigma_stats

WINDOW_LABELS: dict[int | None, str] = {10: "近10年", None: "全历史"}

_TIER_DESC = {
    1: "PMI 显著高于年线,景气动量强劲(扩张侧)",
    2: "PMI 高于年线,景气偏扩张",
    3: "PMI 围绕年线,景气中性",
    4: "PMI 低于年线,景气动量转弱",
    5: "PMI 深度低于年线,景气收缩区(衰退风险)",
}


def pmi_monthly() -> pd.DataFrame:
    """月频 PMI:date(月末), pmi。"""
    return read_raw("macro/pmi_official.parquet")[["date", "pmi"]].dropna()


def pmi_momentum_monthly() -> pd.DataFrame:
    """月频 PMI 动量:date(月末), mom = PMI − 12MMA(百分点)。"""
    df = pmi_monthly().sort_values("date").reset_index(drop=True)
    s = df.set_index("date")["pmi"]
    mom = s - s.rolling(12, min_periods=12).mean()
    out = mom.dropna().reset_index().rename(columns={"index": "date", "pmi": "mom"})
    return out[["date", "mom"]]


def pmi_momentum(window_years: int | None = 10) -> MetricResult:
    """PMI 景气动量主函数。window_years=None → 全历史口径。"""
    df = pmi_momentum_monthly()
    monthly = df.set_index("date")["mom"]
    direction = INVERSE  # 景气动量强 = 风险低(绿);跌破均线 = 风险区(红)
    stats: SigmaStats = compute_sigma_stats(monthly, direction_sign(direction), window_years)
    rating = rating_from_z(stats.val_z)
    row = df.iloc[-1]
    pmi_last = pmi_monthly().iloc[-1]

    desc = (
        f"官方制造业 PMI {pmi_last.pmi:.1f},高于自身 12 个月均线 {row.mom:+.2f} 个百分点。"
        f"按{WINDOW_LABELS[window_years]}口径({stats.start} 起 {stats.n} 个月,均值 "
        f"{stats.mean:.2f}、σ {stats.sd:.2f}),当前偏离均值 {stats.val_z:+.2f}σ,"
        f"评级「{RATING_LEVELS[rating]['label']}」——{_TIER_DESC[rating]}。"
        f"(口径:官方制造业 PMI − 12 个月均线)"
    )
    return MetricResult(
        name="PMI 景气动量(对比12M均线)",
        current=float(row["mom"]),
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
