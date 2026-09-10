"""行情快照：实时现货接口 → parquet 收盘兜底，结果不落盘（AGENTS.md 规则 5 同律）。

供行情监控页（app/market_monitor.py）使用。每条报价返回统一 Quote 结构，
实时源不可达时回退到 data/raw 最新收盘，并以 live/source 字段明示口径
（DESIGN.md 诚实展示原则：没有口径标注的数字不许上页面）。

抓取链与数据源分工（2026-09-10 探针结论，scripts/probe_quotes.py 可复验）：
- A股指数实时：新浪 stock_zh_index_spot_sina 为主（本机/云端实测最稳）；
  H30269 等中证系指数新浪没有 → 东财 stock_zh_index_spot_em(中证系列指数) 补；
  两者都失败 → parquet 收盘兜底。
- ETF 实时：新浪 hq.sinajs.cn 批量快照为主（12 只全覆盖含 QDII）；
  东财 fund_etf_spot_em 为备；再败 → etf_qfq 收盘兜底（前复权价，口径注明）。
- 海外指数/黄金/债券指数：对中国用户本来就是昨夜收盘，直接 parquet EOD。
- QDII 溢价率 = ETF 实时价 ÷ 最新单位净值 − 1（溢价是时点比率，price 与
  单位净值同为当前份额口径；累计净值含拆分/分红累积，做分母会得到 -46% 级
  假折价。PROGRESS.md"QDII 用累计净值"的规则针对收益率序列对比，不适用此处）。

测试开关：环境变量 PASEO_MARKET_OFFLINE=1 时跳过一切网络请求，全部走
parquet 兜底（AppTest 不依赖实时网络）。
"""
from __future__ import annotations

import os
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

# ---------------------------------------------------------------- 报价簿
# (组, 指数名, 指数新浪代码, 指数东财代码, 指数 parquet, ETF 代码, ETF 名, ETF parquet, QDII)
QUOTE_BOOK = [
    ("A股宽基", "沪深300", "sh000300", "000300", "index_daily/index_000300.parquet",
     "510310", "沪深300ETF", "etf_daily/etf_qfq_510310.parquet", False),
    ("A股宽基", "中证500", "sh000905", "000905", "index_daily/index_000905.parquet",
     "510580", "中证500ETF", "etf_daily/etf_qfq_510580.parquet", False),
    ("A股宽基", "中证1000", "sh000852", "000852", "index_daily/index_000852.parquet",
     "159633", "中证1000ETF", "etf_daily/etf_qfq_159633.parquet", False),
    ("A股宽基", "创业板指", "sz399006", "399006", "index_daily/index_399006.parquet",
     "159915", "创业板ETF", "etf_daily/etf_qfq_159915.parquet", False),
    ("A股宽基", "红利低波", None, "H30269", "index_daily/index_H30269.parquet",
     "563020", "红利低波ETF", "etf_daily/etf_qfq_563020.parquet", False),
    ("海外（QDII）", "标普500", None, None, "index_global/spx_inx.parquet",
     "513500", "标普500ETF", "etf_daily/etf_qfq_513500.parquet", True),
    ("海外（QDII）", "纳指100", None, None, "index_global/ndx_ndx.parquet",
     "513100", "纳指ETF", "etf_daily/etf_qfq_513100.parquet", True),
    ("海外（QDII）", "日经225", None, None, "index_global/n225_n225.parquet",
     "513880", "日经225ETF", "etf_daily/etf_qfq_513880.parquet", True),
    ("海外（QDII）", "恒生红利低波", None, None, "index_global/hshylv_nav_159545.parquet",
     "159545", "恒生红利低波ETF", "etf_daily/etf_qfq_159545.parquet", True),
    ("商品与债券", "黄金 AU9999", None, None, "gold/au9999_sge.parquet",
     "518880", "黄金ETF", "etf_daily/etf_qfq_518880.parquet", False),
    ("商品与债券", "国债财富7-10Y", None, None, "bond_index/cbond_treasury_wealth_7_10y.parquet",
     "511260", "十年国债ETF", "etf_daily/etf_qfq_511260.parquet", False),
    ("商品与债券", None, None, None, None,
     "511360", "短融ETF", "etf_daily/etf_qfq_511360.parquet", False),
]

_GROUPS = ["A股宽基", "海外（QDII）", "商品与债券"]


@dataclass
class Quote:
    """单条报价。live=False 即 parquet 收盘兜底，asof 为收盘日。"""
    name: str
    price: float | None = None
    change_pct: float | None = None   # 百分数口径：-0.45 = 跌 0.45%
    prev_close: float | None = None
    asof: str = ""
    source: str = ""
    live: bool = False


@dataclass
class MonitorRow:
    group: str
    index: Quote | None               # 511360 短融无对应指数 → None
    etf_code: str
    etf: Quote
    premium: float | None = None      # QDII 溢价率（百分数），非 QDII 为 None
    nav_date: str | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 实时抓取
def _offline() -> bool:
    return os.environ.get("PASEO_MARKET_OFFLINE") == "1"


def _sina_index_quotes(codes: list[str]) -> dict[str, Quote]:
    """新浪 A股指数批量快照。codes 为 sh000300 形式。"""
    import akshare as ak

    df = ak.stock_zh_index_spot_sina()
    df = df[df["代码"].isin(codes)]
    out = {}
    for _, r in df.iterrows():
        out[r["代码"]] = Quote(
            name=r["名称"], price=float(r["最新价"]), change_pct=float(r["涨跌幅"]),
            prev_close=float(r["昨收"]), asof=time.strftime("%Y-%m-%d %H:%M"),
            source="新浪实时", live=True)
    return out


def _em_index_quotes(codes: list[str]) -> dict[str, Quote]:
    """东财中证系列指数快照（补 H30269 等新浪没有的中证系）。codes 为 H30269 形式。"""
    import akshare as ak

    df = ak.stock_zh_index_spot_em(symbol="中证系列指数")
    df = df[df["代码"].isin(codes)]
    out = {}
    for _, r in df.iterrows():
        out[r["代码"]] = Quote(
            name=r["名称"], price=float(r["最新价"]), change_pct=float(r["涨跌幅"]),
            prev_close=float(r["昨收"]) if "昨收" in df.columns else None,
            asof=time.strftime("%Y-%m-%d %H:%M"), source="东财实时", live=True)
    return out


def _sina_etf_quotes(codes: list[str]) -> dict[str, Quote]:
    """新浪 hq.sinajs.cn ETF 批量快照（12 只全覆盖）。codes 为 510310 形式。"""
    import requests

    pref = ["sh" + c if c.startswith("5") else "sz" + c for c in codes]
    r = requests.get("https://hq.sinajs.cn/list=" + ",".join(pref),
                     headers={"Referer": "https://finance.sina.com.cn"}, timeout=8)
    r.encoding = "gbk"
    out = {}
    for line in r.text.strip().split("\n"):
        if "=" not in line or '""' in line:
            continue
        raw_code = line.split("=")[0].split("_")[-1]   # sh510310
        f = line.split('"')[1].split(",")
        # 股票/ETF 格式：f[0]=名称 f[1]=今开 f[2]=昨收 f[3]=最新价
        code = raw_code[2:]
        price, prev = float(f[3]), float(f[2])
        out[code] = Quote(
            name=f[0], price=price, prev_close=prev,
            change_pct=(price / prev - 1) * 100 if prev else None,
            asof=time.strftime("%Y-%m-%d %H:%M"), source="新浪实时", live=True)
    return out


def _em_etf_quotes(codes: list[str]) -> dict[str, Quote]:
    """东财 ETF 现货快照（备选）。"""
    import akshare as ak

    df = ak.fund_etf_spot_em()
    df = df[df["代码"].isin(codes)]
    out = {}
    for _, r in df.iterrows():
        out[r["代码"]] = Quote(
            name=r["名称"], price=float(r["最新价"]),
            change_pct=float(r["涨跌幅"]) if pd.notna(r["涨跌幅"]) else None,
            prev_close=float(r["昨收"]) if "昨收" in df.columns else None,
            asof=time.strftime("%Y-%m-%d %H:%M"), source="东财实时", live=True)
    return out


# ---------------------------------------------------------------- parquet 兜底
def _parquet_close(rel: str, name: str, col: str = "close") -> Quote:
    """读 parquet 最新两行算涨跌幅；文件缺失/不足两行则 price=None。"""
    p = RAW / rel
    if not p.exists():
        return Quote(name=name, source="无数据")
    df = pd.read_parquet(p)
    if col not in df.columns:  # au9999 为 bench_am/bench_pm 基准价口径
        col = "bench_pm" if "bench_pm" in df.columns else df.columns[-1]
    s = df[["date", col]].dropna()
    if s.empty:
        return Quote(name=name, source="无数据")
    last = s.iloc[-1]
    q = Quote(name=name, price=float(last[col]), asof=str(pd.Timestamp(last["date"]).date()),
              source="收盘(parquet)", live=False)
    if len(s) >= 2:
        prev = float(s.iloc[-2][col])
        q.prev_close = prev
        q.change_pct = (float(last[col]) / prev - 1) * 100 if prev else None
    return q


def _latest_nav(code: str) -> tuple[float, str] | None:
    """QDII 最新单位净值与日期（溢价=时点比率，须用单位净值而非累计净值）。"""
    p = RAW / "etf_nav" / f"nav_{code}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p).dropna(subset=["nav"])
    if df.empty:
        return None
    last = df.iloc[-1]
    return float(last["nav"]), str(pd.Timestamp(last["date"]).date())


# ---------------------------------------------------------------- 组装
def collect_quotes() -> list[MonitorRow]:
    """抓全部报价并组装成监控行。实时源批量抓取一次，失败的逐个 parquet 兜底。"""
    idx_sina = [b[2] for b in QUOTE_BOOK if b[2]]
    etf_codes = [b[5] for b in QUOTE_BOOK]

    live_idx: dict[str, Quote] = {}
    live_etf: dict[str, Quote] = {}
    if not _offline():
        try:
            live_idx.update(_sina_index_quotes(idx_sina))
        except Exception:
            pass
        # 东财补漏：新浪没有的（H30269）+ 新浪整体失败时的其余中证系
        missing_em = [b[3] for b in QUOTE_BOOK if b[3] and (b[2] or b[3]) not in live_idx]
        if missing_em:
            try:
                live_idx.update(_em_index_quotes(missing_em))
            except Exception:
                pass
        try:
            live_etf = _sina_etf_quotes(etf_codes)
        except Exception:
            pass
        missing_etf = [c for c in etf_codes if c not in live_etf]
        if missing_etf:
            try:
                live_etf.update(_em_etf_quotes(missing_etf))
            except Exception:
                pass

    rows: list[MonitorRow] = []
    for (group, idx_name, idx_sina_code, idx_em_code, idx_pq,
         etf_code, etf_name, etf_pq, qdii) in QUOTE_BOOK:
        # 指数侧：海外/商品/债券无实时源设计（对中国用户即昨夜收盘），直接 EOD
        idx_q = None
        if idx_name:
            key = idx_sina_code or idx_em_code
            idx_q = live_idx.get(key) if key else None
            if idx_q is None:
                idx_q = _parquet_close(idx_pq, idx_name)
            idx_q.name = idx_name
        # ETF 侧
        etf_q = live_etf.get(etf_code)
        if etf_q is None:
            etf_q = _parquet_close(etf_pq, etf_name)
        etf_q.name = etf_name

        premium, nav_date = None, None
        if qdii:
            nav = _latest_nav(etf_code)
            if nav and etf_q.price:
                premium = (etf_q.price / nav[0] - 1) * 100
                nav_date = nav[1]
        rows.append(MonitorRow(group=group, index=idx_q, etf_code=etf_code,
                               etf=etf_q, premium=premium, nav_date=nav_date))
    return rows


def groups_of(rows: list[MonitorRow]) -> dict[str, list[MonitorRow]]:
    """按报价簿分组顺序分组。"""
    return {g: [r for r in rows if r.group == g] for g in _GROUPS}
