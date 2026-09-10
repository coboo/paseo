"""行情监控页（第四种页面类型，DESIGN.md 第二节 2026-09-10 增补）。

报价板范式（TradingView 自选表）：分组大表扫读，每行 = 指数点位+涨跌幅 ｜
ETF 最新价+涨跌幅 ｜（QDII）溢价率。数据 = 实时快照（新浪主/东财备）+
parquet 收盘兜底，不落盘；每行标注口径（实时时间/收盘日）。

配色：红涨绿跌（A 股惯例，DESIGN.md 对本页的限定豁免，其他页面不适用）。

用法：uv run streamlit run app/market_monitor.py
测试：PASEO_MARKET_OFFLINE=1 强制全兜底路径（AppTest 不依赖实时网络）。
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from components import INK, MKT_DOWN, MKT_UP
from data_module.quotes import collect_quotes, groups_of

st.set_page_config(page_title="行情监控", layout="wide")

PREMIUM_CAP = 3.0  # QDII 溢价门控（AGENTS.md：≤3%）


@st.cache_data(ttl=60)
def _snapshot():
    return collect_quotes()


def _chg_color(v):
    """红涨绿跌；平盘/缺失用墨色。"""
    if pd.isna(v) or v == 0:
        return f"color: {INK}"
    return f"color: {MKT_UP if v > 0 else MKT_DOWN}"


def _premium_style(v, cap=PREMIUM_CAP):
    if pd.isna(v):
        return ""
    if abs(v) > cap:
        return "color: #ec835a; font-weight: 600"   # 超门控：警示橙（色永伴文字，见行尾 ⚠）
    return f"color: {INK}"


def _group_df(rows, with_premium: bool) -> pd.DataFrame:
    recs = []
    for r in rows:
        idx_asof = f'{"实时" if r.index.live else "收盘 " + r.index.asof}' if r.index else ""
        etf_asof = "实时" if r.etf.live else "收盘 " + r.etf.asof
        rec = {
            "指数": r.index.name if r.index else "—",
            "点位": r.index.price if r.index else None,
            "涨跌%": r.index.change_pct if r.index else None,
            "ETF": f"{r.etf.name} {r.etf_code}",
            "最新价": r.etf.price,
            "涨跌% ": r.etf.change_pct,   # 列名去重（Styler subset 按列名）
            "口径": f"指数 {idx_asof} / ETF {etf_asof}" if r.index else f"ETF {etf_asof}",
        }
        if with_premium:
            rec["溢价%"] = r.premium
            rec["净值日期"] = r.nav_date or "—"
        recs.append(rec)
    return pd.DataFrame(recs)


def _render_group(title: str, rows, with_premium: bool):
    st.subheader(title)
    df = _group_df(rows, with_premium)
    fmt = {"点位": lambda v: "—" if pd.isna(v) else f"{v:,.2f}",
           "最新价": lambda v: "—" if pd.isna(v) else f"{v:,.3f}",
           "涨跌%": lambda v: "—" if pd.isna(v) else f"{v:+.2f}%",
           "涨跌% ": lambda v: "—" if pd.isna(v) else f"{v:+.2f}%"}
    styler = df.style.map(_chg_color, subset=["涨跌%", "涨跌% "])
    if with_premium:
        # Styler.format 多次调用后者会整体覆盖前者 → 合并为单次调用
        fmt["溢价%"] = lambda v: "—" if pd.isna(v) else f"{v:+.2f}%" + (" ⚠" if abs(v) > PREMIUM_CAP else "")
        styler = styler.map(_premium_style, subset=["溢价%"])
    styler = styler.format(fmt)
    st.dataframe(styler, hide_index=True, width="stretch")
    if with_premium:
        over = [r for r in rows if r.premium is not None and abs(r.premium) > PREMIUM_CAP]
        if over:
            names = "、".join(f"{r.etf_code}({r.premium:+.1f}%)" for r in over)
            st.caption(f"⚠️ 溢价超 ±{PREMIUM_CAP:.0f}% 门控：{names}——按 QDII 纪律买入跳过/顺延")


def main():
    st.header("📡 行情监控")
    if st.sidebar.button("🔄 刷新行情"):
        st.cache_data.clear()
    rows = _snapshot()

    live_n = sum(1 for r in rows if r.etf.live)
    st.caption(
        f"快照 {datetime.now():%Y-%m-%d %H:%M} · 数据源：新浪实时（主）/ 东财实时（备）/ parquet 收盘（兜底）· "
        f"本页 {live_n}/{len(rows)} 只 ETF 为实时价，其余为最近收盘 · 实时快照不落盘，刷新间隔 60s"
    )

    groups = groups_of(rows)
    _render_group("A股宽基", groups["A股宽基"], with_premium=False)
    _render_group("海外（QDII）", groups["海外（QDII）"], with_premium=True)
    _render_group("商品与债券", groups["商品与债券"], with_premium=False)

    st.caption(
        "契约：实时价来自新浪/东财现货接口，页面拉取不落盘；海外指数/黄金/债券指数为昨夜收盘"
        "（时区与数据频率所限，属设计而非故障）；QDII 溢价率 = ETF 价 ÷ 最新单位净值（净值滞后 1-2 个交易日，"
        "溢价读数含滞后误差）。Streamlit Cloud 境外节点对国内源不可达时自动降为收盘口径。"
    )


main()
