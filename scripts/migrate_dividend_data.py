# -*- coding: utf-8 -*-
"""dividend-research 原始 CSV → 主项目 data/raw parquet 一次性迁移。

迁移内容（dividend-research/data/raw/ → data/raw/）：
- csindex_{H30269,930955,000300}.csv  → valuation/csindex_pe_*.parquet（含 pe_ttm）
- csindex_{H20269,H20955,H00922,H00300}.csv → index_daily/index_tr_*.parquet（全收益收盘）
- bond_zh_us_rate.csv                 → rates/bond_zh_us_rate.parquet（中美国债）
- macro_monthly.csv                   → macro/macro_monthly.parquet（m1m2/ppi，已滞后一月）

不迁（见交付报告）：fund_nav_*（主项目已有同内容数据集，且研究 CSV 日期 -1 日错位）、
bond_china_yield.csv（空文件）、price_*.csv（iFinD ETF 价，死数据用途待定）、
val_H30269.csv（一次性校验）、csindex_000922/H00922（参照基准，无脚本消费）。

幂等：append_save 按 date 去重只增不改，可重复执行。
在线刷新走 PYTHONPATH=src uv run python -m data_module.update <数据集名>。

用法：uv run python scripts/migrate_dividend_data.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_module.storage import RAW_DIR, append_save, standardize  # noqa: E402

RESEARCH_RAW = Path(__file__).resolve().parent.parent / "dividend-research" / "data" / "raw"
MIGRATE_NOTE = "来自 dividend-research 迁移（存量 CSV 转换，原始文件保留在 dividend-research/data/raw/）"

# (研究 CSV, 目标 rel_path, 列映射, 保留列, 来源接口标注, 复权方式)
JOBS = [
    ("csindex_H30269.csv", "valuation/csindex_pe_H30269.parquet",
     {}, ["date", "close", "pe_ttm", "pct_chg"], "csindex index-perf(H30269)", "无（指数）"),
    ("csindex_930955.csv", "valuation/csindex_pe_930955.parquet",
     {}, ["date", "close", "pe_ttm", "pct_chg"], "csindex index-perf(930955)", "无（指数）"),
    ("csindex_000300.csv", "valuation/csindex_pe_000300.parquet",
     {}, ["date", "close", "pe_ttm", "pct_chg"], "csindex index-perf(000300)", "无（指数）"),
    ("csindex_H20269.csv", "index_daily/index_tr_H20269.parquet",
     {}, ["date", "close", "pe_ttm", "pct_chg"], "csindex index-perf(H20269)", "无（全收益指数）"),
    ("csindex_H20955.csv", "index_daily/index_tr_H20955.parquet",
     {}, ["date", "close", "pe_ttm", "pct_chg"], "csindex index-perf(H20955)", "无（全收益指数）"),
    ("csindex_H00922.csv", "index_daily/index_tr_H00922.parquet",
     {}, ["date", "close", "pe_ttm", "pct_chg"], "csindex index-perf(H00922)", "无（全收益指数）"),
    ("csindex_H00300.csv", "index_daily/index_tr_H00300.parquet",
     {}, ["date", "close", "pe_ttm", "pct_chg"], "csindex index-perf(H00300)", "无（全收益指数）"),
    ("bond_zh_us_rate.csv", "rates/bond_zh_us_rate.parquet",
     {"日期": "date", "中国国债收益率2年": "cn_2y", "中国国债收益率5年": "cn_5y",
      "中国国债收益率10年": "cn_10y", "中国国债收益率30年": "cn_30y",
      "中国国债收益率10年-2年": "cn_spread_10y2y", "中国GDP年增率": "cn_gdp_yoy",
      "美国国债收益率2年": "us_2y", "美国国债收益率5年": "us_5y",
      "美国国债收益率10年": "us_10y", "美国国债收益率30年": "us_30y",
      "美国国债收益率10年-2年": "us_spread_10y2y", "美国GDP年增率": "us_gdp_yoy"},
     ["date", "cn_2y", "cn_5y", "cn_10y", "cn_30y", "cn_spread_10y2y", "cn_gdp_yoy",
      "us_2y", "us_5y", "us_10y", "us_30y", "us_spread_10y2y", "us_gdp_yoy"],
     "bond_zh_us_rate", "不适用"),
    ("macro_monthly.csv", "macro/macro_monthly.parquet",
     {}, ["date", "m1m2", "ppi_yoy"], "macro_china_money_supply + macro_china_ppi", "不适用"),
]


def main() -> None:
    for csv_name, rel_path, col_map, keep, source, adjust in JOBS:
        df = pd.read_csv(RESEARCH_RAW / csv_name)
        df = standardize(df, col_map, keep)
        total, added = append_save(df, RAW_DIR / rel_path,
                                   source=source + "；CSV迁移", adjust=adjust,
                                   note=MIGRATE_NOTE)
        print(f"{csv_name:28s} -> {rel_path:45s} 总行数={total}（新增 {added}）"
              f" 区间 {df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}")


if __name__ == "__main__":
    main()
