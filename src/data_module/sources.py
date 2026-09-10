"""数据清单登记表：覆盖设计文档第四节的全部条目。

每个数据集 = 名称 / raw 相对路径 / 抓取函数 / 备注。
抓取函数返回 FetchResult(df, source, adjust, note)，df 已按 storage.standardize 标准化。
东财接口在当前网络不稳定，凡有替代接口的都带兜底链（primary → fallback），
实际使用的来源会写进 meta 的 source_interface / note。
"""
import datetime as dt
import re
import time
from dataclasses import dataclass, field

import akshare as ak
import pandas as pd
import requests

from .net import retry_fetch

TODAY = dt.date.today().strftime("%Y%m%d")


@dataclass
class FetchResult:
    df: pd.DataFrame
    source: str          # 实际使用的来源接口
    adjust: str = ""     # 复权方式
    note: str = ""       # 口径/兜底说明


@dataclass
class Dataset:
    name: str
    rel_path: str        # 相对 data/raw/
    fetcher: object      # Callable[[], FetchResult]
    note: str = ""


def _try_chain(steps: list) -> FetchResult:
    """按顺序尝试 (说明, callable)；callable 返回 FetchResult，空表或异常则试下一个。"""
    errors = []
    for _label, fn in steps:
        try:
            res = fn()
            if res.df is not None and len(res.df) > 0:
                return res
            errors.append(f"{res.source}: 返回空表")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{_label}: {type(e).__name__} {str(e)[:80]}")
    raise RuntimeError("抓取链全部失败 -> " + " | ".join(errors))


def _std(df: pd.DataFrame, col_map: dict, keep_cols: list) -> pd.DataFrame:
    """标准化（重命名/日期/排序/去重），与 storage.standardize 同逻辑，避免循环引用。"""
    from .storage import standardize

    return standardize(df, col_map, keep_cols)


# ---------------------------------------------------------------- A 股指数日线
# 东财 index_zh_a_hist 中文列映射
_EM_IDX_MAP = {
    "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
    "收盘": "close", "成交量": "volume", "成交额": "amount",
}
_OHLCV = ["date", "open", "high", "low", "close", "volume", "amount"]


def _fetch_index_daily(code: str) -> FetchResult:
    """A股指数日线：东财 index_zh_a_hist 为主，新浪/中证官网兜底。"""

    def primary() -> FetchResult:
        # 东财当前网络不稳定，首选源只快试 3 次即走兜底（兜底源有全历史）
        df = retry_fetch(ak.index_zh_a_hist, symbol=code, period="daily",
                         start_date="20050101", end_date=TODAY,
                         retries=3, base_sleep=1.5)
        return FetchResult(_std(df, _EM_IDX_MAP, _OHLCV),
                           source=f"index_zh_a_hist({code})", adjust="无（指数）")

    def fb_sina() -> FetchResult:  # 沪深交易所指数（无成交额列）
        prefix = "sh" if code.startswith("0") else "sz"
        df = retry_fetch(ak.stock_zh_index_daily, symbol=prefix + code)
        df["amount"] = pd.NA
        return FetchResult(_std(df, {}, _OHLCV),
                           source=f"stock_zh_index_daily({prefix}{code})",
                           adjust="无（指数）", note="东财接口不可用，新浪兜底（无成交额）")

    def fb_csindex() -> FetchResult:  # 中证系指数（H30269 等，新浪没有）
        df = retry_fetch(ak.stock_zh_index_hist_csindex, symbol=code,
                         start_date="20050101", end_date=TODAY)
        col_map = {"日期": "date", "开盘": "open", "最高": "high", "最低": "low",
                   "收盘": "close", "成交量": "volume", "成交金额": "amount"}
        return FetchResult(_std(df, col_map, _OHLCV),
                           source=f"stock_zh_index_hist_csindex({code})",
                           adjust="无（指数）", note="东财接口不可用，中证官网兜底")

    steps = [("em", primary)]
    # 中证系指数（H30269/H30533、93xxxx 等）新浪没有 → 中证官网兜底
    steps.append(("csindex", fb_csindex) if code.startswith(("H", "9")) else ("sina", fb_sina))
    return _try_chain(steps)


# ---------------------------------------------------------------- 海外指数
def _fetch_global_index(symbol: str, tag: str, sina_name: str | None = None,
                        em_name: str | None = None) -> FetchResult:
    steps = []
    if em_name:  # 东财全球指数（历史最长，但当前网络不稳，优先尝试）
        def em() -> FetchResult:
            df = retry_fetch(ak.index_global_hist_em, symbol=em_name,
                             retries=4, base_sleep=2.0)
            col_map = {"日期": "date", "开盘": "open", "最高": "high", "最低": "low",
                       "收盘": "close", "成交量": "volume", "成交额": "amount"}
            col_map = {k: v for k, v in col_map.items() if k in df.columns}
            df = df.rename(columns=col_map)
            if "amount" not in df.columns:
                df["amount"] = pd.NA
            if "volume" not in df.columns:
                df["volume"] = pd.NA
            return FetchResult(_std(df, {}, _OHLCV),
                               source=f"index_global_hist_em({em_name})",
                               adjust="无（指数）", note="本币计价")
        steps.append(("em", em))

    def fn() -> FetchResult:
        df = retry_fetch(ak.index_us_stock_sina, symbol=symbol)
        return FetchResult(_std(df, {}, _OHLCV),
                           source=f"index_us_stock_sina({symbol})",
                           adjust="无（指数）", note="本币计价")

    steps.append((tag, fn))
    if sina_name:  # index_us_stock_sina 只覆盖美股指数，日经等走新浪环球兜底
        def fb() -> FetchResult:
            df = retry_fetch(ak.index_global_hist_sina, symbol=sina_name)
            df["amount"] = pd.NA
            return FetchResult(_std(df, {}, _OHLCV),
                               source=f"index_global_hist_sina({sina_name})",
                               adjust="无（指数）",
                               note="本币计价；index_us_stock_sina 无此指数，新浪环球兜底（无成交额、历史仅约 4 年）")
        steps.append(("sina_global", fb))
    return _try_chain(steps)


def _fetch_hshylv() -> FetchResult:
    """恒生红利低波 HSHYLV：东财全球指数表无此代码，按设计文档用 159545 净值兜底。"""
    def fn() -> FetchResult:
        df = retry_fetch(ak.fund_etf_fund_info_em, fund="159545",
                         start_date="20000101", end_date=TODAY)
        col_map = {"净值日期": "date", "单位净值": "close", "累计净值": "acc_nav"}
        return FetchResult(_std(df, col_map, ["date", "close", "acc_nav"]),
                           source="fund_etf_fund_info_em(159545)", adjust="基金净值",
                           note="HSHYLV 无可用指数接口，用 159545 净值兜底（净值天然无溢价；历史仅覆盖基金成立后）")
    return _try_chain([("nav", fn)])


def _fetch_spdiv50() -> FetchResult:
    """标普中国A股红利机会指数（515450 标的）：标普指数无公开日线接口，用 515450 净值兜底。"""
    def fn() -> FetchResult:
        df = retry_fetch(ak.fund_etf_fund_info_em, fund="515450",
                         start_date="20000101", end_date=TODAY)
        col_map = {"净值日期": "date", "单位净值": "close", "累计净值": "acc_nav"}
        return FetchResult(_std(df, col_map, ["date", "close", "acc_nav"]),
                           source="fund_etf_fund_info_em(515450)", adjust="基金净值",
                           note="标普红利机会指数无可用指数接口，用 515450 净值兜底（与 HSHYLV 同律；历史仅覆盖基金成立后）")
    return _try_chain([("nav", fn)])


# ---------------------------------------------------------------- ETF 前复权日线
def _tx_code(code: str) -> str:
    return ("sh" if code.startswith("5") else "sz") + code


def _fetch_etf_qfq(code: str) -> FetchResult:
    """ETF 前复权日线：东财 fund_etf_hist_em(adjust=qfq) 为主，腾讯 qfq 兜底。"""

    def primary() -> FetchResult:
        # 东财当前网络不稳定，首选源只快试 3 次即走腾讯兜底
        df = retry_fetch(ak.fund_etf_hist_em, symbol=code, period="daily",
                         start_date="20000101", end_date=TODAY, adjust="qfq",
                         retries=3, base_sleep=1.5)
        return FetchResult(_std(df, _EM_IDX_MAP, _OHLCV),
                           source=f"fund_etf_hist_em({code})", adjust="qfq 前复权")

    def fb_tx() -> FetchResult:
        df = retry_fetch(ak.stock_zh_a_hist_tx, symbol=_tx_code(code),
                         start_date="20000101", end_date=TODAY, adjust="qfq")
        return FetchResult(_std(df, {}, _OHLCV),
                           source=f"stock_zh_a_hist_tx({_tx_code(code)})",
                           adjust="qfq 前复权", note="东财接口不可用，腾讯行情兜底")

    return _try_chain([("em", primary), ("tencent", fb_tx)])


# ---------------------------------------------------------------- QDII 净值
def _fetch_etf_nav(code: str) -> FetchResult:
    def fn() -> FetchResult:
        df = retry_fetch(ak.fund_etf_fund_info_em, fund=code,
                         start_date="20000101", end_date=TODAY)
        col_map = {"净值日期": "date", "单位净值": "nav",
                   "累计净值": "acc_nav", "日增长率": "daily_growth"}
        return FetchResult(_std(df, col_map, ["date", "nav", "acc_nav", "daily_growth"]),
                           source=f"fund_etf_fund_info_em({code})", adjust="基金净值",
                           note="溢价过滤器数据源")
    return _try_chain([("em", fn)])


# ---------------------------------------------------------------- 估值（乐咕 + 中证官网）
def _fetch_pe_lg(index_name: str) -> FetchResult:
    """指数 PE 全历史。设计文档原接口 index_value_hist_funddb 已从 akshare 移除，改用乐咕。"""
    def fn() -> FetchResult:
        df = retry_fetch(ak.stock_index_pe_lg, symbol=index_name)
        col_map = {"日期": "date", "指数": "index_close",
                   "静态市盈率": "pe_static", "等权静态市盈率": "pe_static_eq",
                   "静态市盈率中位数": "pe_static_median",
                   "滚动市盈率": "pe_ttm", "等权滚动市盈率": "pe_ttm_eq",
                   "滚动市盈率中位数": "pe_ttm_median"}
        return FetchResult(_std(df, col_map, list(col_map.values())),
                           source=f"stock_index_pe_lg({index_name})", adjust="不适用",
                           note="funddb 接口已下线，乐咕兜底；pe_ttm=滚动市盈率")
    return _try_chain([("legu", fn)])


def _fetch_pb_lg(index_name: str) -> FetchResult:
    def fn() -> FetchResult:
        df = retry_fetch(ak.stock_index_pb_lg, symbol=index_name)
        col_map = {"日期": "date", "指数": "index_close", "市净率": "pb",
                   "等权市净率": "pb_eq", "市净率中位数": "pb_median"}
        return FetchResult(_std(df, col_map, list(col_map.values())),
                           source=f"stock_index_pb_lg({index_name})", adjust="不适用",
                           note="funddb 接口已下线，乐咕兜底")
    return _try_chain([("legu", fn)])


def _fetch_dividend_csindex(code: str) -> FetchResult:
    """中证官网估值快照（仅近一个月，靠每日增量追加逐步积累历史）。"""
    def fn() -> FetchResult:
        df = retry_fetch(ak.stock_zh_index_value_csindex, symbol=code)
        col_map = {"日期": "date", "市盈率1": "pe1", "市盈率2": "pe2",
                   "股息率1": "div_yield_1", "股息率2": "div_yield_2"}
        keep = ["date", "pe1", "pe2", "div_yield_1", "div_yield_2"]
        return FetchResult(_std(df, col_map, keep),
                           source=f"stock_zh_index_value_csindex({code})", adjust="不适用",
                           note="中证官网仅提供近月快照，重跑 update 逐日积累")
    return _try_chain([("csindex", fn)])


def _fetch_dividend_all_a() -> FetchResult:
    def fn() -> FetchResult:
        df = retry_fetch(ak.stock_a_gxl_lg)
        return FetchResult(_std(df, {"日期": "date", "股息率": "div_yield"},
                              ["date", "div_yield"]),
                           source="stock_a_gxl_lg", adjust="不适用",
                           note="全 A 股息率（非单指数），供长历史参考")
    return _try_chain([("legu", fn)])


# ---------------------------------------------------------------- 利率：10Y 国债
def _fetch_cn10y() -> FetchResult:
    """中债国债收益率曲线，按月分块抓全历史，全期限保留（3M–30Y 共 9 列，绝对动量基准需要 3M）。"""
    def fn() -> FetchResult:
        chunks = []
        start = dt.date(2006, 1, 1)
        end = dt.date.today()
        cur = start
        while cur <= end:
            month_end = (cur.replace(day=28) + dt.timedelta(days=10)).replace(day=1) - dt.timedelta(days=1)
            month_end = min(month_end, end)
            df = retry_fetch(ak.bond_china_yield,
                             start_date=cur.strftime("%Y%m%d"),
                             end_date=month_end.strftime("%Y%m%d"),
                             retries=5, base_sleep=1.0)
            chunks.append(df)
            cur = month_end + dt.timedelta(days=1)
        df = pd.concat(chunks, ignore_index=True)
        df = df[df["曲线名称"] == "中债国债收益率曲线"]
        col_map = {"日期": "date", "3月": "yield_3m", "6月": "yield_6m",
                   "1年": "yield_1y", "3年": "yield_3y", "5年": "yield_5y",
                   "7年": "yield_7y", "10年": "yield_10y", "30年": "yield_30y"}
        keep = list(col_map.values())
        return FetchResult(_std(df, col_map, keep),
                           source="bond_china_yield(中债国债收益率曲线)", adjust="不适用",
                           note="工作日频率，单位 %，全期限 3M/6M/1Y/3Y/5Y/7Y/10Y/30Y")
    return _try_chain([("chinamoney", fn)])


# ---------------------------------------------------------------- QVIX
def _fetch_qvix(which: str) -> FetchResult:
    fn_api = {"50etf": ak.index_option_50etf_qvix,
              "300etf": ak.index_option_300etf_qvix}[which]

    def fn() -> FetchResult:
        df = retry_fetch(fn_api)
        return FetchResult(_std(df, {}, ["date", "open", "high", "low", "close"]),
                           source=f"index_option_{which}_qvix", adjust="不适用")
    return _try_chain([("qvix", fn)])


# ---------------------------------------------------------------- 汇率
def _fetch_fx(currency: str, per: float) -> FetchResult:
    """中国银行外汇牌价（每 100 外币兑人民币），换算为每 1 外币兑人民币。"""
    def fn() -> FetchResult:
        df = retry_fetch(ak.currency_boc_safe)
        out = pd.DataFrame({"date": pd.to_datetime(df["日期"]),
                            "close": pd.to_numeric(df[currency], errors="coerce") / per})
        out = out.dropna()
        return FetchResult(_std(out, {}, ["date", "close"]),
                           source=f"currency_boc_safe({currency})", adjust="不适用",
                           note="中行牌价中间价/100，每 1 外币兑人民币")
    return _try_chain([("boc", fn)])


# ---------------------------------------------------------------- 黄金
def _fetch_au9999() -> FetchResult:
    def fn() -> FetchResult:
        df = retry_fetch(ak.spot_golden_benchmark_sge)
        col_map = {"交易时间": "date", "早盘价": "bench_am", "晚盘价": "bench_pm"}
        return FetchResult(_std(df, col_map, ["date", "bench_am", "bench_pm"]),
                           source="spot_golden_benchmark_sge", adjust="不适用",
                           note="上金所 AU9999 早盘/晚盘基准价")
    return _try_chain([("sge", fn)])


def _fetch_au_main() -> FetchResult:
    def fn() -> FetchResult:
        df = retry_fetch(ak.futures_main_sina, symbol="AU0",
                         start_date="20080101", end_date=TODAY)
        col_map = {"日期": "date", "开盘价": "open", "最高价": "high", "最低价": "low",
                   "收盘价": "close", "成交量": "volume", "持仓量": "open_interest",
                   "动态结算价": "settle"}
        keep = ["date", "open", "high", "low", "close", "volume", "open_interest", "settle"]
        return FetchResult(_std(df, col_map, keep),
                           source="futures_main_sina(AU0)", adjust="主力连续",
                           note="沪金主力连续合约")
    return _try_chain([("sina", fn)])


# ---------------------------------------------------------------- 债券指数
def _fetch_bond_index() -> FetchResult:
    """中债-国债财富指数（7-10 年段），用于拼接 511260 上市前的债券腿。

    设计文档原接口 bond_china_close_return 在新版 akshare 已损坏且语义为收益率曲线，
    改用 bond_treasury_index_cbond（中国债券信息网）。511260 跟踪上证 10 年期国债指数
    （样本剩余期限约 7-10 年），故取 period="7-10Y"、indicator="财富"（总回报口径）。
    """
    def fn() -> FetchResult:
        df = retry_fetch(ak.bond_treasury_index_cbond, indicator="财富", period="7-10Y")
        return FetchResult(_std(df, {"value": "close"}, ["date", "close"]),
                           source="bond_treasury_index_cbond(财富,7-10Y)", adjust="不适用",
                           note="替代设计文档的 bond_china_close_return（该接口已失效）")
    return _try_chain([("cbond", fn)])


# ---------------------------------------------------------------- 交易日历
def _fetch_calendar() -> FetchResult:
    def fn() -> FetchResult:
        df = retry_fetch(ak.tool_trade_date_hist_sina)
        return FetchResult(_std(df, {"trade_date": "date"}, ["date"]),
                           source="tool_trade_date_hist_sina", adjust="不适用")
    return _try_chain([("sina", fn)])


# ---------------------------------------------------------------- CMV 复刻:两融余额
def _fetch_margin() -> FetchResult:
    """沪深两融合并余额(日频)。CMV Margin Debt 模型数据源。

    macro_china_market_margin_sh/_sz 均为东财接口,2010-03-31 起;两所同日都有
    才保留(inner merge),避免单边缺失日余额被低估。
    """
    def fn() -> FetchResult:
        sh = retry_fetch(ak.macro_china_market_margin_sh)
        sz = retry_fetch(ak.macro_china_market_margin_sz)
        sh = sh[["日期", "融资融券余额"]].rename(columns={"融资融券余额": "bal_sh"})
        sz = sz[["日期", "融资融券余额"]].rename(columns={"融资融券余额": "bal_sz"})
        df = sh.merge(sz, on="日期", how="inner")
        df["margin_bal"] = df["bal_sh"] + df["bal_sz"]  # 元
        df["date"] = pd.to_datetime(df["日期"])
        out = df[["date", "margin_bal"]].sort_values("date")
        return FetchResult(_std(out, {}, ["date", "margin_bal"]),
                           source="macro_china_market_margin_sh+sz",
                           adjust="不适用", note="沪深两融合并(仅同日双边齐全日),单位元")
    return _try_chain([("em", fn)])


# ---------------------------------------------------------------- CMV 复刻:中短票AAA曲线
def _fetch_credit_aaa() -> FetchResult:
    """中债中短期票据收益率曲线(AAA),信用利差卡(CMV Junk Bond Spreads 代理)。

    与 _fetch_cn10y 同按月分块抓全历史(bond_china_yield 单次请求限制日期跨度),
    只保留 AAA 中短票曲线的 3Y/10Y 两列。中国无高收益债长历史源,用 AAA 利差代理。
    """
    def fn() -> FetchResult:
        chunks = []
        start = dt.date(2006, 1, 1)
        end = dt.date.today()
        cur = start
        while cur <= end:
            month_end = (cur.replace(day=28) + dt.timedelta(days=10)).replace(day=1) - dt.timedelta(days=1)
            month_end = min(month_end, end)
            df = retry_fetch(ak.bond_china_yield,
                             start_date=cur.strftime("%Y%m%d"),
                             end_date=month_end.strftime("%Y%m%d"),
                             retries=5, base_sleep=1.0)
            chunks.append(df)
            cur = month_end + dt.timedelta(days=1)
        df = pd.concat(chunks, ignore_index=True)
        df = df[df["曲线名称"] == "中债中短期票据收益率曲线(AAA)"]
        col_map = {"日期": "date", "3年": "ts_aaa_3y", "10年": "ts_aaa_10y"}
        keep = list(col_map.values())
        return FetchResult(_std(df, col_map, keep),
                           source="bond_china_yield(中债中短期票据收益率曲线AAA)",
                           adjust="不适用", note="单位 %,工作日频率;AAA 利差为高收益利差代理")
    return _try_chain([("chinamoney", fn)])


# ---------------------------------------------------------------- CMV 复刻:全A总市值(月度)
_EM_DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _fetch_a_market_cap() -> FetchResult:
    """A股两市总市值(月度)。CMV Buffett Indicator 分子。

    东财数据中心 RPT_ECONOMY_STOCK_STATISTICS:月度 2008-01 起,一次调用全历史,
    含上交所/深交所总市值(TOTAL_MARKE_SH/SZ,单位亿元)。交易所官网接口无长历史
    (上交所日度 commonQuery 仅近月,已验证),此接口是唯一现成长源。
    """
    def fn() -> FetchResult:
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                r = requests.get(_EM_DC_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"},
                                 params={"reportName": "RPT_ECONOMY_STOCK_STATISTICS",
                                         "columns": "ALL", "pageNumber": 1, "pageSize": 500,
                                         "sortColumns": "REPORT_DATE", "sortTypes": -1})
                data = (r.json().get("result") or {}).get("data") or []
                if not data:
                    raise RuntimeError("datacenter 返回空表")
                df = pd.DataFrame(data)
                df["date"] = pd.to_datetime(df["REPORT_DATE"])
                df = df.rename(columns={"TOTAL_MARKE_SH": "mv_sh", "TOTAL_MARKE_SZ": "mv_sz"})
                df["mv_sh"] = pd.to_numeric(df["mv_sh"], errors="coerce")
                df["mv_sz"] = pd.to_numeric(df["mv_sz"], errors="coerce")
                df["mv_total"] = df["mv_sh"] + df["mv_sz"]  # 亿元
                out = df[["date", "mv_sh", "mv_sz", "mv_total"]]
                return FetchResult(_std(out, {}, ["date", "mv_sh", "mv_sz", "mv_total"]),
                                   source="datacenter RPT_ECONOMY_STOCK_STATISTICS",
                                   adjust="不适用", note="月度,单位亿元;最新月可能为 NaN(未出数)")
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"全A总市值抓取失败: {last_err}")
    return _try_chain([("em_datacenter", fn)])


# ---------------------------------------------------------------- CMV 复刻:EPU/失业率/PMI(月频)
def _fetch_epu_china() -> FetchResult:
    """中国 EPU(经济政策不确定性)指数,月频。CMV #14。

    akshare article_epu_index 转 policyuncertainty.com 官方数据,1995-01 起;
    注意官方更新停滞(当前止于 2023-11),读数滞后约 3 年,卡面需声明。
    """
    def fn() -> FetchResult:
        df = retry_fetch(ak.article_epu_index, symbol="China")
        df["date"] = pd.to_datetime(dict(year=df["year"], month=df["month"], day=1))
        df["epu"] = pd.to_numeric(df["China_Policy_Index"], errors="coerce")
        out = df[["date", "epu"]].dropna()
        return FetchResult(_std(out, {}, ["date", "epu"]),
                           source="article_epu_index(China)", adjust="不适用",
                           note="policyuncertainty.com 中国月度 EPU;官方更新停滞,读数滞后")
    return _try_chain([("epu", fn)])


def _fetch_unemployment() -> FetchResult:
    """全国城镇调查失业率,月频。CMV #9 Sahm Rule 数据源。

    macro_china_urban_unemployment 为长表,item 列带尾部空格(实测),须 strip 后筛选。
    """
    def fn() -> FetchResult:
        df = retry_fetch(ak.macro_china_urban_unemployment)
        df["item"] = df["item"].str.strip()
        nat = df[df["item"] == "全国城镇调查失业率"].copy()
        nat["date"] = pd.to_datetime(nat["date"], format="%Y%m") + pd.offsets.MonthEnd(0)
        nat["urate"] = pd.to_numeric(nat["value"], errors="coerce")
        out = nat[["date", "urate"]].dropna()
        return FetchResult(_std(out, {}, ["date", "urate"]),
                           source="macro_china_urban_unemployment", adjust="不适用",
                           note="全国城镇调查失业率(%),2018-01 起,样本短")
    return _try_chain([("em", fn)])


_PMI_MONTH_RE = re.compile(r"(\d{4})年(\d{2})月份?")


def _fetch_pmi_official() -> FetchResult:
    """官方制造业 PMI,月频。CMV #8 LEI 的降级替代(对标自身 12M 均线)。

    财新 PMI 接口(index_pmi_man_cx)实测不通;官方 PMI 2008-01 起更长,用它替代
    Conference Board LEI 的对标均线判读。
    """
    def fn() -> FetchResult:
        df = retry_fetch(ak.macro_china_pmi)
        m = df["月份"].astype(str).str.extract(_PMI_MONTH_RE)
        df["date"] = pd.to_datetime(m[0] + "-" + m[1] + "-01") + pd.offsets.MonthEnd(0)
        df["pmi"] = pd.to_numeric(df["制造业-指数"], errors="coerce")
        out = df[["date", "pmi"]].dropna()
        return FetchResult(_std(out, {}, ["date", "pmi"]),
                           source="macro_china_pmi", adjust="不适用",
                           note="官方制造业 PMI;LEI 降级替代(对标 12M 均线)")
    return _try_chain([("em", fn)])


# ---------------------------------------------------------------- CMV 复刻:GDP(季度)
_GDP_Q_RE = re.compile(r"(\d{4})年第(\d)(?:-(\d))?季度")


def _fetch_gdp() -> FetchResult:
    """GDP 季度累计值(亿元)。CMV Buffett Indicator 分母。

    macro_china_gdp 的"第1-2季度"为年内累计口径,转季末日期;卡内做滚动四季度
    求和得近四季 GDP。1992 年起,2026 年改接口后实测 2006 起。
    """
    def fn() -> FetchResult:
        df = retry_fetch(ak.macro_china_gdp)
        m = df["季度"].astype(str).str.extract(_GDP_Q_RE)
        df["date"] = pd.to_datetime(
            m[0] + "-" + (m[2].fillna(m[1]).astype(int) * 3).astype(str) + "-01")
        df["date"] = df["date"] + pd.offsets.MonthEnd(0)
        df["gdp_cum"] = pd.to_numeric(df["国内生产总值-绝对值"], errors="coerce")
        out = df[["date", "gdp_cum"]].dropna()
        return FetchResult(_std(out, {}, ["date", "gdp_cum"]),
                           source="macro_china_gdp", adjust="不适用",
                           note="季度累计值(亿元),滚动四季度求和由卡内完成")
    return _try_chain([("em", fn)])


# ================================================================ 注册表
_A_INDEX = ["000300", "000905", "000852", "399006", "H30269",
            "930955", "931139", "H30533"]
_ETFS = ["510310", "510580", "159633", "159915", "563020", "513500",
         "513100", "513880", "518880", "159545", "511260", "511360",
         "515450", "159307", "515650", "513050"]
_QDII = ["513500", "513100", "513880", "159545", "513050"]

DATASETS: list[Dataset] = [
    # A股指数日线 ×5
    *[Dataset(f"index_{c}", f"index_daily/index_{c}.parquet",
              lambda c=c: _fetch_index_daily(c), "A股指数日线") for c in _A_INDEX],
    # 海外指数 ×4（HSHYLV 用 159545 净值兜底）
    Dataset("spx", "index_global/spx_inx.parquet",
            lambda: _fetch_global_index(".INX", "spx"), "标普500，美元计价"),
    Dataset("ndx", "index_global/ndx_ndx.parquet",
            lambda: _fetch_global_index(".NDX", "ndx"), "纳指100，美元计价"),
    Dataset("n225", "index_global/n225_n225.parquet",
            lambda: _fetch_global_index(".N225", "n225", sina_name="日经225指数",
                                        em_name="日经225"),
            "日经225，日元计价"),
    Dataset("hshylv", "index_global/hshylv_nav_159545.parquet",
            _fetch_hshylv, "恒生红利低波，159545 净值兜底"),
    Dataset("spdiv50", "index_daily/spdiv50_nav_515450.parquet",
            _fetch_spdiv50, "标普中国A股红利机会，515450 净值兜底"),
    # ETF 前复权日线 ×16
    *[Dataset(f"etf_qfq_{c}", f"etf_daily/etf_qfq_{c}.parquet",
              lambda c=c: _fetch_etf_qfq(c), "ETF 前复权日线") for c in _ETFS],
    # QDII 净值 ×5
    *[Dataset(f"nav_{c}", f"etf_nav/nav_{c}.parquet",
              lambda c=c: _fetch_etf_nav(c), "QDII 净值") for c in _QDII],
    # 估值：PE/PB（乐咕）+ 股息率快照（中证官网）+ 全A股息率
    Dataset("pe_000300", "valuation/pe_000300.parquet",
            lambda: _fetch_pe_lg("沪深300"), "沪深300 PE"),
    Dataset("pe_000905", "valuation/pe_000905.parquet",
            lambda: _fetch_pe_lg("中证500"), "中证500 PE"),
    Dataset("pb_000300", "valuation/pb_000300.parquet",
            lambda: _fetch_pb_lg("沪深300"), "沪深300 PB"),
    Dataset("pb_000905", "valuation/pb_000905.parquet",
            lambda: _fetch_pb_lg("中证500"), "中证500 PB"),
    Dataset("dividend_000300", "valuation/dividend_000300.parquet",
            lambda: _fetch_dividend_csindex("000300"), "沪深300 股息率（快照积累）"),
    Dataset("dividend_000905", "valuation/dividend_000905.parquet",
            lambda: _fetch_dividend_csindex("000905"), "中证500 股息率（快照积累）"),
    Dataset("dividend_all_a", "valuation/dividend_all_a.parquet",
            _fetch_dividend_all_a, "全A股息率长历史"),
    # 利率
    Dataset("cn10y", "rates/cn10y.parquet", _fetch_cn10y, "中债国债收益率曲线（3M–30Y 全期限）"),
    # QVIX ×2
    Dataset("qvix_50etf", "qvix/qvix_50etf.parquet",
            lambda: _fetch_qvix("50etf"), "50ETF QVIX"),
    Dataset("qvix_300etf", "qvix/qvix_300etf.parquet",
            lambda: _fetch_qvix("300etf"), "300ETF QVIX"),
    # 汇率 ×3
    Dataset("usdcny", "fx/usdcny.parquet", lambda: _fetch_fx("美元", 100.0), "美元/人民币"),
    Dataset("jpycny", "fx/jpycny.parquet", lambda: _fetch_fx("日元", 100.0), "日元/人民币"),
    Dataset("hkdcny", "fx/hkdcny.parquet", lambda: _fetch_fx("港元", 100.0), "港元/人民币"),
    # 黄金 ×2
    Dataset("au9999", "gold/au9999_sge.parquet", _fetch_au9999, "AU9999 基准价"),
    Dataset("au_main", "gold/au_main_sina.parquet", _fetch_au_main, "沪金主力连续"),
    # 债券指数
    Dataset("bond_index", "bond_index/cbond_treasury_wealth_7_10y.parquet",
            _fetch_bond_index, "中债国债财富指数 7-10Y"),
    # CMV 复刻:两融/信用利差/总市值/GDP
    Dataset("margin", "margin/margin_total.parquet", _fetch_margin, "沪深两融合并余额"),
    Dataset("credit_aaa", "rates/credit_ts_aaa.parquet",
            _fetch_credit_aaa, "中债中短期票据收益率曲线 AAA(3Y/10Y)"),
    Dataset("a_market_cap", "valuation/a_market_cap.parquet",
            _fetch_a_market_cap, "A股两市总市值(月度,亿元)"),
    Dataset("gdp", "macro/gdp_quarterly.parquet", _fetch_gdp, "GDP 季度累计值(亿元)"),
    Dataset("epu_china", "macro/epu_china.parquet", _fetch_epu_china, "中国 EPU 指数(月度)"),
    Dataset("unemployment", "macro/urban_unemployment.parquet",
            _fetch_unemployment, "全国城镇调查失业率(月度)"),
    Dataset("pmi_official", "macro/pmi_official.parquet",
            _fetch_pmi_official, "官方制造业 PMI(月度)"),
    # 交易日历
    Dataset("calendar", "calendar.parquet", _fetch_calendar, "A股交易日历"),
]

BY_NAME = {d.name: d for d in DATASETS}
