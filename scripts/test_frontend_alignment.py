"""前端对齐 DESIGN.md 后的 AppTest 冒烟验证（一次性，不入 CI）。

- valuation_dashboard：双窗口口径各跑一遍，无异常
- browse_data：总览表 + 点选一行进详情（含绘图分支），无异常
"""
import sys

from streamlit.testing.v1 import AppTest

DASH = "app/valuation_dashboard.py"
BROWSE = "app/browse_data.py"

# ── 估值仪表盘：双口径 ──
# 页面有两个 radio(侧栏 σ 窗口 + IC 区 horizon),按标签取,勿用下标(元素顺序会变)
for choice in ["10y", "full"]:
    at = AppTest.from_file(DASH).run()
    assert not at.exception, f"dashboard {choice} 初始（10y）异常：{at.exception}"
    win_radio = next(r for r in at.radio if r.label.startswith("σ 口径窗口"))
    win_radio.set_value(choice)
    at.run()
    assert not at.exception, f"dashboard {choice} 异常：{at.exception}"
    # AppTest 不内建 plotly 元素，改查可访问元素：标题 / hero+色条 markdown / 双辅证表
    # (默认卡自 2026-08-26 起为综合分,MODELS 第一项)
    assert at.header[0].value.startswith("股债性价比")
    assert len(at.markdown) >= 4, "五件套 HTML 区块缺失"
    assert len(at.table) == 3, "双窗口对照 + 锚点回验 + IC 总表缺失"
print("valuation_dashboard 双口径 OK")

# ── 估值仪表盘：全部卡片遍历(2026-09-09:13 卡 + 综合分)──
# 注意:selectbox options 为 key、format_func 显示中文——select() 必须传原始 key
for key in ["composite", "erp_000300", "curve_10y3m", "dividend_spread",
            "pe_000300", "ma250_dev", "rates_10y", "qvix_50etf",
            "margin_debt", "buffett_indicator", "credit_spread",
            "pmi_momentum", "epu_china", "sahm_rule"]:
    at = AppTest.from_file(DASH).run()
    at.sidebar.selectbox[0].select(key)
    at.run()
    assert not at.exception, f"dashboard [{key}] 异常：{at.exception}"
    assert len(at.markdown) >= 4 and len(at.table) == 3, f"[{key}] 五件套区块缺失"
print("valuation_dashboard 全卡片 OK")


# ── 数据浏览器：总览 → 侧栏直接挑选 → 详情（绘图分支）──
# （st.dataframe 的行选择交互 AppTest 无法模拟，改走"直接挑选"模式）
at = AppTest.from_file(BROWSE).run()
assert not at.exception, f"browse 总览异常：{at.exception}"
assert len(at.dataframe) >= 1, "总览表缺失"
at.radio[0].set_value("🔽 直接挑选")
at.run()
sb = at.sidebar.selectbox[0]
sb.select(sb.options[1])
at.run()
assert not at.exception, f"browse 详情异常：{at.exception}"
assert at.header[0].value, "详情页标题缺失"
print("browse_data 总览+详情 OK")

# ── 组件层断言：tier 呈现符合 3.1 表 ──
sys.path.insert(0, "app")
from components import CATEGORICAL, tier_fill, tier_text  # noqa: E402

assert CATEGORICAL[0] == "#2a78d6" and len(CATEGORICAL) == 8
assert tier_fill(2) == "rgba(12,163,12,0.5)", tier_fill(2)
assert tier_fill(3).startswith("rgba(250,178,25,"), tier_fill(3)  # 黄全值（@50% 仅档2）
assert tier_fill(4).startswith("rgba(236,131,90,"), tier_fill(4)  # 橙全值
assert tier_text(3) == "#0b0b0b" and tier_text(5) == "#ffffff"
print("components tier 呈现 OK")
