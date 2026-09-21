"""app/dividend_page.py AppTest + 档位/溢价门控纯函数断言（一次性，不入 CI）。

- 纯函数：五档边界两侧（20/40/60/80）、建议文案映射（<40 分批建仓 /
  40-60 持有 / ≥60 减仓·不追加）、溢价门控（>3% 阻断买入侧、≤3% 放行、
  None 不阻断、持有/减仓不受门控影响）
- 数据层：compute_cards 四标的齐全、159545 带不可外推标记、分位与五档自洽
- AppTest：PASEO_MARKET_OFFLINE=1 离线跑页面——无异常、四标的齐全、
  离线兜底提示在、信号区可用

用法：uv run python scripts/test_dividend_page.py
"""
import os
import sys
from pathlib import Path

os.environ["PASEO_MARKET_OFFLINE"] = "1"   # 必须在页面 import 前设置

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))

from dividend.cards import (PREMIUM_CAP, advice_for_pct, apply_premium_gate,  # noqa: E402
                            compute_cards, tier_from_pct)

# ── 五档边界两侧（TIER_BOUNDS 左闭右开）──
assert tier_from_pct(0.0) == 1 and tier_from_pct(19.9) == 1
assert tier_from_pct(20.0) == 2 and tier_from_pct(39.9) == 2
assert tier_from_pct(40.0) == 3 and tier_from_pct(59.9) == 3
assert tier_from_pct(60.0) == 4 and tier_from_pct(79.9) == 4
assert tier_from_pct(80.0) == 5 and tier_from_pct(100.0) == 5
print("五档边界 OK")

# ── 建议文案映射（设计文档十二节第 2 条机械纪律，边界两侧都断言）──
assert advice_for_pct(19.9) == "分批建仓" and advice_for_pct(20.0) == "分批建仓"
assert advice_for_pct(39.9) == "分批建仓" and advice_for_pct(40.0) == "持有"
assert advice_for_pct(59.9) == "持有" and advice_for_pct(60.0) == "减仓/不追加"
assert advice_for_pct(99.9) == "减仓/不追加"
print("建议映射 OK")

# ── 溢价门控（设计文档十二节第 3 条：买入侧 ≤3% 门控）──
assert apply_premium_gate("分批建仓", PREMIUM_CAP + 1e-9) == "等待溢价回落"
assert apply_premium_gate("分批建仓", PREMIUM_CAP) == "分批建仓"      # 边界 = 门控含等号放行
assert apply_premium_gate("分批建仓", 0.0) == "分批建仓"
assert apply_premium_gate("分批建仓", None) == "分批建仓"             # 无读数不阻断（页面另标注）
assert apply_premium_gate("分批建仓", -PREMIUM_CAP - 1) == "分批建仓"  # 折价不阻断
assert apply_premium_gate("持有", 9.9) == "持有"                      # 门控只管买入侧
assert apply_premium_gate("减仓/不追加", 9.9) == "减仓/不追加"
print("溢价门控 OK")

# ── 数据层：compute_cards ──
cards = compute_cards("valuation")
assert set(cards) == {"H30269", "930955", "515450", "159545"}, "四标的不齐"
for code, c in cards.items():
    assert 0.0 <= c.current <= 100.0, f"{code} 分位越界"
    assert 0.0 <= c.p_pos_1y <= 1.0, f"{code} 概率越界"
    assert c.rating == tier_from_pct(c.current), f"{code} 档位与分位不自洽"
    assert "P(1年收益>0)" in c.desc, f"{code} desc 缺概率白话"
assert cards["159545"].non_extrapolatable, "159545 必须带不可外推标记（落在数据层）"
full = compute_cards("full")
assert set(full) == set(cards), "含动量口径四标的不齐"
print(f"compute_cards OK（纯估值分位: "
      + " / ".join(f"{c.name.split()[0]}{c.name.split()[-1]}={c.current:.0f}%" for c in cards.values())
      + "）")

# ── AppTest（offline 兜底路径）──
from streamlit.testing.v1 import AppTest

at = AppTest.from_file(str(ROOT / "app" / "dividend_page.py")).run()
assert not at.exception, f"页面异常: {at.exception}"
assert "红利低波" in at.header[0].value, "header 缺失"
texts = " ".join(m.value for m in at.markdown)
for etf in ["563020", "515450", "159307", "159545"]:
    assert etf in texts, f"信号区缺 {etf}"
# 机械操作建议文案至少三类齐备（当前读数下：三兄弟分批建仓、159545 减仓/不追加）
assert "分批建仓" in texts and "减仓/不追加" in texts, "操作建议文案缺失"
# 离线兜底提示在（info 或 caption），且不阻断信号区
info_caps = " ".join(i.value for i in at.info) + " ".join(c.value for c in at.caption)
assert "离线" in info_caps, "离线兜底提示缺失"
assert "walk-forward" in info_caps, "诚实声明缺失"
subs = [s.value for s in at.subheader]
assert subs[0] == "当前信号状态（纯估值口径）", f"信号区须置顶: {subs}"
assert "证据链（全部检验的完整记录）" in subs, "证据链区块缺失"
# 证据链必须如实标注 walk-forward 未做（实测与裁决分离纪律）
ev_table = at.table[-1].value.to_string()
assert "未走" in ev_table and "❌" in ev_table, "walk-forward 未做的诚实标注缺失"
print("dividend_page AppTest(offline) OK")

print("\n全部通过 ✅")
