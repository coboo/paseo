"""一次性补数脚本：等东财恢复时抓日经225全历史并增量入库。"""
import sys
import time

sys.path.insert(0, "src")

import akshare as ak
import pandas as pd

from data_module.storage import RAW_DIR, append_save, standardize

for i in range(30):
    try:
        df = ak.index_global_hist_em(symbol="日经225")
        if len(df) > 2000:
            col_map = {"日期": "date", "开盘": "open", "最高": "high", "最低": "low",
                       "收盘": "close", "成交量": "volume"}
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            df["amount"] = pd.NA
            out = standardize(df, {}, ["date", "open", "high", "low", "close", "volume", "amount"])
            total, added = append_save(
                out, RAW_DIR / "index_global/n225_n225.parquet",
                source="index_global_hist_em(日经225)", adjust="无（指数）",
                note="本币计价；东财全球指数接口",
            )
            print(f"SUCCESS 行数={total}（新增 {added}），区间 {out['date'].min()} ~ {out['date'].max()}")
            sys.exit(0)
        print(f"#{i} 返回行数不足({len(df)})，继续等")
    except Exception as e:
        print(f"#{i} {type(e).__name__}")
    time.sleep(90)
print("东财 45 分钟内未恢复，放弃（保留新浪环球 2022 年起数据）")
sys.exit(1)
