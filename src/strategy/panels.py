"""基线策略通用信号层面板(设计文档第十一节)。

资产键 → 数据源映射(信号层干净价格);面板骨架 = A 股交易日(沪深300 的日期,
沿用 GEM 踩坑结论:长假期混入会让月首触发日与执行日错位);海外/黄金源 reindex+ffill(5)。
cash 列 = 中债 3M 日利率复利累积价格(现金腿,替代旧约定"固定年化 2%")。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import DERIVED_DIR, read_raw

# 资产规格:(raw 相对路径 | None=derived, 价格列, 是否 ×usdcny)
ASSET_SPECS: dict[str, tuple[str | None, str, bool]] = {
    "hs300": ("index_daily/index_000300.parquet", "open", False),
    "csi500": ("index_daily/index_000905.parquet", "open", False),
    "hdlow": ("index_daily/index_H30269.parquet", "open", False),
    "spx": ("index_global/spx_inx.parquet", "open", True),
    "gold": ("gold/au_main_sina.parquet", "open", False),
    "bond": (None, "close", False),   # derived 拼接债券腿(无开盘价,前收盘近似)
}


def _series(key: str, price_col: str | None = None) -> pd.Series:
    """单资产日频价格序列(DatetimeIndex);price_col 覆盖规格列(信号用 close)。"""
    path, col, use_fx = ASSET_SPECS[key]
    col = price_col or col
    if path is None:
        s = pd.read_parquet(DERIVED_DIR / "aligned" / "bond_leg_spliced_511260.parquet") \
              .set_index("date")[col]
    else:
        s = read_raw(path).set_index("date")[col]
    if use_fx:
        fx = read_raw("fx/usdcny.parquet").set_index("date")["close"]
        s = s * fx.reindex(s.index).ffill()
    return s.astype(float).sort_index()


def cash_price(rf_col: str = "yield_3m") -> pd.Series:
    """现金腿价格:3M 日利率 ACT/365 复利累积(起点 1)。"""
    rf = read_raw("rates/cn10y.parquet").set_index("date")[rf_col] / 100.0 / 365.0
    return (1.0 + rf).cumprod()


def build_signal_panel(keys: list[str], with_cash: bool = True) -> pd.DataFrame:
    """信号层开盘面板:列 = keys(+cash),骨架 = A 股交易日。"""
    frame = _series("hs300").rename("hs300").to_frame()
    for k in keys:
        if k == "hs300":
            continue
        frame[k] = _series(k).reindex(frame.index).ffill(limit=5)
    if with_cash:
        frame["cash"] = cash_price().reindex(frame.index).ffill(limit=10)
    frame = frame[keys + (["cash"] if with_cash else [])].dropna()
    return frame


def month_end_anchor_dates(start: str | None = None,
                           end: str | None = None) -> pd.DatetimeIndex:
    """A 股日历每月最后交易日锚点(基线策略共用)。

    新鲜度截断(同 GEM 纪律):锚点 ≤ min(各资产源 + 利率的最后日期),
    防未来日历锚点用陈旧价格拼出不完整月份的伪信号(如 8 月未走完出 8-31 信号)。
    """
    cal = read_raw("calendar.parquet")["date"]
    if start is not None:
        cal = cal[cal >= pd.Timestamp(start)]
    anchors = pd.DatetimeIndex(sorted(cal.groupby(cal.dt.to_period("M")).max().values))
    last = min(_series(k).index.max() for k in ASSET_SPECS)
    last = min(last, read_raw("rates/cn10y.parquet")["date"].max())
    if end is not None:
        last = min(last, pd.Timestamp(end))
    return anchors[anchors <= last]
