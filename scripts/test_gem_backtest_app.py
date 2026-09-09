"""app/gem_backtest.py AppTest 冒烟(三段式,对齐 test_frontend_alignment 惯例)。

前置:derived/backtests/ 已由 CLI 生成(本脚本会先确认,缺失则提示)。
用法:uv run python scripts/test_gem_backtest_app.py
"""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app" / "gem_backtest.py"
DERIVED = Path(__file__).resolve().parents[1] / "data" / "derived" / "backtests"


def main() -> int:
    for tag in ["index", "etf"]:
        if not (DERIVED / f"gem_cn_{tag}.parquet").exists():
            print(f"[跳过] 缺 {tag} 结果——先跑 PYTHONPATH=src uv run python -m strategy.backtest")
            return 0

    for opt in ["信号层·指数", "执行层·ETF", "两层对照", "敏感性扫描", "基线三策略"]:
        at = AppTest.from_file(str(APP)).run()
        assert not at.exception, f"[{opt}] 页面异常: {at.exception}"
        at.radio[0].set_value(opt)
        at.run()
        assert not at.exception, f"[{opt}] 切换后异常: {at.exception}"
        assert at.header[0].value.startswith("双动量 GEM"), f"[{opt}] header 缺失"
        # plotly 图 AppTest 不可见,退化为元素计数断言(层视图有 metric,其余视图有 table)
        if opt != "信号层·指数" and opt != "执行层·ETF":
            assert len(at.caption) >= 2 and len(at.table) >= 1, f"[{opt}] 元素不足"
        else:
            assert len(at.caption) >= 3 and len(at.metric) >= 4, f"[{opt}] 元素不足"
        print(f"  [{opt}] OK(header/caption/图表元素齐全,无异常)")

    # 组件纪律:页面不重写色值,统一 import components
    src = APP.read_text(encoding="utf-8")
    assert "from components import" in src and '"#2a78d6"' not in src.replace(
        'colorscale=[[0.0, "#2a78d6"]', "").replace('"#eb6834"]', ""), "页面内不得硬编码序列色"
    print("  组件纪律 OK(取色走 components,热力图色除外[已登记 DESIGN.md])")
    print("gem_backtest_app 全部 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
