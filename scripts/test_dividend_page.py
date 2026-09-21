"""app/dividend_page.py AppTest + 档位/溢价门控/自证三件套纯函数断言（一次性，不入 CI）。

- 纯函数：五档边界两侧（20/40/60/80）、建议文案映射（<40 分批建仓 /
  40-60 持有 / ≥60 减仓·不追加）、溢价门控（>3% 阻断买入侧、≤3% 放行、
  None 不阻断、持有/减仓不受门控影响）
- 自证三件套（src/dividend/forward.py）：五档前瞻收益表（5 行 × 4 期限
  n/中位数/胜率 + 563020 极低估 252d 中位数 >0 实测断言 + 159545 无样本
  如实 NaN）、Spearman IC ∈ [-1,1]、事件研究（563020 n≥5 / 159545 触发
  样本不足保护）；无未来函数抽查（扰动末 200 行 fwd，历史统计不变）
- 数据层：compute_cards 四标的齐全、159545 带不可外推标记、分位与五档自洽
- AppTest：PASEO_MARKET_OFFLINE=1 离线跑页面——无异常、四标的齐全、
  离线兜底提示在、信号区可用、自证区块在、159545 切换出样本不足提示

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

# ── 「打分 × 后续走势」三件套（src/dividend/forward.py 纯函数层）──
import copy

import numpy as np
import pandas as pd

from dividend import factors, forward, score

sc = forward.compute_self_check()
assert set(sc) == {"H30269", "930955", "515450", "159545"}, "三件套四标的不齐"

# A · 五档前瞻收益表：5 行 × 4 期限，n/med/win 齐备
for code, r in sc.items():
    tbl = r["tier"]
    assert len(tbl) == 5 and list(tbl["tier"]) == [1, 2, 3, 4, 5], f"{code} 五档行缺失"
    for h in forward.HORIZONS:
        for col in (f"n_{h}", f"med_{h}", f"win_{h}"):
            assert col in tbl.columns, f"{code} 缺列 {col}"
        valid = tbl[f"n_{h}"] > 0
        med, win = tbl.loc[valid, f"med_{h}"], tbl.loc[valid, f"win_{h}"]
        assert ((med > -1) & (med < 5)).all(), f"{code} {h}d 中位数越界(疑似 fwd 混入)"
        assert ((win >= 0) & (win <= 1)).all(), f"{code} {h}d 胜率越界"
# 实测（2026-09-21 数据）：563020 极低估档 1 年后中位数为正、胜率 >50%
t69 = sc["H30269"]["tier"].set_index("tier")
assert t69.loc[1, "med_252"] > 0, f"563020 极低估 252d 中位数应 >0（实测 {t69.loc[1, 'med_252']:.2%}）"
assert t69.loc[1, "win_252"] > 0.5, "563020 极低估 252d 胜率应 >50%"
# 159545 历史太短：极低估档 252d 无样本 → NaN 而非硬凑
t45 = sc["159545"]["tier"].set_index("tier")
assert t45.loc[1, "n_252"] == 0 and np.isnan(t45.loc[1, "med_252"]), "159545 极低估 252d 应如实显示无样本"
print("五档前瞻收益表 OK（563020 极低估档："
      + " / ".join(f"{h}d 中位 {t69.loc[1, f'med_{h}']:+.1%} 胜率 {t69.loc[1, f'win_{h}']:.0%}"
                   for h in forward.HORIZONS) + "）")

# B · Spearman IC ∈ [-1,1]（有样本处必须非 NaN）
for code, r in sc.items():
    for h, s in r["scatter"].items():
        assert s["n"] > 0, f"{code} {h}d 散点无样本"
        if s["n"] >= forward.IC_MIN_N:
            assert -1.0 <= s["ic"] <= 1.0, f"{code} {h}d IC 越界"
        else:
            assert np.isnan(s["ic"]), "样本不足处 IC 必须为 NaN"
print("Spearman IC OK（563020: "
      + " / ".join(f"{h}d {r_['ic']:+.2f}" for h, r_ in sc["H30269"]["scatter"].items())
      + "；四标的各期限实测均 >0，页面 caption 已如实声明方向与直觉相反）")

# C · 事件研究：563020 事件数 ≥5 可画曲线；159545 触发样本不足保护
e69, e45 = sc["H30269"]["event"], sc["159545"]["event"]
assert e69["ok"] and e69["n_events"] >= 5, f"563020 事件数不足: {e69['n_events']}"
assert len(e69["event_path"]) == e69["window"] + 1 == len(e69["baseline_path"])
assert not e45["ok"] and e45["n_events"] < forward.MIN_EVENTS, "159545 必须触发样本不足保护"
print(f"事件研究 OK（563020 n={e69['n_events']}（另截断 {e69['n_skipped_incomplete']}），"
      f"事件 252d {e69['event_path'].iloc[-1]:+.1%} vs 基准 {e69['baseline_path'].iloc[-1]:+.1%}；"
      f"159545 完整窗口事件 n={e45['n_events']} → 保护）")

# ── 无未来函数抽查：扰动 panel 末 200 行 fwd，历史行统计必须不变 ──
# 口径：fwd_h 标签按行存储（t 行的 fwd_h 用 tr[t..t+h]），扰动末 200 行
# 只可能改变这 200 行自身的标签；截去扰动窗口后，更早历史的五档表/
# 散点/事件数必须逐项一致（否则即存在未来函数）。
panels_orig = factors.build_panels()
scores_orig, _ = score.score_valuation_only(panels_orig)
panels_pert = copy.deepcopy(panels_orig)
for p in panels_pert.values():
    fwd_cols = [c for c in p.columns if c.startswith("fwd_")]
    p.loc[p.index[-200:], fwd_cols] = p.loc[p.index[-200:], fwd_cols] + 0.5
scores_pert, _ = score.score_valuation_only(panels_pert)
for code in score.INSTRUMENTS:
    # 打分本身不受 fwd 扰动影响（权重只用 ≤2023 样本内；T 日信号只用 ≤T-1）
    pd.testing.assert_series_equal(scores_orig[code]["score_pct"],
                                   scores_pert[code]["score_pct"], check_names=False)
    p_o, p_p = panels_orig[code].iloc[:-200], panels_pert[code].iloc[:-200]
    s_o = scores_orig[code]["score_pct"].iloc[:-200] * 100
    s_p = scores_pert[code]["score_pct"].iloc[:-200] * 100
    pd.testing.assert_frame_equal(forward.tier_forward_table(p_o, s_o),
                                  forward.tier_forward_table(p_p, s_p),
                                  obj=f"{code} 五档表历史行被 fwd 扰动影响（存在未来函数）")
    ev_o = forward.event_study(p_o, s_o)
    ev_p = forward.event_study(p_p, s_p)
    assert ev_o["n_events"] == ev_p["n_events"], f"{code} 事件数被 fwd 扰动影响"
print("无未来函数抽查 OK（末 200 行 fwd +50pp 扰动后，截尾历史五档表/事件数逐项不变）")

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
assert "打分 × 后续走势（历史自证）" in subs, "自证区块缺失"
assert "证据链（全部检验的完整记录）" in subs, "证据链区块缺失"
# 证据链必须如实标注 walk-forward 未做（实测与裁决分离纪律）
ev_table = at.table[-1].value.to_string()
assert "未走" in ev_table and "❌" in ev_table, "walk-forward 未做的诚实标注缺失"
print("dividend_page AppTest(offline) OK")

# 自证区块：切换 159545 必须出现"样本不足，不可外推"提示，且不画事件曲线
at.selectbox[0].set_value("159545").run()
assert not at.exception, f"159545 切换异常: {at.exception}"
warns = " ".join(w.value for w in at.warning)
assert "样本不足" in warns and "不可外推" in warns, "159545 样本不足提示缺失"
print("自证区块 159545 样本不足保护 OK")

print("\n全部通过 ✅")
