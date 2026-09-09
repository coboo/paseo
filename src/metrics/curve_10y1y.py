"""⚠ 已废弃:收益率曲线卡片初版用 10Y−1Y 口径,与 CMV 原版(10Y−3M)不符。

2026-09-09 起口径修正版见 curve_10y3m.py(数据源同为 cn10y,仅短端列 1Y→3M)。
本文件仅保留向后兼容别名,新代码请用 curve_10y3m / curve_10y3m.curve_daily。
"""
from __future__ import annotations

from .curve_10y3m import curve_10y3m as _curve_10y3m
from .curve_10y3m import curve_daily

# 向后兼容别名(aggregate/旧测试曾引用)
curve_10y1y = _curve_10y3m
