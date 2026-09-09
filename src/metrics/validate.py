"""估值分 vs 未来收益自证(IC 分析,CMV 会员版 Correlations 页的复刻)。

对每个参与综合分的卡片 + 综合分本身:expanding 估值z(当时视角,无前视)与
沪深300 未来 1/3 年月度收益的 Spearman 秩相关(IC)。IC < 0 且显著 = 估值z 低
(便宜)时未来收益高,σ 方法有预测力(方向约定:估值z 负=便宜)。

诚实声明:
- expanding 序列受 MIN_MONTHS=50 约束,综合分有效样本 2019-03 起,3Y 口径
  末端截到 2023-08,样本量小(n≈53),结论仅供参考;
- IC 是秩相关,对单调性敏感、对量级不敏感;月频非独立观测使显著性检验偏乐观,
  不做 p 值断言,只报 IC 与 n。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from scipy.stats import spearmanr

from data_module.storage import read_raw

from .aggregate import CARDS, composite_series
from .sigma import expanding_val_z, monthly_sample
from .contract import direction_sign

HORIZONS = {1: "未来1年", 3: "未来3年"}


@dataclass
class ICResult:
    """单卡单 horizon 的 IC 结果。"""

    ic: float          # Spearman 秩相关(期望为负:z 低=便宜→未来收益高)
    n: int             # 成对样本数
    coverage_start: str
    coverage_end: str


def hs300_monthly_close() -> pd.Series:
    """沪深300 月频收盘价(收益计算基准)。"""
    df = read_raw("index_daily/index_000300.parquet")[["date", "close"]]
    s = df.set_index("date")["close"]
    return s.resample("ME").last().dropna()


def forward_returns(horizon_years: int) -> pd.Series:
    """月末收盘价 horizon 年后的未来收益(%)。"""
    px = hs300_monthly_close()
    fwd = px.shift(-12 * horizon_years) / px - 1.0
    return fwd.dropna() * 100.0


def card_expanding_series(key: str) -> pd.Series:
    """CARDS 中某卡的 expanding 估值z 序列(当时视角)。"""
    if key == "composite":
        return composite_series()
    for k, _, daily_fn, col, direction in CARDS:
        if k == key:
            df = daily_fn()
            monthly = monthly_sample(df.set_index("date")[col])
            return expanding_val_z(monthly, direction_sign(direction))
    raise KeyError(f"未知卡片: {key}")


def ic_for(key: str, horizon_years: int) -> ICResult:
    """单卡单 horizon 的 IC 计算。"""
    z = card_expanding_series(key).dropna()
    fwd = forward_returns(horizon_years)
    pair = pd.concat([z.rename("z"), fwd.rename("fwd")], axis=1).dropna()
    if len(pair) < 12:
        return ICResult(ic=float("nan"), n=len(pair),
                        coverage_start="", coverage_end="")
    ic = float(spearmanr(pair["z"], pair["fwd"]).statistic)
    return ICResult(ic=ic, n=len(pair),
                    coverage_start=f"{pair.index.min():%Y-%m}",
                    coverage_end=f"{pair.index.max():%Y-%m}")


def ic_table() -> pd.DataFrame:
    """全部卡片 × 两个 horizon 的 IC 总表(行=卡,列=IC/n)。"""
    keys = [k for k, *_ in CARDS] + ["composite"]
    rows = []
    for key in keys:
        row: dict = {"card": key}
        for h, label in HORIZONS.items():
            r = ic_for(key, h)
            row[f"ic_{h}y"] = round(r.ic, 3) if r.n >= 12 else None
            row[f"n_{h}y"] = r.n if r.n >= 12 else None
            row[f"cov_{h}y"] = f"{r.coverage_start}~{r.coverage_end}" if r.n >= 12 else "样本不足"
        rows.append(row)
    return pd.DataFrame(rows)


def scatter_data(key: str, horizon_years: int) -> pd.DataFrame:
    """散点图数据:z 与未来收益成对序列(带日期列供着色)。"""
    z = card_expanding_series(key).dropna()
    fwd = forward_returns(horizon_years)
    pair = pd.concat([z.rename("z"), fwd.rename("fwd")], axis=1).dropna()
    out = pair.reset_index()
    out.columns = ["date", "z", "fwd"]  # 索引名不统一,按位置命名
    return out
