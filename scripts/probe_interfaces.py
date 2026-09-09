"""小样本试跑各 AKShare 接口，打印列名与样例行，确认列结构。"""
import traceback
import akshare as ak
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)


def probe(name, fn, **kw):
    print(f"\n{'='*70}\n### {name}")
    try:
        df = fn(**kw)
        print("shape:", df.shape)
        print("columns:", list(df.columns))
        print(df.head(2).to_string())
        print(df.tail(2).to_string())
    except Exception as e:
        print("FAILED:", repr(e))
        traceback.print_exc(limit=1)


probe("index_zh_a_hist 000300", ak.index_zh_a_hist, symbol="000300", period="daily",
      start_date="20050101", end_date="20050201")
probe("index_zh_a_hist H30269", ak.index_zh_a_hist, symbol="H30269", period="daily",
      start_date="20050101", end_date="20050201")
probe("index_us_stock_sina .INX", ak.index_us_stock_sina, symbol=".INX")
probe("fund_etf_hist_em 510310 qfq", ak.fund_etf_hist_em, symbol="510310", period="daily",
      start_date="20130101", end_date="20130201", adjust="qfq")
probe("fund_etf_fund_info_em 513500", ak.fund_etf_fund_info_em, fund="513500",
      start_date="20140101", end_date="20140201")
probe("index_value_hist_funddb 沪深300 市盈率", ak.index_value_hist_funddb,
      symbol="沪深300", indicator="市盈率")
probe("bond_china_yield", ak.bond_china_yield, start_date="20240101", end_date="20240201")
probe("index_option_50etf_qvix", ak.index_option_50etf_qvix)
probe("index_option_300etf_qvix", ak.index_option_300etf_qvix)
probe("currency_boc_safe 美元", ak.currency_boc_safe, symbol="美元",
      start_date="20240101", end_date="20240201")
probe("spot_golden_benchmark_sge", ak.spot_golden_benchmark_sge)
probe("futures_main_sina AU0", ak.futures_main_sina, symbol="AU0",
      start_date="20240101", end_date="20240201")
probe("bond_china_close_return", ak.bond_china_close_return, period="3",
      start_date="20240101", end_date="20240201")
probe("tool_trade_date_hist_sina", ak.tool_trade_date_hist_sina)
