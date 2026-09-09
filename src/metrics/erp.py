"""ERP 股债利差指标（FED 模型，设计文档第六节 12 卡片之一）。

沪深300 盈利收益率 1/PE(TTM) − 中国 10Y 国债收益率，单位百分点。
中间量（pe/ep/bond_10y）同结构保留、不落盘（AGENTS.md 规则 4/5）。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw

from .contract import INVERSE, MetricResult, RATING_LEVELS, direction_sign, rating_from_z
from .sigma import SigmaStats, compute_sigma_stats, monthly_sample

# 窗口标签（σ 方法第 4 条：主口径近 10 年，辅口径全历史）
WINDOW_LABELS: dict[int | None, str] = {10: "近10年", None: "全历史"}

# 各档白话解读（desc 尾句用）
_TIER_DESC = {
    1: "股票相对债券异常便宜，历史上对应长期布局区域",
    2: "股票相对债券偏便宜",
    3: "股债性价比大体均衡",
    4: "股票相对债券偏贵",
    5: "股票相对债券异常昂贵，历史上对应风险区域",
}


def erp_daily() -> pd.DataFrame:
    """日频 ERP 及中间量：date, pe_ttm, yield_10y, ep, erp。"""
    pe = read_raw("valuation/pe_000300.parquet")[["date", "pe_ttm"]]
    rates = read_raw("rates/cn10y.parquet")[["date", "yield_10y"]]
    df = pe.merge(rates, on="date").dropna().sort_values("date").reset_index(drop=True)
    df["ep"] = 1.0 / df["pe_ttm"]                         # 盈利收益率
    df["erp"] = (df["ep"] - df["yield_10y"] / 100) * 100  # 股债利差，百分点
    return df


def erp_000300(window_years: int | None = 10) -> MetricResult:
    """ERP 指标主函数。window_years=None → 全历史口径。"""
    df = erp_daily()
    monthly = monthly_sample(df.set_index("date")["erp"])
    direction = INVERSE  # ERP 高 = 股便宜（方向归一后负=便宜、正=贵）
    stats: SigmaStats = compute_sigma_stats(monthly, direction_sign(direction), window_years)
    rating = rating_from_z(stats.val_z)
    row = df.iloc[-1]
    label = RATING_LEVELS[rating]["label"]

    desc = (
        f"沪深300 盈利收益率（1/PE，{row.pe_ttm:.1f} 倍 → {row.ep * 100:.2f}%）比十年期"
        f"国债收益率（{row.yield_10y:.2f}%）高 {row.erp:.2f} 个百分点。"
        f"按{WINDOW_LABELS[window_years]}口径（{stats.start} 起 {stats.n} 个月，"
        f"均值 {stats.mean:.2f}、σ {stats.sd:.2f}），当前利差偏离均值 {stats.val_z:+.2f}σ，"
        f"评级「{label}」——{_TIER_DESC[rating]}。"
    )
    return MetricResult(
        name="股债利差 ERP（FED 模型）",
        current=float(row["erp"]),
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
