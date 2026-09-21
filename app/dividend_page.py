"""红利低波簇策略信号页（设计文档十二节展示层）。

范式 = 策略页（faber_strategy.py，DESIGN.md 第二节 2026-08-26 增补）：
当前信号状态区置顶 + 证据链 + 页脚实盘映射。内容 = 四标的打分分位
（五档贵贱）+ P(1年收益>0) + 机械操作建议（低估分批建仓/公允持有/高估减仓）；
159545 为 QDII，买入建议叠加溢价率 ≤3% 门控（超门控显示"等待溢价回落"）。

定位诚实声明：本研究未走主项目 walk-forward + holdout 流程（设计文档十二节），
页面为"估值参考 + 信号观察"，不构成实盘指令；计算全部 @st.cache_data 不落盘
（AGENTS.md 规则 5）；PASEO_MARKET_OFFLINE=1 时溢价区显示离线兜底提示，
不阻断其余内容（以行情监控页为准）。

用法：uv run streamlit run app/dividend_page.py
测试：PASEO_MARKET_OFFLINE=1 uv run python scripts/test_dividend_page.py
"""
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from components import (CATEGORICAL, GREEN_WASH, GRID, INK, INK2, MUTED, RED_WASH,
                        base_layout, tier_text)
from dividend.cards import (CALIBER_LABELS, CLUSTER_WEIGHT_RANGE, INSTRUMENTS, ORDER,
                            PREMIUM_CAP, RATING_LEVELS, SUGGESTED_WEIGHTS,
                            advice_for_pct, apply_premium_gate, compute_cards)
from dividend.cards import DividendCard  # noqa: F401  (类型留档，页面只读消费)

st.set_page_config(page_title="红利低波簇策略信号", page_icon="🧧", layout="wide")

# 溢价警示橙 = 行情监控页溢价语义色（DESIGN.md：色永伴文字，不用黄——
# 黄已是五档"公允"专属语义）
PREMIUM_WARN = "#ec835a"


@st.cache_data(ttl=3600)
def _cards(caliber: str) -> dict:
    return compute_cards(caliber)


@st.cache_data(ttl=300)
def _premium_159545() -> tuple[float | None, str, bool]:
    """159545 溢价率（百分数）、口径标注、是否离线。

    口径同行情监控页：ETF 价 ÷ 最新单位净值 − 1（单位净值，非累计净值）。
    PASEO_MARKET_OFFLINE=1 时不发网络请求，premium=None + offline=True。
    """
    offline = os.environ.get("PASEO_MARKET_OFFLINE") == "1"
    if offline:
        return None, "离线模式", True
    from data_module.quotes import collect_quotes

    rows = collect_quotes()
    r = next((x for x in rows if x.etf_code == "159545"), None)
    if r is None or r.premium is None:
        return None, (f"{r.etf.source}（净值缺失）" if r else "无数据"), False
    asof = f"{r.etf.source} {r.etf.asof}" + (f" · 净值 {r.nav_date}" if r.nav_date else "")
    return float(r.premium), asof, False


def _signal_card_html(code: str, card: DividendCard, premium: float | None,
                      offline: bool) -> tuple[str, bool]:
    """单标的信号小卡 HTML；返回 (html, 是否被溢价门控拦截)。"""
    meta = INSTRUMENTS[code]
    advice = advice_for_pct(card.current)
    gated = False
    if meta["qdii"]:
        gated_advice = apply_premium_gate(advice, None if offline else premium)
        gated = gated_advice != advice
        advice = gated_advice
    advice_color = PREMIUM_WARN if gated else INK
    advice_mark = " ⚠️" if gated else ""
    p_txt = f"P(1年>0) = {card.p_pos_1y:.0%}"
    if card.non_extrapolatable:
        p_txt += " ⚠️不可外推"
    weight = SUGGESTED_WEIGHTS[meta["etf"]]
    return (
        f'<div style="border:1px solid {GRID};border-radius:10px;padding:12px 14px;height:100%">'
        f'<div style="font-size:1.02rem;font-weight:600;color:{INK}">{meta["label"]}</div>'
        f'<div style="font-size:2.1rem;font-weight:700;color:{INK};line-height:1.15">'
        f"{card.current:.0f}<span style='font-size:0.95rem;color:{MUTED};font-weight:400'>% 分位</span></div>"
        f'<div style="display:inline-block;background:{card.color};color:{tier_text(card.rating)};'
        f'border-radius:6px;padding:2px 10px;font-weight:600;font-size:0.9rem">'
        f'{RATING_LEVELS[card.rating]["label"]}</div>'
        f'<div style="margin-top:8px;font-size:0.92rem;color:{INK2}">{p_txt}'
        f'<span style="color:{MUTED}">（n={card.state_n}）</span></div>'
        f'<div style="font-size:0.95rem;color:{advice_color};font-weight:600">'
        f"建议：{advice}{advice_mark}</div>"
        f'<div style="font-size:0.85rem;color:{MUTED}">建议权重 ≈{weight}%'
        + ("（QDII 门控）" if meta["qdii"] else "") + "</div>"
        f"</div>"
    ), gated


def _history_fig(cards: dict) -> go.Figure:
    """近 3 年四标的打分分位走势 + 五档带（多序列 categorical 固定顺序，按实体不按名次）。"""
    fig = go.Figure()
    for i, code in enumerate(ORDER):
        s = cards[code].series
        s3 = s[s.index >= s.index[-1] - pd.DateOffset(years=3)]
        fig.add_scatter(x=s3.index, y=s3.values, name=INSTRUMENTS[code]["label"],
                        line=dict(color=CATEGORICAL[i], width=1.8),
                        hovertemplate="%{x|%Y-%m-%d}：%{y:.0f}%<extra></extra>")
    for y in (20, 40, 60, 80):
        fig.add_hline(y=y, line=dict(color=MUTED, width=1, dash="dot"))
    fig.add_hrect(y0=0, y1=20, fillcolor=GREEN_WASH, line_width=0)
    fig.add_hrect(y0=80, y1=100, fillcolor=RED_WASH, line_width=0)
    base_layout(fig, "打分分位(%)")
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.12),
                      title="近 3 年打分分位走势（绿带 <20% = 便宜区，红带 >80% = 贵区）",
                      yaxis=dict(range=[0, 100]))
    return fig


def _evidence_block() -> None:
    """证据链摘要（实测与裁决分离纪律：walk-forward 未做必须如实标 ❌）。"""
    rows = [
        ("因子筛选", "16 候选因子 → 幸存 4 个家族（252 日反转 / 盈利收益率利差 / −PE / 股息率·ERP 分位）；"
         "全样本 IC + expanding 分档单调 + 滚动 ICIR + 2024+ 样本外，四重验证", "✅ 通过"),
        ("权重估计", "样本内（≤2023）126 日滚动 ICIR 归一化，永久冻结；迁移仅修复分位因子前视"
         "（取值截至前一交易日），权重一个数未改", "✅ 冻结"),
        ("样本外检验", "冻结模型逐周模拟历史预测（2024+，无未来函数）；非重叠抽样后相关仍 p<0.01；"
         "logistic 概率对照全面落败，频率法为最优概率模型", "✅ 通过"),
        ("主项目 walk-forward + holdout", "未走（研究完成于主项目之外，验证惯例自洽但流程不同）", "❌ 未做"),
        ("终局裁决", "定位「估值参考 + 信号观察」，不自动成为实盘策略；若未来按此信号实盘，"
         "须补 walk-forward 终验并独立立项（设计文档十二节）", "⚠️ 观察定位"),
    ]
    st.table(pd.DataFrame(rows, columns=["检验", "结果摘要", "判"]))


def main() -> None:
    st.header("🧧 红利低波簇策略信号")
    st.caption("四标的打分分位（五档贵贱）+ P(1年收益>0) + 机械操作建议 · "
               "打分 = expanding z × ≤2023 样本内 ICIR 冻结权重 · 纯估值口径回答「贵贱」，"
               "含动量口径回答「赢面」（对照见下表）· "
               "定位「估值参考 + 信号观察」，未走主项目 walk-forward（证据链与声明见页底）")

    val = _cards("valuation")
    full = _cards("full")
    premium, premium_asof, offline = _premium_159545()

    # ── ① 当前信号状态区（策略页置顶区块）──
    st.subheader("当前信号状态（纯估值口径）")
    cols = st.columns(4)
    any_gated = False
    for i, code in enumerate(ORDER):
        html, gated = _signal_card_html(code, val[code], premium, offline)
        any_gated = any_gated or gated
        cols[i].markdown(html, unsafe_allow_html=True)
    w_sum = sum(SUGGESTED_WEIGHTS.values())
    st.caption(f"建议权重来源：HANDOFF 一页纸「当前建议（进取型）」，簇合计 {w_sum:.1f}%"
               f"（区间 {CLUSTER_WEIGHT_RANGE[0]:.0f}–{CLUSTER_WEIGHT_RANGE[1]:.0f}%）——"
               "信号观察定位下的参考权重，非实盘指令。")

    # ── ② 双口径对照（含动量 = 赢面 / 纯估值 = 贵贱）──
    st.subheader("双口径对照")
    rows = []
    for code in ORDER:
        v, f = val[code], full[code]
        rows.append(dict(
            标的=INSTRUMENTS[code]["label"],
            纯估值分位=f"{v.current:.0f}%", 纯估值P1年=f"{v.p_pos_1y:.0%}",
            含动量分位=f"{f.current:.0f}%", 含动量P1年=f"{f.p_pos_1y:.0%}",
            操作档位=RATING_LEVELS[v.rating]["label"],
        ))
    st.table(pd.DataFrame(rows))
    st.caption("口径说明：" + "；".join(CALIBER_LABELS.values())
               + "。515450/159545 无 PE，纯估值口径仅含股息率/ERP 因子；"
               "159545 历史仅 2.5 年，两口径概率均不可外推（⚠️ 标记落在数据层）。")

    # ── ③ 159545 QDII 溢价门控 ──
    st.subheader("159545 QDII 溢价门控")
    if offline:
        st.info("离线模式（PASEO_MARKET_OFFLINE=1）：溢价数据不可用，以行情监控页为准；"
                "买入门控暂不生效，恢复在线后自动重查（口径：ETF 价 ÷ 最新单位净值 − 1）。")
    elif premium is None:
        st.warning(f"溢价率暂不可得（{premium_asof}）——159545 任何买入前请自行核对行情监控页溢价列。")
    elif abs(premium) > PREMIUM_CAP:
        st.markdown(f"⚠️ 当前溢价 **{premium:+.2f}%**（{premium_asof}）超 ±{PREMIUM_CAP:.0f}% 门控——"
                    "买入建议已转为「等待溢价回落」，按 QDII 纪律跳过/顺延。")
    else:
        st.markdown(f"当前溢价 **{premium:+.2f}%**（{premium_asof}）≤ {PREMIUM_CAP:.0f}% 门控——"
                    "买入建议正常生效。")

    # ── ④ 打分历史（近 3 年四标的）──
    st.subheader("打分历史")
    st.plotly_chart(_history_fig(val), width="stretch")

    # ── ⑤ 证据链与诚实声明 ──
    st.subheader("证据链（全部检验的完整记录）")
    _evidence_block()
    st.caption("已知局限（HANDOFF 诚实展示）：515450/159545 缺 PE（股息率/ERP 口径代理，"
               "515450 的 DV 代理系统性偏低约 1pt）；159545 历史仅 2.5 年，概率不可外推；"
               "16 因子筛选存在温和多重检验膨胀；重叠窗口致独立样本偏少（n_eff 调整已做）。")

    st.divider()
    st.caption("实盘映射：563020 / 515450 / 159307 / 159545（QDII，买入前过溢价 ≤3% 门控）· "
               "页面只读消费 src/dividend 冻结打分（不改权重与参数），计算 @st.cache_data 不落盘 · "
               "研究全文：dividend-research/HANDOFF.md · 规则出处：设计方案十二节")


main()
