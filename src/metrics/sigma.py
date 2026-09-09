"""σ 评估引擎（设计文档第六节"σ 评估方法"，CMV 复刻）。

所有估值模型共用：月频采样、方向归一、五档、双窗口、expanding 回验。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# expanding 回验最低样本量（月）：2006–2009 段样本不足（2007 泡沫顶
# expanding 估值z 仅 +1.38 未及红档），评级从 2010 起可信（σ 方法第 5/6 条）
MIN_MONTHS = 50


@dataclass
class SigmaStats:
    """单窗口 σ 统计（画 σ 带用）。"""

    mean: float
    sd: float
    n: int          # 月频样本数
    start: str      # 窗口起点 YYYY-MM
    end: str        # 窗口终点 YYYY-MM
    z_raw: float    # 未方向归一 z = (当前 − 均值) / σ
    val_z: float    # 估值z = z_raw × direction（负=便宜、正=贵）
    lo2: float      # 均值 − 2σ
    lo1: float      # 均值 − 1σ
    hi1: float      # 均值 + 1σ
    hi2: float      # 均值 + 2σ


def monthly_sample(daily: pd.Series) -> pd.Series:
    """日频 → 月频（月末）。均值/σ 用月频口径，避免日频自相关虚增有效样本。"""
    s = daily.dropna().sort_index()
    return s.resample("ME").last().dropna()


def _window_tail(monthly: pd.Series, window_years: int | None) -> pd.Series:
    """窗口终点 = 样本末端；window_years=None 取全历史，否则往前 N 年。"""
    if window_years is None:
        return monthly
    cutoff = monthly.index[-1] - pd.DateOffset(years=window_years)
    return monthly[monthly.index >= cutoff]


def compute_sigma_stats(
    monthly: pd.Series, direction_sign: int, window_years: int | None = 10
) -> SigmaStats:
    """对一个窗口计算 σ 统计与估值z。

    direction_sign: +1（值高=贵）/ −1（值高=便宜），来自 contract.direction_sign。
    """
    s = _window_tail(monthly, window_years)
    cur = s.iloc[-1]
    mean, sd = float(s.mean()), float(s.std())
    z_raw = (cur - mean) / sd
    return SigmaStats(
        mean=mean,
        sd=sd,
        n=len(s),
        start=f"{s.index[0]:%Y-%m}",
        end=f"{s.index[-1]:%Y-%m}",
        z_raw=z_raw,
        val_z=z_raw * direction_sign,
        lo2=mean - 2 * sd,
        lo1=mean - sd,
        hi1=mean + sd,
        hi2=mean + 2 * sd,
    )


def expanding_val_z(
    monthly: pd.Series, direction_sign: int, min_months: int = MIN_MONTHS
) -> pd.Series:
    """当时视角估值z 序列（画历史评级演进 / 回验用）。

    每个时点只用截至当时的历史，严禁用全样本统计量回看（σ 方法第 5 条）；
    样本 < min_months 输出 NaN（σ 方法第 6 条）。
    """
    vals: dict[pd.Timestamp, float] = {}
    for i, (ts, v) in enumerate(monthly.items()):
        hist = monthly.iloc[: i + 1]
        if len(hist) < min_months:
            vals[ts] = float("nan")
            continue
        z = (v - hist.mean()) / hist.std()
        vals[ts] = z * direction_sign
    return pd.Series(vals, dtype=float)
