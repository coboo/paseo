"""两融情绪卡片(CMV 复刻 #11:Margin Debt)。

CMV 口径:两融余额 12 个月变化量占全 A 总市值的比例,对历史均值做 σ 偏离。
杠杆快速上升 = 投资者乐观加杠杆 = 情绪偏热(POSITIVE:高→贵=红档)。
数据:margin(沪深合并,2010-04 起)× a_market_cap(月度总市值);比值天然月频。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw

from .contract import POSITIVE, MetricResult, RATING_LEVELS, direction_sign, rating_from_z
from .sigma import SigmaStats, compute_sigma_stats, monthly_sample

WINDOW_LABELS: dict[int | None, str] = {10: "近10年", None: "全历史"}

_TIER_DESC = {
    1: "杠杆处于历史极低位,投资者情绪冰点(逆向视角的冷淡区)",
    2: "杠杆偏低,情绪谨慎",
    3: "杠杆变化处于常态区间",
    4: "杠杆上升偏快,情绪偏乐观",
    5: "杠杆急升,情绪极度乐观(常伴市场顶部)",
}


def margin_debt_monthly() -> pd.DataFrame:
    """月频两融杠杆变化率:date(月末), ratio(12M 余额变化/总市值, %)。

    margin 日频取月末值,12 个月差分;a_market_cap 月度总市值(亿元)转元。
    """
    margin = read_raw("margin/margin_total.parquet")[["date", "margin_bal"]]
    mv = read_raw("valuation/a_market_cap.parquet")[["date", "mv_total"]]
    m = monthly_sample(margin.set_index("date")["margin_bal"]).to_frame("margin_bal")
    mv_m = mv.set_index("date")["mv_total"] * 1e8  # 亿元 → 元
    # 总市值 REPORT_DATE 为月初(如 2010-05-01 代表 5 月),对齐到月末再合并
    mv_m.index = mv_m.index + pd.offsets.MonthEnd(0)
    m["mv_yuan"] = mv_m
    df = m.dropna()
    df["ratio"] = (df["margin_bal"] - df["margin_bal"].shift(12)) / df["mv_yuan"] * 100.0
    df = df.dropna(subset=["ratio"]).reset_index().rename(columns={"index": "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "ratio"]]


def margin_debt(window_years: int | None = 10) -> MetricResult:
    """两融情绪主函数。window_years=None → 全历史口径。"""
    df = margin_debt_monthly()
    monthly = df.set_index("date")["ratio"]
    direction = POSITIVE  # 杠杆升 = 情绪乐观 = 贵(红)
    stats: SigmaStats = compute_sigma_stats(monthly, direction_sign(direction), window_years)
    rating = rating_from_z(stats.val_z)
    row = df.iloc[-1]

    desc = (
        f"两融余额 12 个月变化占全 A 总市值 {row.ratio:+.2f}%。按{WINDOW_LABELS[window_years]}口径"
        f"({stats.start} 起 {stats.n} 个月,均值 {stats.mean:.2f}、σ {stats.sd:.2f}),"
        f"当前偏离均值 {stats.val_z:+.2f}σ,评级「{RATING_LEVELS[rating]['label']}」"
        f"——{_TIER_DESC[rating]}。(口径:两融余额变动/总市值,沪深两融合并)"
    )
    return MetricResult(
        name="两融杠杆变化(占市值比)",
        current=float(row["ratio"]),
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
