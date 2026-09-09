"""app/faber_strategy.py AppTest 冒烟。

前置:derived 的 faber 落盘已生成(run_baselines)。
用法:uv run python scripts/test_faber_strategy_app.py
"""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app" / "faber_strategy.py"
DERIVED = Path(__file__).resolve().parents[1] / "data" / "derived"


def main() -> int:
    if not (DERIVED / "backtests" / "faber_index.parquet").exists():
        print("[跳过] 缺 faber 落盘——先跑 PYTHONPATH=src uv run python -m strategy.run_baselines")
        return 0
    at = AppTest.from_file(str(APP)).run()
    assert not at.exception, f"页面异常: {at.exception}"
    assert at.header[0].value.startswith("Faber"), "header 缺失"
    assert len(at.metric) >= 8, "当前状态 4 + 指标 4 个 metric 应齐全"
    assert len(at.caption) >= 2 and len(at.table) >= 1, "元信息/证据链表缺失"
    # 证据链必须包含 holdout 实测行与裁决行(实测与裁决分离纪律)
    src = APP.read_text(encoding="utf-8")
    assert "holdout" in src and "验收" in src, "证据链须含 holdout 实测与验收裁决"
    # 下次调仓日禁止硬编码
    assert "2026-08-31 月末信号" not in src, "下次调仓日不得硬编码"
    print("  faber_strategy OK(状态/指标/证据链/调仓日动态推导,无异常)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
