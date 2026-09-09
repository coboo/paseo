"""每日评级快照(AGENTS.md 规则 5:metrics_history.parquet 是唯一允许追加写的文件)。

CLI:PYTHONPATH=src uv run python -m metrics.snapshot
算 7 卡 + 综合分,按数据截止日追加/覆盖当日一行(同日重跑幂等)。
用于事后验证"估值分 vs 未来收益"散点(第 4 步余量)。
"""
from __future__ import annotations

import sys

import pandas as pd

from data_module.storage import DERIVED_DIR

from .aggregate import CARDS, composite

HISTORY_PATH = DERIVED_DIR / "metrics_history.parquet"


def snapshot_row(window_years: int | None = 10) -> pd.DataFrame:
    """单行快照:date + 各卡 current/z/rating + composite_z/composite_rating。"""
    row: dict = {}
    for key, fn, _, _, _ in CARDS:
        m = fn(window_years)
        row[f"{key}_current"] = m.current
        row[f"{key}_z"] = m.sigma
        row[f"{key}_rating"] = m.rating
        if "date" not in row or pd.Timestamp(m.updated) > pd.Timestamp(row["date"]):
            row["date"] = m.updated
    c = composite(window_years)
    row["composite_z"] = c.sigma
    row["composite_rating"] = c.rating
    return pd.DataFrame([row])


def append_snapshot(window_years: int | None = 10) -> tuple[int, int]:
    """追加快照(同日覆盖)。返回 (总行数, 本次写入行数)。"""
    new = snapshot_row(window_years)
    day = new["date"].iloc[0]
    if HISTORY_PATH.exists():
        old = pd.read_parquet(HISTORY_PATH)
        old = old[old["date"] != day]          # 同日幂等覆盖
        out = pd.concat([old, new], ignore_index=True).sort_values("date")
    else:
        out = new
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(HISTORY_PATH, index=False)
    return len(out), 1


def main() -> int:
    total, added = append_snapshot()
    row = pd.read_parquet(HISTORY_PATH).iloc[-1]
    print(f"快照写入 {row['date']}:composite_z={row['composite_z']:+.2f} "
          f"rating={int(row['composite_rating'])}(共 {total} 行)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
