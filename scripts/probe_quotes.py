"""行情快照接口探针：验证 quotes.py 依赖的实时源覆盖度与字段（可重复执行）。

用法：uv run python scripts/probe_quotes.py
结论（2026-09-10，已写入 src/data_module/quotes.py docstring）：
- 新浪 stock_zh_index_spot_sina：A股指数 4/5（无 H30269 中证系），字段全
- 新浪 hq.sinajs.cn：ETF 12/12 全覆盖（含 QDII），格式同股票快照
- 东财 spot（指数/ETF）：数字子域名本机代理时通时断，作备份源
"""
import warnings

warnings.filterwarnings("ignore")

import akshare as ak
import requests

A_IDX = ["sh000300", "sh000905", "sh000852", "sz399006"]
ETFS = ["510310", "510580", "159633", "159915", "563020", "513500",
        "513100", "513880", "518880", "159545", "511260", "511360"]


def probe_sina_index():
    df = ak.stock_zh_index_spot_sina()
    hit = df[df["代码"].isin(A_IDX)]
    print(f"[新浪指数] {len(hit)}/{len(A_IDX)} 命中，字段 {list(df.columns)[:6]}…")


def probe_sina_etf():
    pref = ["sh" + c if c.startswith("5") else "sz" + c for c in ETFS]
    r = requests.get("https://hq.sinajs.cn/list=" + ",".join(pref),
                     headers={"Referer": "https://finance.sina.com.cn"}, timeout=8)
    r.encoding = "gbk"
    ok = sum(1 for line in r.text.strip().split("\n") if "=" in line and '""' not in line)
    print(f"[新浪ETF] {ok}/{len(ETFS)} 命中")


def probe_em():
    try:
        df = ak.stock_zh_index_spot_em(symbol="中证系列指数")
        has_h = "H30269" in set(df["代码"])
        print(f"[东财指数] 可达，H30269 {'有' if has_h else '无'}")
    except Exception as e:
        print(f"[东财指数] 不可达：{type(e).__name__}")
    try:
        df = ak.fund_etf_spot_em()
        hit = df[df["代码"].isin(ETFS)]
        print(f"[东财ETF] 可达，{len(hit)}/{len(ETFS)} 命中")
    except Exception as e:
        print(f"[东财ETF] 不可达：{type(e).__name__}")


if __name__ == "__main__":
    probe_sina_index()
    probe_sina_etf()
    probe_em()
