"""行情监控页 AppTest + quotes 组装逻辑单测（一次性，不入 CI）。

- 页面：PASEO_MARKET_OFFLINE=1 强制全 parquet 兜底（测试不依赖实时网络），
  断言三组分表 + 兜底口径标注 + 无异常
- quotes.collect_quotes：offline 路径 16 行齐全、QDII 溢价用单位净值、
  511360 无指数行 index=None
"""
import os
import sys

os.environ["PASEO_MARKET_OFFLINE"] = "1"   # 必须在 import quotes 前设置

sys.path.insert(0, "src")

from streamlit.testing.v1 import AppTest

# ── quotes 组装逻辑（offline 兜底路径）──
from data_module.quotes import collect_quotes, groups_of

rows = collect_quotes()
assert len(rows) == 16, f"报价簿 16 行，实得 {len(rows)}"
assert all(not r.etf.live for r in rows), "offline 模式不得有实时价"
assert all(r.etf.price for r in rows), "有 ETF 兜底失败"
assert all(r.index is None or not r.index.live for r in rows)
assert [r for r in rows if r.index is None][0].etf_code == "511360", "仅 511360 无指数"

premiums = {r.etf_code: r.premium for r in rows if r.premium is not None}
assert set(premiums) == {"513500", "513100", "513880", "159545", "513050"}, "QDII 溢价行不齐"
assert all(abs(v) < 30 for v in premiums.values()), \
    f"溢价超 ±30% 说明误用累计净值（拆分断崖）: {premiums}"

groups = groups_of(rows)
assert {g: len(rs) for g, rs in groups.items()} == \
    {"A股宽基": 8, "海外（QDII）": 5, "商品与债券": 3}
print("quotes 组装逻辑 OK")

# ── 神奇九转 td_setup 单测（合成序列）──
import pandas as pd
from data_module.quotes import td_display, td_setup

up9 = pd.Series([100, 101, 102, 103] + [110 + i for i in range(9)])   # 9 天连高
assert td_setup(up9) == (1, 9), td_setup(up9)
down5 = pd.Series([100, 101, 102, 103] + [90 - i for i in range(5)])  # 5 天连低
assert td_setup(down5) == (-1, 5), td_setup(down5)
# 中断归零：最后一天条件反转
broken = pd.Series([100, 101, 102, 103] + [110, 111, 112, 50])
assert td_setup(broken) == (-1, 1), td_setup(broken)
assert td_setup(pd.Series([1.0, 2.0, 3.0])) == (0, 0)                 # 样本不足
flat = pd.Series([100, 100, 100, 100, 100])                            # 相等不满足严格 >
assert td_setup(flat) == (0, 0)
assert td_display(1, 6) == "上 6" and td_display(-1, 12) == "下 9" and td_display(0, 0) == "—"

# td_multi：日/周/月三级别（构造 300 个交易日单边上行序列，月线需 ≥5 根才有读数）
from data_module.quotes import td_multi
import numpy as np
idx = pd.bdate_range("2025-01-01", periods=300)
up = pd.Series(np.arange(300, dtype=float) + 100, index=idx)
multi = td_multi(up)
assert set(multi) == {"D", "W", "M"}
assert multi["D"][0] == 1 and multi["W"][0] == 1 and multi["M"][0] == 1, multi
# 周线级别校验：周五收盘序列单调增 → 周计数 = 周数−4
n_weeks = len(up.resample("W-FRI").last())
assert multi["W"] == (1, n_weeks - 4), (multi["W"], n_weeks)

# 真实数据：offline 路径下九转应已按 parquet 序列计算（计数在合理区间）
for r in rows:
    for lvl in ("D", "W", "M"):
        sign, n = r.td.get(lvl, (0, 0))
        assert (sign, n) == (0, 0) or (sign in (1, -1) and n >= 1), (r.etf_code, lvl, sign, n)
print("td_setup 单测 OK")

# ── 页面 AppTest（offline 兜底路径）──
at = AppTest.from_file("app/market_monitor.py").run()
assert not at.exception, f"行情页异常：{at.exception}"
assert at.header[0].value == "📡 行情监控"
subs = [s.value for s in at.subheader]
assert subs == ["A股宽基", "海外（QDII）", "商品与债券"], f"分组缺失：{subs}"
assert len(at.dataframe) == 3, "三张分组报价表"
# 兜底口径必须明示（DESIGN 诚实展示）：caption 含收盘/实时计数说明
caps = " ".join(c.value for c in at.caption)
assert "收盘" in caps and "不落盘" in caps, "口径标注缺失"
print("market_monitor 页面（兜底路径）OK")

print("\n全部通过 ✅")
