"""红利低波簇策略信号页（设计文档十二节展示层）。

范式 = 策略页（faber_strategy.py，DESIGN.md 第二节 2026-08-26 增补）：
当前信号状态区置顶 + 证据链 + 页脚实盘映射。内容 = 四标的打分分位
（五档贵贱）+ P(1年收益>0) + 机械操作建议（低估分批建仓/公允持有/高估减仓）；
159545 为 QDII，买入建议叠加溢价率 ≤3% 门控（超门控显示"等待溢价回落"）。

打分历史之后为「打分 × 后续走势（历史自证）」区块（A 五档前瞻收益表 /
B 散点 + Spearman IC / C 极低估事件研究，计算在 src/dividend/forward.py
纯函数层，复刻估值页 IC 自证范式）；159545 样本不足时事件研究显示
"样本不足，不可外推"提示，不画误导性曲线。

定位诚实声明：主项目 walk-forward + holdout 终验已完成（设计文档十三节，2026-09-21）——
WF 样本外通过、holdout 夏普未达 >1 → 维持「信号观察」，死因见页底证据链；
计算全部 @st.cache_data 不落盘（AGENTS.md 规则 5）；PASEO_MARKET_OFFLINE=1 时溢价区显示离线兜底提示，
不阻断其余内容（以行情监控页为准）。

用法：uv run streamlit run app/dividend_page.py
测试：PASEO_MARKET_OFFLINE=1 uv run python scripts/test_dividend_page.py
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from components import (BLUE, CATEGORICAL, GREEN_WASH, GRID, INK, INK2, MUTED,
                        RED_WASH, base_layout, tier_fill, tier_text)
from dividend.cards import (CALIBER_LABELS, CLUSTER_WEIGHT_RANGE, INSTRUMENTS, ORDER,
                            PREMIUM_CAP, RATING_LEVELS, SUGGESTED_WEIGHTS,
                            advice_for_pct, apply_premium_gate, compute_cards)
from dividend.cards import DividendCard  # noqa: F401  (类型留档，页面只读消费)
from dividend.forward import HORIZONS, IC_MIN_N, compute_self_check

st.set_page_config(page_title="红利低波簇策略信号", page_icon="🧧", layout="wide")

# 溢价警示橙 = 行情监控页溢价语义色（DESIGN.md：色永伴文字，不用黄——
# 黄已是五档"公允"专属语义）
PREMIUM_WARN = "#ec835a"


@st.cache_data(ttl=3600)
def _cards(caliber: str) -> dict:
    return compute_cards(caliber)


@st.cache_data(ttl=3600)
def _self_check() -> dict:
    """打分 × 后续走势三件套（纯函数在 src/dividend/forward.py，不落盘）。"""
    return compute_self_check()


@st.cache_data(ttl=300)
def _premium_159545() -> tuple[float | None, str, bool]:
    """159545 溢价率（百分数）、口径标注、是否离线。

    口径同行情监控页：ETF 价 ÷ 最新单位净值 − 1（单位净值，非累计净值）。
    PASEO_MARKET_OFFLINE=1 时不发网络请求，premium=None + offline=True。
    只走新浪单票快照（timeout 8s，由 quotes 模块保证）——本页不调用 collect_quotes()
    全量链：云上对新浪/东财不可达时东财兜底会重试到分钟级，阻塞整页首渲（2026-09-21 实测）。
    新浪不可达时 premium=None，页面降级为提示自行核对行情监控页，语义不变。
    """
    offline = os.environ.get("PASEO_MARKET_OFFLINE") == "1"
    if offline:
        return None, "离线模式", True
    from data_module.quotes import _latest_nav, _sina_etf_quotes

    try:
        q = _sina_etf_quotes(["159545"]).get("159545")
    except Exception:
        q = None
    nav = _latest_nav("159545")
    if q is None or not q.price or nav is None:
        src = q.source if q else "新浪不可达"
        return None, (f"{src}（净值缺失）" if nav is None else src), False
    premium = (float(q.price) / nav[0] - 1) * 100
    asof = f"{q.source} {q.asof} · 净值 {nav[1]}"
    return premium, asof, False


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


def _tier_table_html(tbl: pd.DataFrame) -> str:
    """A · 五档前瞻收益表（HTML 表：行=五档档色徽章，列=各期限中位数/胜率/样本数）。

    数值一律墨字（DESIGN.md：本页禁用红涨绿跌行情语义）；无样本格显示 ——。
    """
    def cell(r: pd.Series, h: int) -> str:
        if not r[f"n_{h}"]:
            return f'<div style="color:{MUTED}">—</div>'
        return (f'<div style="color:{INK};font-weight:600">{r[f"med_{h}"] * 100:+.1f}%</div>'
                f'<div style="color:{INK2};font-size:0.82rem">胜率 {r[f"win_{h}"] * 100:.0f}%'
                f'<span style="color:{MUTED}"> · n={r[f"n_{h}"]}</span></div>')

    th = (f'padding:6px 10px;text-align:center;color:{MUTED};font-weight:600;'
          f"border-bottom:2px solid {GRID}")
    head = "".join(f"<th style='{th}'>之后 {h} 日</th>" for h in HORIZONS)
    rows = []
    for _, r in tbl.iterrows():
        tier = int(r["tier"])
        badge = (f'<span style="background:{tier_fill(tier)};color:{tier_text(tier)};'
                 f'border-radius:6px;padding:3px 12px;font-weight:600">{r["label"]}</span>')
        cells = "".join(f"<td style='padding:8px 10px;text-align:center;"
                        f"border-bottom:1px solid {GRID}'>{cell(r, h)}</td>"
                        for h in HORIZONS)
        rows.append(f"<tr><td style='padding:8px 10px;border-bottom:1px solid {GRID}'>{badge}</td>"
                    f"{cells}</tr>")
    return (f'<table style="border-collapse:collapse;width:100%"><thead><tr>'
            f"<th style='{th};text-align:left'>打分档位</th>{head}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def _scatter_fig(res: dict, label: str, horizon: int) -> go.Figure:
    """B · 打分分位 vs 未来 h 日收益散点 + OLS 趋势线（蓝）+ IC 标注。"""
    d = res["df"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=d["pct"], y=d["fwd"] * 100, mode="markers",
        marker=dict(color=INK2, size=6, opacity=0.45),  # 散点淡墨
        text=d["date"].dt.strftime("%Y-%m-%d"),
        hovertemplate="%{text}：分位 %{x:.0f}% → 未来%{y:+.1f}%<extra></extra>",
    ))
    if len(d) >= 12:
        k_, b_ = np.polyfit(d["pct"], d["fwd"] * 100, 1)
        x0, x1 = float(d["pct"].min()), float(d["pct"].max())
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[k_ * x0 + b_, k_ * x1 + b_], mode="lines",
            name="OLS 趋势线（判读辅助，非预测）", line=dict(color=BLUE, width=2),
        ))
    ic_txt = f"Spearman IC = {res['ic']:+.2f}" if res["n"] >= IC_MIN_N else "样本不足不报 IC"
    fig.add_hline(y=0, line=dict(color=MUTED, width=1))
    base_layout(fig, "未来收益(%)")
    fig.update_layout(
        title=f"{label}：打分分位 vs 未来 {horizon} 日全收益（{ic_txt}，n={res['n']}）",
        showlegend=True, legend=dict(orientation="h", y=1.12),
        xaxis=dict(title="打分分位（expanding 当时视角，无前视；高=贵）",
                   range=[0, 100], zeroline=False),
    )
    return fig


def _event_fig(res: dict, label: str) -> go.Figure:
    """C · 极低估事件路径 vs 全部交易日等权基准（categorical 双色，双序列图例）。"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=res["event_path"].index, y=res["event_path"].values * 100, mode="lines",
        name=f"极低估事件路径（n={res['n_events']}，{res['first_event']} ~ {res['last_event']}）",
        line=dict(color=BLUE, width=2.2),
        hovertemplate="T+%{x}：%{y:+.1f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=res["baseline_path"].index, y=res["baseline_path"].values * 100, mode="lines",
        name="全部交易日等权基准",
        line=dict(color=CATEGORICAL[1], width=1.8, dash="dash"),
        hovertemplate="T+%{x}：%{y:+.1f}%<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color=MUTED, width=1))
    base_layout(fig, "累计收益(%)")
    fig.update_layout(
        title=f"{label}：首次进入极低估区（<20%）后 {res['window']} 个交易日平均累计收益",
        showlegend=True, legend=dict(orientation="h", y=1.12),
        xaxis=dict(title="事件后交易日", zeroline=False),
    )
    return fig


def _evidence_block() -> None:
    """证据链摘要（实测与裁决分离纪律：WF/holdout 实测照登，不粉饰）。"""
    rows = [
        ("因子筛选", "16 候选因子 → 幸存 4 个家族（252 日反转 / 盈利收益率利差 / −PE / 股息率·ERP 分位）；"
         "全样本 IC + expanding 分档单调 + 滚动 ICIR + 2024+ 样本外，四重验证", "✅ 通过"),
        ("权重估计", "样本内（≤2023）126 日滚动 ICIR 归一化，永久冻结；迁移仅修复分位因子前视"
         "（取值截至前一交易日），权重一个数未改", "✅ 冻结"),
        ("样本外检验", "冻结模型逐周模拟历史预测（2024+，无未来函数）；非重叠抽样后相关仍 p<0.01；"
         "logistic 概率对照全面落败，频率法为最优概率模型", "✅ 通过"),
        ("主项目 walk-forward", "基线 5 验证（设计文档十三节）：训练 5 年/测试 1 年滚动（2020 起），"
         "网格 18 组 Calmar 机械选参；样本外拼接 2020-01→2025-09：年化 +2.00%、MDD −1.61%"
         "（簇等权 B&H −16.39%，削减 90%）、夏普 1.06 → 通过线（夏普>1 且削减≥40%）", "✅ 通过"),
        ("主项目 holdout 终验", "冻结规则 enter=40/exit=70/hyst=0（末段 WF 选参），2025-09-15→2026-09-14 "
         "untouched 一次：年化 +1.80%、MDD −3.05%（簇 B&H −13.39%，削减 77%）、夏普 0.57 < 1 "
         "→ 未通过（回撤控制好但收益性不足）", "❌ 未通过"),
        ("终局裁决", "按十三节处置：holdout 未过 → 保持「信号观察」，死因如实记录"
         "（holdout 失败但 WF 强，可提请用户裁决——Faber 2026-08-26 先例）；"
         "复现：PYTHONPATH=src uv run --no-sync python -m dividend.walkforward", "⚠️ 信号观察"),
    ]
    st.table(pd.DataFrame(rows, columns=["检验", "结果摘要", "判"]))


def main() -> None:
    st.header("🧧 红利低波簇策略信号")
    st.caption("四标的打分分位（五档贵贱）+ P(1年收益>0) + 机械操作建议 · "
               "打分 = expanding z × ≤2023 样本内 ICIR 冻结权重 · 纯估值口径回答「贵贱」，"
               "含动量口径回答「赢面」（对照见下表）· "
               "定位「信号观察」：主项目 walk-forward 已过、holdout 夏普未达线"
               "（证据链与声明见页底）")

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

    # ── ⑤ 打分 × 后续走势（历史自证；与证据链"四重验证"互证不重复）──
    st.subheader("打分 × 后续走势（历史自证）")
    st.caption("打分 = 纯估值口径分位（expanding 当时视角，T 日信号仅用 T-1 及以前数据，无前视）；"
               "前瞻收益 = 未来 h 个交易日全收益（标签天然向后）。重叠前瞻窗口使样本非独立，"
               "全部统计只做判读、不做 p 值断言。")
    self_check = _self_check()
    sel_cols = st.columns([1, 2])
    with sel_cols[0]:
        sc_code = st.selectbox("标的", ORDER,
                               format_func=lambda c: INSTRUMENTS[c]["label"], index=0)
    sc_label = INSTRUMENTS[sc_code]["label"]

    # A · 五档前瞻收益表
    st.markdown(f"**A · 五档前瞻收益（{sc_label}）**：打分分位按 "
                "<20 / 20-40 / 40-60 / 60-80 / ≥80 分五档，统计每档**之后**各期限全收益")
    st.markdown(_tier_table_html(self_check[sc_code]["tier"]), unsafe_allow_html=True)
    st.caption("中位数/胜率单位为小数收益换算；前瞻窗口重叠（同一交易日同时落入多期统计），"
               "各档样本非独立；前瞻期限越长可观测样本越少（末段不足 h 日的交易日无标签）。")

    # B · 散点 + Spearman IC（复刻估值页 IC 自证范式）
    with sel_cols[1]:
        sc_h = st.radio("前瞻期限", list(HORIZONS), horizontal=True, index=0,
                        format_func=lambda h: f"未来 {h} 日")
    st.markdown(f"**B · 打分分位 vs 未来收益（{sc_label}）**：散点淡墨 + 蓝色 OLS 趋势线（判读辅助，非预测）")
    sc_res = self_check[sc_code]["scatter"][sc_h]
    st.plotly_chart(_scatter_fig(sc_res, sc_label, sc_h), width="stretch")
    st.caption(f"IC = 打分分位与未来收益的 Spearman 秩相关（覆盖 {sc_res['coverage_start']} ~ "
               f"{sc_res['coverage_end']}）。实测本簇打分各期限 IC > 0（历史上分位越高、后续收益越高），"
               "与「低估建仓」直觉方向相反——打分是估值状态刻画而非收益预测，此结果如实呈现，判读须谨慎。")

    # C · 事件研究（首次进入极低估区后 252 日；样本不足不画曲线）
    st.markdown(f"**C · 极低估事件研究（{sc_label}）**：打分首次进入 <20% 极低估区的事件日 T 后 "
                "252 个交易日平均累计收益 vs 全部交易日等权基准")
    ev = self_check[sc_code]["event"]
    if ev["ok"]:
        st.plotly_chart(_event_fig(ev, sc_label), width="stretch")
        st.caption("事件口径：T 日打分首次 <20%（T-1 不在区内；连续在区间只取首次进入日，避免重叠事件"
                   "过度重复——同一轮低估只计一次）；事件后不足 252 个交易日的样本不计入"
                   f"（本标的另有 {ev['n_skipped_incomplete']} 起尾部截断）。基准 = 全部交易日等权"
                   "平均的同期累计收益（同一全收益序列、同一窗口）。重叠窗口样本非独立，不做显著性断言。")
    else:
        st.warning(f"**{sc_label}** 极低估事件样本不足（完整 252 日窗口事件 n={ev['n_events']} < 5，"
                   f"另有 {ev['n_skipped_incomplete']} 起事件因历史太短、事件后不足 252 日而截断）"
                   "——样本不足，不可外推，不画事件曲线（口径与打分卡 ⚠️不可外推 标记一致）。")

    # ── ⑥ 证据链与诚实声明 ──
    st.subheader("证据链（全部检验的完整记录）")
    _evidence_block()
    st.caption("已知局限（HANDOFF 诚实展示）：515450/159545 缺 PE（股息率/ERP 口径代理，"
               "515450 的 DV 代理系统性偏低约 1pt）；159545 历史仅 2.5 年，概率不可外推；"
               "16 因子筛选存在温和多重检验膨胀；重叠窗口致独立样本偏少（n_eff 调整已做）。")

    st.divider()
    st.caption("实盘映射：563020 / 515450 / 159307 / 159545（QDII，买入前过溢价 ≤3% 门控）· "
               "页面只读消费 src/dividend 冻结打分（不改权重与参数），计算 @st.cache_data 不落盘 · "
               "研究全文：dividend-handoff.md（私有文档仓 coboo/paseo-docs，含完整研究过程）· 规则出处：设计方案十二节")


main()
