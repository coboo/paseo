"""A股估值仪表盘（设计文档第六节展示层，CMV 复刻 v1）。

对标 currentmarketvaluation.com 的模型页五件套：当前值大字 → 偏离 σ →
五档评级红绿灯 → 历史走势 + ±1σ/±2σ 标准差带 → 白话解释。
指标实时计算不落盘（AGENTS.md 规则 5），st.cache_data 缓存 1 小时。

用法：uv run streamlit run app/valuation_dashboard.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# AppTest 等裸执行环境不会把脚本目录加进 sys.path（streamlit run 会）
sys.path.insert(0, str(Path(__file__).resolve().parent))
# 云上部署（Streamlit Community Cloud）没有 uv 把 src/ 装进 site-packages，
# metrics 包靠仓库内路径直接导入（与 faber_strategy.py 同模式）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from components import (
    BLUE,
    GREEN_WASH,
    GRID,
    INK,
    INK2,
    MUTED,
    RED_WASH,
    base_layout,
    tier_fill,
    tier_text,
)
from metrics import (
    RATING_LEVELS,
    WINDOW_LABELS,
    buffett_indicator,
    buffett_monthly,
    composite,
    composite_series,
    credit_spread,
    credit_spread_daily,
    curve_10y3m,
    curve_daily,
    direction_sign,
    dividend_spread,
    dividend_spread_daily,
    erp_000300,
    erp_daily,
    epu_china,
    epu_monthly,
    expanding_val_z,
    ma250_daily,
    ma250_dev,
    margin_debt,
    margin_debt_monthly,
    monthly_sample,
    pe_000300,
    pe_daily,
    pmi_momentum,
    pmi_momentum_monthly,
    qvix_50etf,
    qvix_daily,
    rating_from_z,
    rates_10y,
    rates_daily,
    sahm_monthly,
    sahm_rule,
)
from metrics import CARDS  # IC 自证区块:卡片键 → 中文名映射(_IC_LABELS)
from metrics.validate import ic_table, scatter_data

# 模型注册表：新增估值模型在此补一行（函数须输出 MetricResult）
# EPU/Sahm 不参与综合分(数据停滞/样本短),仅独立展示(aggregate.py docstring 声明)
MODELS = {
    "composite": "股债性价比综合分（11 卡等权）",
    "erp_000300": "股债利差 ERP（FED 模型）",
    "curve_10y3m": "收益率曲线（10Y−3M）",
    "dividend_spread": "股息率 − 10Y 国债（全A）",
    "pe_000300": "沪深300 PE（TTM）",
    "ma250_dev": "偏离 250 日均线",
    "rates_10y": "10Y 国债收益率",
    "qvix_50etf": "QVIX 情绪（50ETF，逆向）",
    "margin_debt": "两融杠杆变化（占市值比）",
    "buffett_indicator": "巴菲特指标（总市值/GDP）",
    "credit_spread": "信用利差（中短票AAA−国债）",
    "pmi_momentum": "PMI 景气动量（对比12M均线）",
    "epu_china": "EPU 政策不确定性（逆向，读数滞后）",
    "sahm_rule": "Sahm 规则（失业率缺口，样本短）",
}
# 分发表：模型 → (主函数, 日频中间量函数, 序列列名, 方向)——expanding 副图共用
_MODEL_SPECS: dict = {
    "composite": (composite, None, None, None),   # expanding 副图走特判(composite_series)
    "erp_000300": (erp_000300, erp_daily, "erp", "inverse"),
    "pe_000300": (pe_000300, pe_daily, "pe_ttm", "positive"),
    "ma250_dev": (ma250_dev, ma250_daily, "dev", "positive"),
    "rates_10y": (rates_10y, rates_daily, "yield_10y", "positive"),
    "qvix_50etf": (qvix_50etf, qvix_daily, "qvix", "inverse"),
}

# 历史锚点回验（事后注记为人工判读；估值z 由 expanding 当时视角动态计算）
ANCHORS = [
    ("2007-10", "六千点泡沫顶", "随后一年指数腰斩"),
    ("2014-06", "估值大底", "随后一年近乎翻倍"),
    ("2018-12", "熊市尾段", "2019 年大幅反弹"),
    ("2024-02", "微盘流动性危机", "随后两年修复行情"),
]


_MODEL_SPECS.update({
    "curve_10y3m": (curve_10y3m, curve_daily, "spread", "inverse"),
    "dividend_spread": (dividend_spread, dividend_spread_daily, "spread", "inverse"),
    "margin_debt": (margin_debt, margin_debt_monthly, "ratio", "positive"),
    "buffett_indicator": (buffett_indicator, buffett_monthly, "mv_gdp", "positive"),
    "credit_spread": (credit_spread, credit_spread_daily, "spread", "inverse"),
    "pmi_momentum": (pmi_momentum, pmi_momentum_monthly, "mom", "inverse"),
    "epu_china": (epu_china, epu_monthly, "epu", "inverse"),
    "sahm_rule": (sahm_rule, sahm_monthly, "gap", "positive"),
})


@st.cache_data(ttl=3600)
def _metric_cached(model: str, window: int | None):
    """当天级缓存：指标计算亚秒级，1 小时 TTL 已远超需要。"""
    return _MODEL_SPECS[model][0](window)


@st.cache_data(ttl=3600)
def _expanding_cached(model: str) -> pd.Series:
    if model == "composite":
        return composite_series()   # 综合卡的 series 本身即 expanding 等权平均
    _, daily_fn, col, direction = _MODEL_SPECS[model]
    df = daily_fn()
    monthly = monthly_sample(df.set_index("date")[col])
    return expanding_val_z(monthly, direction_sign(direction))


# ────────────────────────── 绘图 ──────────────────────────
# 图面与色彩组件见 app/components.py（DESIGN.md 第七节）。


def _fig_erp(m) -> go.Figure:
    """主图：全历史月频 ERP + 所选窗口均值线与 ±1σ/±2σ 界线 + 极值区 wash。

    ERP 为反向指标（高=便宜）：+2σ 上方涂绿、−2σ 下方涂红。
    """
    s = m.series
    fig = go.Figure()
    y_hi = max(float(s.max()) * 1.05, m.stats.hi2 + 0.5)
    y_lo = min(float(s.min()) * 1.05, m.stats.lo2 - 0.5)
    # 极值区 wash（大面积填充只取 8% 透明度）
    fig.add_hrect(y0=m.stats.hi2, y1=y_hi, fillcolor=GREEN_WASH, line_width=0,
                  annotation_text="极便宜区 ≥ +2σ", annotation_font=dict(color=MUTED, size=11))
    fig.add_hrect(y0=y_lo, y1=m.stats.lo2, fillcolor=RED_WASH, line_width=0,
                  annotation_text="极贵区 ≤ −2σ", annotation_font=dict(color=MUTED, size=11))
    # σ 界线（阈值语义 → 点线）与均值线（虚线）
    for y, txt in [(m.stats.lo2, "−2σ"), (m.stats.lo1, "−1σ"),
                   (m.stats.hi1, "+1σ"), (m.stats.hi2, "+2σ")]:
        fig.add_hline(y=y, line=dict(color=MUTED, width=1, dash="dot"),
                      annotation_text=f"{txt}={y:.1f}", annotation_font=dict(color=MUTED, size=10),
                      annotation_position="bottom right")
    fig.add_hline(y=m.stats.mean, line=dict(color=INK2, width=1.5, dash="dash"),
                  annotation_text=f"均值 {m.stats.mean:.2f}（{m.window}）",
                  annotation_font=dict(color=INK2, size=11))
    # 主序列（单序列蓝 2px，无图例——标题即命名）
    fig.add_trace(go.Scatter(
        x=s.index, y=s.values, name="ERP", mode="lines",
        line=dict(color=BLUE, width=2),
        hovertemplate="%{x|%Y-%m}：ERP %{y:+.2f}pp<extra></extra>",
    ))
    fig = base_layout(fig, "百分点")
    fig.update_layout(title=f"股债利差月频走势（{s.index[0]:%Y-%m} 起）与 σ 带")
    return fig


def _fig_val_z(ez: pd.Series) -> go.Figure:
    """副图：expanding 当时视角估值z——历史每个时点"当时怎么看"。

    无前视（每点仅用截至当时样本，≥50 个月才输出）；±2σ 外按估值语义着色。
    """
    fig = go.Figure()
    ymax = max(2.5, float(ez.abs().max()) * 1.1)
    fig.add_hrect(y0=2, y1=ymax, fillcolor=RED_WASH, line_width=0)
    fig.add_hrect(y0=-ymax, y1=-2, fillcolor=GREEN_WASH, line_width=0)
    for y in (-2, -1, 1, 2):
        fig.add_hline(y=y, line=dict(color=MUTED, width=1, dash="dot"))
    fig.add_hline(y=0, line=dict(color=INK2, width=1))
    fig.add_trace(go.Scatter(
        x=ez.index, y=ez.values, name="估值z", mode="lines",
        line=dict(color=BLUE, width=2), connectgaps=False,
        hovertemplate="%{x|%Y-%m}：估值z %{y:+.2f}<extra></extra>",
    ))
    fig = base_layout(fig, "估值z（σ）")
    fig.update_layout(
        title="历史评级演进（expanding 当时视角，无前视；2006–2009 样本不足不评级）",
        yaxis=dict(range=[-ymax, ymax], gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED)),
    )
    return fig


def _tier_bar(m) -> str:
    """五档红绿灯色条（HTML）：每档 σ 范围 + 色块 + 档名，当前档加粗描边。

    色块呈现色与文字墨/白一律走 components.tier_fill/tier_text（DESIGN.md 3.1
    表——当前档与非常住档同规则，浅底档用墨字）。
    """
    tiers = [(1, "≤ −2σ"), (2, "−2σ ~ −1σ"), (3, "±1σ"), (4, "+1σ ~ +2σ"), (5, "≥ +2σ")]
    cells = []
    for r, rng in tiers:
        active = r == m.rating
        edge = f"border:3px solid {INK};" if active else "border:3px solid transparent;"
        mark = "▲ 当前" if active else ""
        cells.append(
            f'<div style="flex:1;text-align:center">'
            f'<div style="font-size:0.78rem;color:{MUTED};margin-bottom:2px">{rng}</div>'
            f'<div style="background:{tier_fill(r)};{edge}border-radius:8px;padding:8px 0;'
            f'color:{tier_text(r)};font-weight:600;font-size:0.95rem">{RATING_LEVELS[r]["label"]}</div>'
            f'<div style="font-size:0.75rem;color:{INK2};height:1.1em;margin-top:2px">{mark}</div>'
            f"</div>"
        )
    return f'<div style="display:flex;gap:8px;margin:6px 0 2px">{"".join(cells)}</div>'


# ────────────────────────── 页面 ──────────────────────────

st.set_page_config(page_title="A股估值仪表盘", page_icon="📈", layout="wide")

with st.sidebar:
    st.title("📈 A股估值仪表盘")
    model_key = st.selectbox("估值模型", list(MODELS), format_func=MODELS.get)
    # 窗口选项用显式字符串（'10y'/'full'），避免 None 值在 radio/测试工具里的歧义
    choice = st.radio(
        "σ 口径窗口（主口径近 10 年，可切全历史对照）",
        ["10y", "full"],
        format_func={"10y": WINDOW_LABELS[10], "full": WINDOW_LABELS[None]}.get,
    )
    window_years = None if choice == "full" else 10
    st.divider()
    with st.expander("σ 评估方法"):
        st.markdown(
            "1. 月频（月末）采样计算均值/σ\n"
            "2. `估值z = (当前−均值)/σ × 方向`，负=便宜（绿）、正=贵（红）\n"
            "3. 五档：≤−2σ 极低估 / −2~−1σ 低估 / ±1σ 公允 / +1~+2σ 高估 / ≥+2σ 极高估\n"
            "4. 双窗口：主口径近 10 年（利率中枢下移后全历史带过宽）\n"
            "5. 历史评级一律 expanding 当时视角，≥50 个月样本才输出"
        )

m = _metric_cached(model_key, window_years)

st.header(m.name)
st.caption(
    f"数据截止 {m.updated} · {m.window}口径（{m.stats.start} 起 {m.stats.n} 个月，"
    f"均值 {m.stats.mean:.2f}、σ {m.stats.sd:.2f}）"
)

# 五件套 1+2：当前值大字 + 评级徽章（偏离 σ）
c_val, c_badge = st.columns([3, 2])
with c_val:
    st.markdown(
        f'<div style="font-size:3.2rem;font-weight:700;color:{INK};line-height:1">'
        f"{m.current:+.2f}<span style='font-size:1.1rem;color:{MUTED};font-weight:400'>"
        f" {m.unit}</span></div>"
        f'<div style="color:{MUTED};margin-top:4px">当前值 · {m.name}</div>',
        unsafe_allow_html=True,
    )
with c_badge:
    st.markdown(
        f'<div style="background:{tier_fill(m.rating)};color:{tier_text(m.rating)};'
        f'border-radius:10px;padding:14px 20px;text-align:center;margin-top:6px">'
        f'<div style="font-size:1.6rem;font-weight:700">{RATING_LEVELS[m.rating]["label"]}</div>'
        f'<div style="font-size:0.95rem;opacity:.92">{m.sigma:+.2f}σ 偏离历史均值</div>'
        f"</div>",
        unsafe_allow_html=True,
    )

# 五件套 3：五档红绿灯色条
st.markdown(_tier_bar(m), unsafe_allow_html=True)
st.caption("估值z 口径：负 = 股票相对债券便宜（绿），正 = 贵（红）。")

# 五件套 4：主图（全历史走势 + 所选窗口 σ 带）＋ 副图（expanding 估值z）
st.plotly_chart(_fig_erp(m), width="stretch")
st.plotly_chart(_fig_val_z(_expanding_cached(model_key)), width="stretch")

# 五件套 5：白话解释
st.markdown(f"> {m.desc}")

# 双窗口对照 + 锚点回验
c_tbl, c_anchor = st.columns([1, 1])
with c_tbl:
    st.subheader("双窗口对照")
    other = 10 if window_years is None else None
    m2 = _metric_cached(model_key, other)
    rows = [
        dict(窗口=mm.window, 当前值=f"{mm.current:+.2f}", 均值=f"{mm.stats.mean:.2f}",
             σ=f"{mm.stats.sd:.2f}", 估值z=f"{mm.sigma:+.2f}",
             评级=RATING_LEVELS[mm.rating]["label"])
        for mm in (m, m2)
    ]
    st.table(pd.DataFrame(rows))
with c_anchor:
    st.subheader("历史锚点回验")
    ez = _expanding_cached(model_key)
    rows = []
    for ym, name, after in ANCHORS:
        seg = ez[ez.index <= f"{ym}-28"]
        v = seg.iloc[-1] if len(seg) else float("nan")
        ok = pd.notna(v)
        r = rating_from_z(v) if ok else None
        rows.append(
            dict(时点=ym, 事件=name,
                 当时估值z=f"{v:+.2f}" if ok else "样本不足",
                 当时评级=RATING_LEVELS[r]["label"] if r else "—", 事后=after)
        )
    st.table(pd.DataFrame(rows))

st.divider()

# ── 估值分 vs 未来收益(IC 自证,CMV Correlations 页复刻)──
# 期望方向:IC < 0(估值z 低=便宜 → 未来收益高)。只支持综合分 + 参与综合的卡
# (EPU/Sahm 不在 CARDS,无 expanding 综合口径,不入口径混淆)。
st.subheader("估值分 vs 未来收益（IC 自证）")
_IC_KEYS = ["composite"] + [k for k, *_ in CARDS]
_IC_LABELS = {
    "composite": MODELS["composite"], "erp": MODELS["erp_000300"],
    "curve": MODELS["curve_10y3m"], "divspread": MODELS["dividend_spread"],
    "pe": MODELS["pe_000300"], "ma250": MODELS["ma250_dev"],
    "rates10y": MODELS["rates_10y"], "qvix": MODELS["qvix_50etf"],
    "margin": MODELS["margin_debt"], "buffett": MODELS["buffett_indicator"],
    "credit": MODELS["credit_spread"], "pmi": MODELS["pmi_momentum"],
}


@st.cache_data(ttl=3600)
def _ic_table_cached() -> pd.DataFrame:
    return ic_table()


@st.cache_data(ttl=3600)
def _scatter_cached(key: str, horizon: int) -> pd.DataFrame:
    return scatter_data(key, horizon)


ic_df = _ic_table_cached()
show_ic = ic_df.copy()
show_ic["card"] = show_ic["card"].map(lambda k: _IC_LABELS.get(k, k))
show_ic.columns = ["卡片", "IC(1年)", "n(1年)", "覆盖(1年)", "IC(3年)", "n(3年)", "覆盖(3年)"]
st.table(show_ic)

c_sc1, c_sc2 = st.columns([1, 1])
with c_sc1:
    sc_key = st.selectbox("散点卡片", _IC_KEYS, format_func=_IC_LABELS.get, index=0)
with c_sc2:
    sc_h = st.radio("收益 horizon", [1, 3], format_func={1: "未来 1 年", 3: "未来 3 年"}.get,
                    horizontal=True)
sd = _scatter_cached(sc_key, sc_h)
ic_row = ic_df[ic_df["card"] == sc_key].iloc[0]
ic_val = ic_row[f"ic_{sc_h}y"]
fig_sc = go.Figure()
fig_sc.add_trace(go.Scatter(
    x=sd["z"], y=sd["fwd"], mode="markers", marker=dict(color=BLUE, size=7, opacity=0.65),
    text=sd["date"].dt.strftime("%Y-%m"),
    hovertemplate="%{text}：估值z %{x:+.2f} → 未来%{y:+.1f}%<extra></extra>",
))
# OLS 趋势线(判读辅助,非预测)
if len(sd) >= 12:
    k_, b_ = np.polyfit(sd["z"], sd["fwd"], 1)
    x0, x1 = float(sd["z"].min()), float(sd["z"].max())
    fig_sc.add_trace(go.Scatter(
        x=[x0, x1], y=[k_ * x0 + b_, k_ * x1 + b_], mode="lines",
        line=dict(color=INK2, width=1.5, dash="dash"), showlegend=False,
        hoverinfo="skip",
    ))
fig_sc = base_layout(fig_sc, "未来收益(%)")
fig_sc.update_layout(
    title=f"{_IC_LABELS[sc_key]}：估值z vs 沪深300 未来 {sc_h} 年收益"
          f"（Spearman IC = {ic_val:+.2f}，n={int(ic_row[f'n_{sc_h}y'])}）",
    xaxis=dict(title="expanding 估值z（当时视角，无前视）", gridcolor=GRID,
               zeroline=True, zerolinecolor=MUTED, tickfont=dict(color=MUTED)),
)
st.plotly_chart(fig_sc, width="stretch")
st.caption(
    "口径：expanding 当时视角估值z（≥50 个月样本才输出）× 沪深300 月末价未来 1/3 年收益，"
    "Spearman 秩相关；IC<0 = 便宜时未来收益高（σ 方法期望方向）。月频观测非独立，"
    "显著性偏乐观，不做 p 值断言；综合分样本 2019-03 起（3 年口径 n≈55），结论仅供参考。"
)

st.divider()
st.caption("指标层 MetricResult 实时计算、不落盘；综合评分与其余模型卡片随第 4 步扩展。")
