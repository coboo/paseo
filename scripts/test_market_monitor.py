"""行情监控页 AppTest + quotes 组装逻辑单测（一次性，不入 CI）。

- 页面：PASEO_MARKET_OFFLINE=1 强制全 parquet 兜底（测试不依赖实时网络），
  断言三组分表 + 兜底口径标注 + 无异常
- quotes.collect_quotes：offline 路径 12 行齐全、QDII 溢价用单位净值、
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
assert len(rows) == 12, f"报价簿 12 行，实得 {len(rows)}"
assert all(not r.etf.live for r in rows), "offline 模式不得有实时价"
assert all(r.etf.price for r in rows), "有 ETF 兜底失败"
assert all(r.index is None or not r.index.live for r in rows)
assert [r for r in rows if r.index is None][0].etf_code == "511360", "仅 511360 无指数"

premiums = {r.etf_code: r.premium for r in rows if r.premium is not None}
assert set(premiums) == {"513500", "513100", "513880", "159545"}, "QDII 溢价行不齐"
assert all(abs(v) < 30 for v in premiums.values()), \
    f"溢价超 ±30% 说明误用累计净值（拆分断崖）: {premiums}"

groups = groups_of(rows)
assert {g: len(rs) for g, rs in groups.items()} == \
    {"A股宽基": 5, "海外（QDII）": 4, "商品与债券": 3}
print("quotes 组装逻辑 OK")

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
