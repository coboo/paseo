"""红利低波簇研究：从中证官网 index-perf 抓取指数日线（含滚动市盈率 peg）。

数据源与 data_module.sources._fetch_csindex_perf 一致（该处为入库注册表），
本模块供研究侧复算/补数使用，抓取统一走 data_module.net.retry_fetch 重试
（中证官网间歇 502）。
"""
from __future__ import annotations

import pandas as pd
import requests

from data_module.net import retry_fetch

URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.csindex.com.cn/"}

# 研究涉及的中证指数代码（价格 + 全收益）
CODES = {
    "H30269": "红利低波(价格)",
    "H20269": "红利低波(全收益)",
    "930955": "红利低波100(价格)",
    "H20955": "红利低波100(全收益)",
    "000300": "沪深300(价格)",
    "H00300": "沪深300(全收益)",
}


def fetch_csindex(code: str, start: str = "20150101", end: str = "20991231") -> pd.DataFrame:
    """拉取单个指数日线，返回 date, close, pe_ttm, pct_chg（按 date 排序去重）。"""
    def call() -> list:
        r = requests.get(URL, params={"indexCode": code, "startDate": start, "endDate": end},
                         headers=HEADERS, timeout=60)
        r.raise_for_status()
        return r.json().get("data") or []

    data = retry_fetch(call, retries=5, base_sleep=2.0)
    df = pd.DataFrame(data)
    if df.empty:
        raise RuntimeError(f"index-perf({code}) 返回空表")
    df = df[["tradeDate", "close", "peg", "changePct"]].rename(
        columns={"tradeDate": "date", "peg": "pe_ttm", "changePct": "pct_chg"})
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return df.reset_index(drop=True)
