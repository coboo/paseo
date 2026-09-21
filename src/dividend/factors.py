"""构建红利指数因子面板（dividend-research build_factors.py 迁移版）。

口径（与原研究一致，见 HANDOFF §4/§5.1）：
- DV(股息率)重建：dv = 252 * mean(d ln(TR/PR), 252) —— 全收益缺口漂移的年化
- ERP(股债利差) = DV - 10Y国债收益率；ey_spread = 1/PE_TTM - 10Y国债
- 动量/波动：TR 口径；前瞻标签为未来 h 日全收益
- 分位数：expanding 历史分位（修复：取值截至前一交易日，不含当日）

数据源全部走 data_module（data/raw parquet），禁止相对路径。
基金净值（515450/159545）：主项目数据集为 akshare 口径，日期正确
（研究侧 pingzhongdata CSV 曾整体 -1 交易日错位，迁移后以主项目为准，无需 shift）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_module.storage import read_raw

# 无风险利率（中/美国债，单位小数）
_BOND_REL = "rates/bond_zh_us_rate.parquet"

# 基金净值数据集（主项目 raw 路径；close=单位净值, acc_nav=累计净值=全收益代理）
_FUND_REL = {"515450": "index_daily/spdiv50_nav_515450.parquet",
             "159545": "index_global/hshylv_nav_159545.parquet"}

HORIZONS = (21, 63, 126, 252)


def _bond() -> pd.DataFrame:
    """中/美国债收益率（日频，%），转小数、ffill 前向填充由调用方做。"""
    b = read_raw(_BOND_REL).set_index("date").sort_index()
    return b[["cn_2y", "cn_10y", "us_10y"]].astype(float) / 100.0


def load_csindex(price_code: str, tr_code: str) -> pd.DataFrame:
    """中证系：价格收盘 + 全收益收盘（ffill 对齐价格交易日）+ PE_TTM。"""
    p = read_raw(f"valuation/csindex_pe_{price_code}.parquet").set_index("date")
    t = read_raw(f"index_daily/index_tr_{tr_code}.parquet").set_index("date")
    df = pd.DataFrame({
        "close": p["close"],
        "tr": t["close"].reindex(p.index).ffill(),
        "pe_ttm": p["pe_ttm"],
    })
    return df


def load_fund(code: str) -> pd.DataFrame:
    """基金净值代理（无 PE）。主项目 akshare 净值日期正确，不再做错位 shift。"""
    f = read_raw(_FUND_REL[code]).set_index("date").sort_index()
    return pd.DataFrame({"close": f["close"], "tr": f["acc_nav"], "pe_ttm": np.nan})


def pct_rank(s: pd.Series, min_periods: int = 252) -> pd.Series:
    """expanding 历史分位（修复前视：取值截至前一交易日，不含当日）。

    原实现以当日值为参照对历史取分位，当日收盘前不可得；现改为先 shift(1)
    再对昨日值做 expanding 分位，保证 t 日信号只用到 t-1 及以前数据。
    """
    past = s.shift(1)
    return past.expanding(min_periods=min_periods).apply(
        lambda x: (x[:-1] <= x[-1]).mean(), raw=True)


def build_panel(df: pd.DataFrame, clip: float | None = 0.001) -> pd.DataFrame:
    """单标的因子面板。clip=日缺口限幅（中证全收益陈旧跳点 ±0.1%；基金净值 None 不限幅）。"""
    df = df.copy()
    df["ret_tr"] = np.log(df["tr"]).diff()
    # 股息率重建：TR/PR 缺口漂移年化
    gap = np.log(df["tr"] / df["close"])
    d_gap = gap.diff().clip(-clip, clip) if clip else gap.diff()
    df["dv"] = d_gap.rolling(252, min_periods=60).mean() * 252
    # 估值与利差
    bond = _bond()
    df["cgb10"] = bond["cn_10y"].reindex(df.index).ffill()
    df["cgb2"] = bond["cn_2y"].reindex(df.index).ffill()
    df["us10"] = bond["us_10y"].reindex(df.index).ffill()
    df["erp"] = df["dv"] - df["cgb10"]                # 股债利差(股息率口径)
    df["ey"] = 1.0 / df["pe_ttm"]                     # 盈利收益率
    df["ey_spread"] = df["ey"] - df["cgb10"]          # 盈利收益率利差
    # 动量与波动（TR口径）
    for h in HORIZONS:
        df[f"mom_{h}"] = df["tr"].pct_change(h)
    df["vol_20"] = df["ret_tr"].rolling(20).std() * np.sqrt(252)
    df["vol_60"] = df["ret_tr"].rolling(60).std() * np.sqrt(252)
    # 分位数（不含当日，修复前视）
    df["pe_pct"] = pct_rank(df["pe_ttm"]) if df["pe_ttm"].notna().any() else np.nan
    df["dv_pct"] = pct_rank(df["dv"])
    df["erp_pct"] = pct_rank(df["erp"])
    # 未来收益标签（TR口径）
    for h in HORIZONS:
        df[f"fwd_{h}"] = df["tr"].shift(-h) / df["tr"] - 1
    return df


def build_panels() -> dict[str, pd.DataFrame]:
    """全量面板：四个标的 + 沪深300 基准（相对估值分母）。"""
    panels = {
        # 中证系（有PE），clip=0.001 默认
        "H30269": build_panel(load_csindex("H30269", "H20269")),
        "930955": build_panel(load_csindex("930955", "H20955")),
        # 基金代理（无PE）—— 净值分红为季度大块跳变，不设限幅
        "515450": build_panel(load_fund("515450"), clip=None),
        "159545": build_panel(load_fund("159545"), clip=None),
        # 基准：沪深300 相对估值
        "000300": load_csindex("000300", "H00300"),
    }
    return panels
