"""metrics：指标层（设计文档第六节）。

σ 评估引擎（sigma.py）+ 统一契约（contract.py）+ 估值模型函数。
指标结果不落盘（AGENTS.md 规则 5），仪表盘实时计算。
"""
from .contract import (
    INVERSE,
    POSITIVE,
    RATING_LEVELS,
    MetricResult,
    direction_sign,
    rating_from_z,
)
from .aggregate import CARDS, composite, composite_series
from .buffett import buffett_indicator, buffett_monthly
from .credit_spread import credit_spread, credit_spread_daily
from .curve_10y3m import curve_10y3m
from .curve_10y3m import curve_daily
from .curve_10y1y import curve_10y1y  # 向后兼容别名(=curve_10y3m)
from .dividend_spread import dividend_spread, dividend_spread_daily
from .erp import WINDOW_LABELS, erp_000300, erp_daily
from .epu import epu_china, epu_monthly
from .margin_debt import margin_debt, margin_debt_monthly
from .pmi_momentum import pmi_momentum, pmi_momentum_monthly
from .sahm import sahm_monthly, sahm_rule, unemployment_monthly
from .more_cards import (
    ma250_daily,
    ma250_dev,
    pe_000300,
    pe_daily,
    qvix_50etf,
    qvix_daily,
    rates_10y,
    rates_daily,
)
from .sigma import MIN_MONTHS, SigmaStats, compute_sigma_stats, expanding_val_z, monthly_sample

__all__ = [
    "INVERSE",
    "POSITIVE",
    "RATING_LEVELS",
    "MetricResult",
    "direction_sign",
    "rating_from_z",
    "WINDOW_LABELS",
    "CARDS",
    "composite",
    "composite_series",
    "erp_000300",
    "erp_daily",
    "curve_10y3m",
    "curve_10y1y",
    "curve_daily",
    "buffett_indicator",
    "buffett_monthly",
    "margin_debt",
    "margin_debt_monthly",
    "credit_spread",
    "credit_spread_daily",
    "epu_china",
    "epu_monthly",
    "sahm_rule",
    "sahm_monthly",
    "unemployment_monthly",
    "pmi_momentum",
    "pmi_momentum_monthly",
    "dividend_spread",
    "dividend_spread_daily",
    "ma250_daily",
    "ma250_dev",
    "pe_000300",
    "pe_daily",
    "qvix_50etf",
    "qvix_daily",
    "rates_10y",
    "rates_daily",
    "MIN_MONTHS",
    "SigmaStats",
    "compute_sigma_stats",
    "expanding_val_z",
    "monthly_sample",
]
