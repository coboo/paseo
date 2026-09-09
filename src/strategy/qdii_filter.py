"""QDII 溢价代理与买入门控(设计文档第十节:执行层对照实验,不影响信号层)。

nav_513500 单位净值有份额拆分断崖(2022-03-30 单日 -49.8%,PROGRESS 已记录),
溢价不能直接 close/nav−1;用 close_qfq/nav 比率对 63 日滚动中位数(仅向后看)的
偏离作代理,比率单日跳幅 >50% 视为拆分断点、断点起重新锚定。
"""
from __future__ import annotations

import pandas as pd

from data_module.storage import read_raw


def premium_proxy(code: str = "513500", window: int = 63) -> pd.Series:
    """QDII 溢价代理(日频,小数)。滚动中位数仅用历史数据,无前视。"""
    etf = read_raw(f"etf_daily/etf_qfq_{code}.parquet")[["date", "close"]]
    nav = read_raw(f"etf_nav/nav_{code}.parquet")[["date", "nav"]]
    df = etf.merge(nav, on="date", how="inner").dropna().set_index("date").sort_index()
    df["ratio"] = df["close"] / df["nav"]

    # 拆分断点:ratio 单日跳幅 >50% → 分段,段内各自滚动锚定
    brk = df["ratio"].pct_change().abs() > 0.5
    seg = brk.cumsum()
    anchor = df.groupby(seg)["ratio"].transform(
        lambda s: s.rolling(window, min_periods=5).median())
    # 窗口未满时退化为 expanding(早期数据仍可用)
    anchor = anchor.fillna(df.groupby(seg)["ratio"].transform(
        lambda s: s.expanding(min_periods=5).median()))
    premium = df["ratio"] / anchor - 1.0
    return premium.dropna()


def apply_premium_gate(sig: pd.DataFrame, cap: float = 0.03,
                       proxy: pd.Series | None = None) -> pd.DataFrame:
    """执行层买入门:目标 = 513500 且信号日溢价 > cap → 当月持防御腿、次月自然重试。

    只挡买入不挡卖出(卖出无溢价约束);只改 etf_target / blocked_by_premium,
    不动 position(信号层不受门控影响,设计文档第十节)。
    """
    out = sig.copy()
    if proxy is None:
        proxy = premium_proxy()
    prem = out["date"].map(proxy.reindex(proxy.index.union(out["date"])).ffill())
    out["premium_513500"] = prem
    blocked = (out["etf_target"] == "513500") & (prem > cap)
    out["blocked_by_premium"] = blocked
    out.loc[blocked, "etf_target"] = "511260"
    return out
