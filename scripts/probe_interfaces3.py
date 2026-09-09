"""小样本试跑（第三轮）：估值替代、汇率、中债财富指数、港股指数。"""
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


probe("stock_index_pe_lg 中证500", ak.stock_index_pe_lg, symbol="中证500")
probe("stock_index_pb_lg 沪深300", ak.stock_index_pb_lg, symbol="沪深300")
probe("stock_index_pb_lg 中证500", ak.stock_index_pb_lg, symbol="中证500")
probe("stock_a_gxl_lg", ak.stock_a_gxl_lg)
probe("currency_boc_safe 无参", ak.currency_boc_safe)
probe("bond_china_close_return 国债 period=1", ak.bond_china_close_return,
      symbol="国债", period="1", start_date="20240101", end_date="20240110")
probe("fund_etf_hist_em 510310 qfq 上市起", ak.fund_etf_hist_em, symbol="510310",
      period="daily", start_date="20130301", end_date="20130401", adjust="qfq")
# 港股指数接口候选
for cand in ["stock_hk_index_daily_sina", "stock_hk_index_daily_em", "stock_hk_index_spot_em"]:
    if hasattr(ak, cand):
        print(cand, "exists")
probe("stock_hk_index_daily_em HSHYLV?", getattr(ak, "stock_hk_index_daily_em", None) or (lambda: None), symbol="HSHYLV") if hasattr(ak, "stock_hk_index_daily_em") else None
