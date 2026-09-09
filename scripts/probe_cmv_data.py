"""CMV 复刻数据源探针（2026-09-09）。

探测 akshare / 官方 CSV 各候选接口：历史长度、频率、列结构、可达性。
用法: uv run python scripts/probe_cmv_data.py
"""

import sys
import time
import traceback

import akshare as ak
import pandas as pd

pd.set_option("display.width", 160)


def probe(name, fn, note=""):
    print(f"\n{'=' * 15} {name} {'=' * 15}")
    if note:
        print(f"[note] {note}")
    try:
        df = fn()
        if df is None or len(df) == 0:
            print("EMPTY")
            return
        print(f"shape={df.shape}")
        print(f"columns={list(df.columns)}")
        # 找日期列并报告范围
        date_col = next((c for c in df.columns if str(c).lower() in ("date", "日期", "trade_date", "月份", "统计时间")), None)
        if date_col is not None:
            s = pd.to_datetime(df[date_col], errors="coerce")
            if s.notna().any():
                print(f"date_col={date_col}  range={s.min().date()} ~ {s.max().date()}")
        print(df.tail(2).to_string())
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {type(e).__name__}: {e}")
        traceback.print_exc(limit=1)
    time.sleep(1)  # 礼貌间隔


# ── 两融（Margin Debt）──
probe("macro_china_market_margin_sh", lambda: ak.macro_china_market_margin_sh(), "东财·上交所两融")
probe("macro_china_market_margin_sz", lambda: ak.macro_china_market_margin_sz(), "东财·深交所两融")
probe("stock_margin_sse", lambda: ak.stock_margin_sse(start_date="20000101", end_date="20260909"), "交易所官网·上交所两融")
probe("stock_margin_szse", lambda: ak.stock_margin_szse(date="20260908"), "交易所官网·深交所两融(单日)")

# ── 失业率（Sahm Rule）──
probe("macro_china_urban_unemployment", lambda: ak.macro_china_urban_unemployment(), "城镇调查失业率(东财)")

# ── GDP（Buffett 分母）──
probe("macro_china_gdp", lambda: ak.macro_china_gdp(), "GDP 季度(东财)")
probe("macro_china_gdp_yearly", lambda: ak.macro_china_gdp_yearly(), "GDP 年度")

# ── 总市值（Buffett 分子）──
probe("stock_sse_summary", lambda: ak.stock_sse_summary(), "上交所每日概况(含市价总值)")
probe("stock_szse_summary", lambda: ak.stock_szse_summary(date="20260908"), "深交所概况(单日)")

# ── 领先指标（LEI 替代）──
probe("index_pmi_man_cx", lambda: ak.index_pmi_man_cx(), "财新制造业PMI( Mur岩 )")
probe("macro_china_cx_pmi_yearly", lambda: ak.macro_china_cx_pmi_yearly(), "财新PMI年度")
probe("macro_china_pmi", lambda: ak.macro_china_pmi(), "官方PMI")

# ── 政策不确定性（EPU）──
probe("article_epu_index", lambda: ak.article_epu_index(symbol="中国"), "akshare EPU 指数")

# ── 信用利差（Junk Bond Spreads 替代）──
probe("bond_china_yield", lambda: ak.bond_china_yield(symbol="国债", indicator="到期收益率"), "中债收益率(曲线)")
probe("bond_china_close_return", lambda: ak.bond_china_close_return(symbol="信用债", period="日", start_date="20260101", end_date="20260909"), "中债信用债收盘")

print("\nDONE")
