"""指标层统一契约（设计文档第六节 / AGENTS.md 指标层契约）。

每个估值模型 = 一个纯函数，输出 MetricResult；指标结果不落盘，
由仪表盘实时计算 + st.cache_data 当天缓存（AGENTS.md 硬性规则 5）。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .sigma import SigmaStats

# 指标方向（设计文档：direction 正向或反向指标）
POSITIVE = "positive"  # 值高 = 贵（PE、PB、巴菲特指标类）
INVERSE = "inverse"    # 值高 = 便宜（ERP、股息率、QVIX 类）


def direction_sign(direction: str) -> int:
    """方向字符串 → 乘法符号。inverse → −1，positive → +1。"""
    return -1 if direction == INVERSE else 1


# 五档评级表：rating → (标签, 状态色)。
# 颜色为状态语义色（dataviz status palette）；文字标签永远伴随颜色，
# 不许仅靠颜色传义（黄/橙在浅色表面对比度低于 3:1 的既定缓解方式）。
RATING_LEVELS: dict[int, dict[str, str]] = {
    1: {"label": "极低估", "color": "#0ca30c"},  # good 绿
    2: {"label": "低估", "color": "#0ca30c"},
    3: {"label": "公允", "color": "#fab219"},    # warning 黄
    4: {"label": "高估", "color": "#ec835a"},    # serious 橙
    5: {"label": "极高估", "color": "#d03b3b"},  # critical 红
}


def rating_from_z(val_z: float) -> int:
    """估值z（方向归一后：负=便宜、正=贵）→ 五档 rating（σ 方法第 3 条）。"""
    if val_z <= -2:
        return 1
    if val_z <= -1:
        return 2
    if val_z < 1:
        return 3
    if val_z < 2:
        return 4
    return 5


@dataclass
class MetricResult:
    """统一输出契约：name / current / unit / sigma / rating / color / series /
    ±1σ带（stats 内）/ desc / direction。"""

    name: str            # 中文模型名
    current: float       # 当前值
    unit: str            # 单位（如 "个百分点"）
    sigma: float         # 估值z：方向归一后，负=便宜、正=贵
    rating: int          # 1-5
    color: str           # 评级状态色
    direction: str       # positive / inverse
    window: str          # 窗口标签（"近10年" / "全历史"）
    series: pd.Series    # 月频历史序列（DatetimeIndex）
    stats: SigmaStats    # 同窗口均值/σ/±1σ±2σ 带
    desc: str            # 白话解释
    updated: str         # 数据截止日（YYYY-MM-DD）
