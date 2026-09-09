"""CLI 入口：全量或按名称增量更新数据集。

用法：
    PYTHONPATH=src uv run python -m data_module.update            # 全量更新
    PYTHONPATH=src uv run python -m data_module.update --list     # 列出所有数据集
    PYTHONPATH=src uv run python -m data_module.update index_000300 cn10y  # 按名称更新

raw 层只增不改：重跑不会重复入库（按 date 去重，旧行优先），天然断点续传。
"""
import argparse
import sys
import time

from .sources import BY_NAME, DATASETS
from .storage import RAW_DIR, append_save


def update_one(ds) -> tuple[bool, str]:
    """更新单个数据集，返回 (是否成功, 摘要)。"""
    print(f"\n>>> [{ds.name}] -> {ds.rel_path}")
    try:
        res = ds.fetcher()
        total, added = append_save(
            res.df, RAW_DIR / ds.rel_path,
            source=res.source, adjust=res.adjust,
            note="；".join(x for x in [ds.note, res.note] if x),
        )
        d0 = res.df["date"].min()
        d1 = res.df["date"].max()
        msg = f"OK 行数={total}（新增 {added}），区间 {d0:%Y-%m-%d} ~ {d1:%Y-%m-%d}，来源 {res.source}"
        print(f"    {msg}")
        return True, msg
    except Exception as e:  # noqa: BLE001
        msg = f"FAILED {type(e).__name__}: {str(e)[:200]}"
        print(f"    {msg}")
        return False, msg


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="指数/ETF 量化系统——数据更新")
    parser.add_argument("names", nargs="*", help="数据集名称（默认全部）")
    parser.add_argument("--list", action="store_true", help="列出所有数据集")
    args = parser.parse_args(argv)

    if args.list:
        for ds in DATASETS:
            print(f"{ds.name:22s} {ds.rel_path:45s} {ds.note}")
        return 0

    targets = []
    for name in args.names:
        if name not in BY_NAME:
            print(f"未知数据集: {name}（--list 查看全部）")
            return 2
        targets.append(BY_NAME[name])
    if not targets:
        targets = DATASETS

    results = {}
    for i, ds in enumerate(targets):
        ok, msg = update_one(ds)
        results[ds.name] = (ok, msg)
        if i < len(targets) - 1:
            time.sleep(1.0)  # 限流保护

    print("\n" + "=" * 60)
    print("更新汇总")
    failed = [n for n, (ok, _) in results.items() if not ok]
    print(f"成功 {len(results) - len(failed)}/{len(results)}")
    if failed:
        print("失败清单：")
        for n in failed:
            print(f"  - {n}: {results[n][1]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
