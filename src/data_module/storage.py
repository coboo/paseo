"""Parquet 存储层：列标准化、增量追加（raw 只增不改）、meta 侧车文件。

纪律（见 AGENTS.md）：
1. raw 层只追加、不回写 —— append_save 对已存在日期保留旧行（keep="first"），只补新日期；
2. 列名入库即标准化，date 转 datetime、排序、去重；
3. 每个 parquet 旁边一个 .meta.json，记录来源接口、复权方式、抓取日期、备注。
"""
import json
from datetime import date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DERIVED_DIR = PROJECT_ROOT / "data" / "derived"

# 行情文件标准列（设计文档第五节）：date, open, high, low, close, volume, amount
OHLCV_MAP_EM = {
    "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
    "收盘": "close", "成交量": "volume", "成交额": "amount",
}


def standardize(df: pd.DataFrame, col_map: dict, keep_cols: list | None = None) -> pd.DataFrame:
    """重命名列 → date 转 datetime → 排序 → 按 date 去重（保最新一行）。"""
    df = df.rename(columns=col_map)
    if keep_cols is not None:
        df = df[[c for c in keep_cols if c in df.columns]]
    df["date"] = pd.to_datetime(df["date"])
    df = (
        df.sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    return df


def meta_path(parquet_path: Path) -> Path:
    """xxx.parquet -> xxx.meta.json"""
    return parquet_path.with_suffix(".meta.json")


def read(parquet_path: Path) -> pd.DataFrame:
    return pd.read_parquet(parquet_path)


def read_raw(rel_path: str) -> pd.DataFrame:
    """按 raw 相对路径读取，如 'index_daily/index_000300.parquet'。"""
    return read(RAW_DIR / rel_path)


def write_meta(parquet_path: Path, *, source: str, adjust: str = "", note: str = "") -> None:
    meta = {
        "source_interface": source,  # 来源接口
        "adjust": adjust,            # 复权方式
        "fetch_date": str(date.today()),  # 最近抓取日期
        "note": note,                # 备注（口径/兜底说明）
    }
    meta_path(parquet_path).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def append_save(
    df: pd.DataFrame,
    parquet_path: Path,
    *,
    source: str,
    adjust: str = "",
    note: str = "",
    key: str = "date",
) -> tuple[int, int]:
    """增量追加：读旧 → 拼接 → 按 key 去重（旧行优先，只增不改）→ 排序写回。

    返回 (总行数, 本次新增行数)。
    """
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    if parquet_path.exists():
        old = read(parquet_path)
        df = pd.concat([old, df], ignore_index=True)
        df = (
            df.drop_duplicates(subset=[key], keep="first")
            .sort_values(key)
            .reset_index(drop=True)
        )
        added = len(df) - len(old)
    else:
        added = len(df)
    df.to_parquet(parquet_path, index=False)
    write_meta(parquet_path, source=source, adjust=adjust, note=note)
    return len(df), added


def save_derived(df: pd.DataFrame, rel_path: str) -> Path:
    """derived 层：全量重算后直接覆盖（read raw → compute → overwrite）。"""
    path = DERIVED_DIR / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path
