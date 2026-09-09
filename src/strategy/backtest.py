"""双动量 GEM 回测 CLI。

用法:
    PYTHONPATH=src uv run python -m strategy.backtest            # 两层全跑 + 报告
    PYTHONPATH=src uv run python -m strategy.backtest --layer index --no-report
    PYTHONPATH=src uv run python -m strategy.backtest --cost-bps 5 --premium-cap 0.05
"""
from __future__ import annotations

import argparse
import sys

from .contract import StrategyConfig
from .run_gem import compare_layers, run_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="双动量 GEM 中美本土化——两层回测")
    parser.add_argument("--layer", choices=["index", "etf", "all"], default="all",
                        help="回测层(默认 all)")
    parser.add_argument("--cost-bps", type=float, default=0.0, help="单边成本 bp(默认 0)")
    parser.add_argument("--premium-cap", type=float, default=0.03,
                        help="QDII 溢价买入门(默认 0.03,inf 关闭门控)")
    parser.add_argument("--as-of", default=None, help="数据截止(测试用)")
    parser.add_argument("--no-report", action="store_true", help="跳过 QuantStats 报告")
    args = parser.parse_args(argv)

    cfg = StrategyConfig(cost_bps=args.cost_bps,
                         premium_cap=float("inf") if args.premium_cap == "inf" else args.premium_cap,
                         as_of=args.as_of)
    results = run_all(cfg)
    if args.layer != "all":
        results = {args.layer: results[args.layer]}

    for key, r in results.items():
        s = r.summary
        print(f"\n=== {r.name} ===")
        print(f"  区间   {r.nav.index.min():%Y-%m-%d} → {r.nav.index.max():%Y-%m-%d}({s['days']} 交易日)")
        print(f"  年化   {s['cagr'] * 100:+.2f}%    最大回撤 {s['mdd'] * 100:.1f}%")
        print(f"  夏普   {s['sharpe']:.2f}      Calmar   {s['calmar']:.2f}")
        print(f"  换仓   {s['switch_count']} 次" + (f"    QDII 溢价跳过 {s['blocked_months']} 月"
                                                if s.get("blocked_months") else ""))

    if len(results) == 2:
        print("\n=== 两层对照(共同区间) ===")
        print(compare_layers(*results.values()).to_string(index=False))

    if not args.no_report:
        from .report import write_reports
        paths = write_reports(results)
        for p in paths:
            print(f"  报告 → {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
