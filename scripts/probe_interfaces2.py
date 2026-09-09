"""小样本试跑（第二轮）：剩余接口 + 估值接口替代方案。"""
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
    except Exception:
        print("FAILED:", traceback.format_exc(limit=2))


probe("stock_zh_index_value_csindex 000300", ak.stock_zh_index_value_csindex, symbol="000300")
probe("stock_zh_index_value_csindex 000905", ak.stock_zh_index_value_csindex, symbol="000905")
probe("stock_index_pe_lg 沪深300", ak.stock_index_pe_lg, symbol="沪深300")
probe("bond_china_yield", ak.bond_china_yield, start_date="20240101", end_date="20240201")
probe("index_option_50etf_qvix", ak.index_option_50etf_qvix)
probe("index_option_300etf_qvix", ak.index_option_300etf_qvix)
probe("currency_boc_safe 美元", ak.currency_boc_safe, symbol="美元", start_date="20240101", end_date="20240131")
probe("spot_golden_benchmark_sge", ak.spot_golden_benchmark_sge)
probe("futures_main_sina AU0", ak.futures_main_sina, symbol="AU0", start_date="20240101", end_date="20240201")
probe("bond_china_close_return 3", ak.bond_china_close_return, period="3", start_date="20240101", end_date="20240201")
probe("tool_trade_date_hist_sina", ak.tool_trade_date_hist_sina)
probe("index_global_hist_em HSHYLV 试", ak.index_global_hist_em, symbol="HSHYLV")
