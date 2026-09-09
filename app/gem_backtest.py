"""双动量 GEM 回测卡片页(DESIGN.md 回测页区块,2026-08-25 增补)。

只读 derived/backtests/ 落盘结果(页面不做回测引擎,回测由 CLI 产出):
PYTHONPATH=src uv run python -m strategy.backtest

用法:uv run streamlit run app/gem_backtest.py
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# AppTest 裸执行环境不把脚本目录加进 sys.path(streamlit run 会)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from components import BLUE, CATEGORICAL, GREEN_WASH, INK, INK2, MUTED, RED_WASH, base_layout

st.set_page_config(page_title="双动量 GEM 回测", layout="wide")

DERIVED = Path(__file__).resolve().parents[1] / "data" / "derived"
ASSET_NAMES = {"spx": "标普500", "hs300": "沪深300", "bond": "债券腿",
               "513500": "513500", "510310": "510310", "511260": "511260"}


@st.cache_data(ttl=3600)
def _load(tag: str) -> pd.DataFrame | None:
    p = DERIVED / "backtests" / f"gem_cn_{tag}.parquet"
    return pd.read_parquet(p) if p.exists() else None


@st.cache_data(ttl=3600)
def _load_trades(tag: str) -> pd.DataFrame | None:
    p = DERIVED / "backtests" / f"gem_cn_trades_{tag}.parquet"
    return pd.read_parquet(p) if p.exists() else None


@st.cache_data(ttl=3600)
def _benchmarks() -> dict[str, pd.Series]:
    """对照基准:沪深300 / 标普500折人民币 / 债券腿(日频 close)。"""
    root = DERIVED.parent / "raw"
    hs = pd.read_parquet(root / "index_daily/index_000300.parquet").set_index("date")["close"].rename("沪深300")
    spx = pd.read_parquet(root / "index_global/spx_inx.parquet").set_index("date")["close"]
    fx = pd.read_parquet(root / "fx/usdcny.parquet").set_index("date")["close"]
    spx_cny = (spx * fx.reindex(spx.index).ffill()).rename("标普500(折CNY)")
    bond = pd.read_parquet(DERIVED / "aligned/bond_leg_spliced_511260.parquet").set_index("date")["close"].rename("债券腿")
    return {"hs": hs, "spx_cny": spx_cny, "bond": bond}


def _nav_norm(s: pd.Series, idx: pd.DatetimeIndex) -> pd.Series | None:
    seg = s[s.index >= idx.min()]
    return (seg / seg.iloc[0]).reindex(idx).ffill() if len(seg) else None


def _stats_block(df: pd.DataFrame, label: str):
    nav, ret = df.set_index("date")["nav"], df.set_index("date")["ret"]
    yrs = len(nav) / 252.0
    cagr = nav.iloc[-1] ** (1 / yrs) - 1
    mdd = (nav / nav.cummax() - 1).min()
    sharpe = ret.mean() / ret.std() * 252 ** 0.5 if ret.std() > 0 else float("nan")
    calmar = cagr / abs(mdd) if mdd < 0 else float("nan")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("年化收益", f"{cagr:+.2%}")
    c2.metric("最大回撤", f"{mdd:.1%}")
    c3.metric("夏普 (rf=0)", f"{sharpe:.2f}")
    c4.metric("Calmar", f"{calmar:.2f}")
    st.caption(f"{label}:{nav.index.min():%Y-%m-%d} → {nav.index.max():%Y-%m-%d}({len(nav)} 交易日)")


def _nav_chart(df: pd.DataFrame) -> go.Figure:
    d = df.set_index("date")
    idx = d.index
    bench = _benchmarks()
    fig = go.Figure()
    fig.add_scatter(x=idx, y=d["nav"], name="双动量 GEM", line=dict(color=INK, width=2.4))
    for i, (key, cn) in enumerate([("hs", "沪深300"), ("spx_cny", "标普500(折CNY)"), ("bond", "债券腿")]):
        n = _nav_norm(bench[key], idx)
        if n is not None:
            fig.add_scatter(x=n.index, y=n.values, name=cn,
                            line=dict(color=CATEGORICAL[i + 1], width=1.6))
    base_layout(fig)
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.12))
    return fig


def _dd_chart(df: pd.DataFrame) -> go.Figure:
    d = df.set_index("date")
    bench = _benchmarks()
    hs = bench["hs"]
    hs = (hs / hs.cummax() - 1).reindex(d.index).ffill()
    fig = go.Figure()
    fig.add_scatter(x=d.index, y=hs * 100, name="沪深300 回撤", line=dict(color=CATEGORICAL[1], width=1.4),
                    fill="tozeroy", fillcolor="rgba(235,104,52,0.08)")
    fig.add_scatter(x=d.index, y=d["drawdown"] * 100, name="策略回撤", line=dict(color=INK, width=2.0),
                    fill="tozeroy", fillcolor="rgba(11,11,11,0.08)")
    base_layout(fig, y_title="%")
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.12))
    return fig


def _heatmap(df: pd.DataFrame) -> go.Figure:
    ret = df.set_index("date")["ret"]
    m = ret.groupby([ret.index.year, ret.index.month]).apply(lambda s: (1 + s).prod() - 1).unstack()
    m = m * 100
    fig = go.Figure(go.Heatmap(
        z=m.values, x=[f"{i}月" for i in m.columns], y=m.index.astype(str),
        colorscale=[[0.0, "#2a78d6"], [0.5, "#ffffff"], [1.0, "#eb6834"]],
        zmin=-8, zmax=8, text=m.round(1).values, texttemplate="%{text}",
        hovertemplate="%{y} %{x}: %{z:+.1f}%<extra></extra>",
    ))
    base_layout(fig)
    fig.update_layout(yaxis=dict(autorange="reversed"))
    fig.add_annotation(text="冷=负收益,暖=正收益(单位 %,色阶 ±8% 封顶)", showarrow=False,
                       xref="paper", yref="paper", x=0, y=-0.12, font=dict(color=MUTED, size=12))
    return fig


def _position_chart(df: pd.DataFrame) -> go.Figure:
    pos = df.set_index("date")["position"]
    changes = pos[pos.ne(pos.shift(1))]
    segs, start = [], None
    for d, p in changes.items():
        if start is not None:
            segs.append((start, d, prev))
        start, prev = d, p
    if start is not None:
        segs.append((start, pos.index[-1], prev))
    color_map = {"spx": CATEGORICAL[0], "hs300": CATEGORICAL[1], "bond": CATEGORICAL[2],
                 "513500": CATEGORICAL[0], "510310": CATEGORICAL[1], "511260": CATEGORICAL[2]}
    fig = go.Figure()
    for i, (a, b, p) in enumerate(segs):
        fig.add_trace(go.Scatter(
            x=[a, b], y=[0, 0], mode="lines",
            line=dict(color=color_map.get(p, CATEGORICAL[3]), width=14),
            name=ASSET_NAMES.get(p, p), legendgroup=p,
            showlegend=(i == next(j for j, (aa, bb, pp) in enumerate(segs) if pp == p)),
            hovertemplate=f"{ASSET_NAMES.get(p, p)}: %{{x|%Y-%m}} 起<extra></extra>",
        ))
    base_layout(fig)
    fig.update_layout(yaxis=dict(visible=False), showlegend=True,
                      legend=dict(orientation="h", y=1.12), margin=dict(t=60))
    fig.add_annotation(text="持仓时间线(换仓发生在月度执行日开盘)", showarrow=False,
                       xref="paper", yref="paper", x=0, y=-0.12, font=dict(color=MUTED, size=12))
    return fig


def _layer_view(tag: str, label: str):
    df = _load(tag)
    if df is None:
        st.info(f"未找到 derived/backtests/gem_cn_{tag}.parquet——先运行 "
                f"`PYTHONPATH=src uv run python -m strategy.backtest` 生成回测结果。")
        return
    _stats_block(df, label)
    st.plotly_chart(_nav_chart(df), width="stretch")
    st.plotly_chart(_dd_chart(df), width="stretch")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.plotly_chart(_heatmap(df), width="stretch")
    with c2:
        st.plotly_chart(_position_chart(df), width="stretch")
    trades = _load_trades(tag)
    if trades is not None and len(trades):
        t = trades.tail(24).copy()
        t["exec_date"] = t["exec_date"].dt.strftime("%Y-%m-%d")
        if "signal_date" in t.columns:
            t["signal_date"] = t["signal_date"].dt.strftime("%Y-%m-%d")
        st.dataframe(t.set_index("exec_date"), width="stretch", height=420)


def _compare_view():
    a, b = _load("index"), _load("etf")
    if a is None or b is None:
        st.info("两层结果不全,先跑 CLI。")
        return
    an, bn = a.set_index("date")["nav"], b.set_index("date")["nav"]
    start = max(an.index.min(), bn.index.min())
    seg_a, seg_b = an[an.index >= start], bn[bn.index >= start]
    ra, rb = a.set_index("date")["ret"], b.set_index("date")["ret"]
    n = min(len(ra), len(rb))
    diff = (ra[ra.index >= start].iloc[:n] - rb[rb.index >= start].iloc[:n]).dropna()

    def _cagr(seg):
        return seg.iloc[-1] ** (252 / len(seg)) - 1

    rows = {
        "共同区间起点": f"{start:%Y-%m-%d}",
        "年化(信号层·指数)": f"{_cagr(seg_a):+.2%}",
        "年化(执行层·ETF)": f"{_cagr(seg_b):+.2%}",
        "年化差(执行−信号)": f"{_cagr(seg_b) - _cagr(seg_a):+.2%}",
        "日收益差 p95 / p99": f"{diff.quantile(0.95):+.3%} / {diff.quantile(0.99):+.3%}",
        "差异来源(已知)": "ETF 跟踪差+费率;QDII 溢价门控(2020-03 nav 滞后假信号躲过熔断、2024 溢价大波动年择时);ETF 溢价中枢抬升",
    }
    st.table(pd.DataFrame({"指标": list(rows.keys()), "值": list(rows.values())}).set_index("指标"))
    fig = go.Figure()
    fig.add_scatter(x=seg_a.index, y=seg_a.values, name="信号层(指数)", line=dict(color=BLUE, width=1.8))
    fig.add_scatter(x=seg_b.index, y=seg_b.values, name="执行层(ETF)", line=dict(color=INK, width=1.8, dash="dot"))
    base_layout(fig)
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, width="stretch")


def _sweep_view():
    p = DERIVED / "backtests" / "gem_cn_sweep.parquet"
    if not p.exists():
        st.info("未找到 gem_cn_sweep.parquet——先运行 `PYTHONPATH=src uv run python -m strategy.sweep`。")
        return
    t = pd.read_parquet(p)
    st.caption(f"回望窗口网格 {sorted(t['lookback_m'].tolist())} 月 · 共同区间 2009-02 起 · "
               "通过线:回撤砍 40%+ 且年化 ≥ 基准 70%(AGENTS 验证纪律 5)")
    disp = t.copy()
    disp["cagr"] = (disp["cagr"] * 100).round(2).astype(str) + "%"
    disp["mdd"] = (disp["mdd"] * 100).round(1).astype(str) + "%"
    disp["dd_cut"] = (disp["dd_cut"] * 100).round(0).astype(int).astype(str) + "%"
    disp["cagr_ratio"] = disp["cagr_ratio"].round(1)
    disp["pass_line"] = disp["pass_line"].map({True: "✅", False: "❌"})
    disp = disp.rename(columns={"lookback_m": "回望(月)", "n_signals": "信号数", "cagr": "年化",
                                "mdd": "最大回撤", "sharpe": "夏普", "calmar": "Calmar",
                                "dd_cut": "回撤削减", "cagr_ratio": "年化/基准",
                                "pass_line": "通过线"})
    st.table(disp.set_index("回望(月)"))

    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure(go.Bar(x=t["lookback_m"].astype(str) + "M", y=t["cagr"] * 100,
                               marker_color=INK))
        base_layout(fig, y_title="年化 %")
        fig.update_layout(title="年化 vs 回望窗口")
        st.plotly_chart(fig, width="stretch")
    with c2:
        fig = go.Figure(go.Bar(x=t["lookback_m"].astype(str) + "M", y=t["mdd"] * 100,
                               marker_color=CATEGORICAL[1]))
        base_layout(fig, y_title="最大回撤 %")
        fig.update_layout(title="最大回撤 vs 回望窗口")
        st.plotly_chart(fig, width="stretch")
    n_pass = int(t["pass_line"].sum())
    st.markdown("> **判读**:" + (
        f"全域 {len(t)} 个窗口 **无一通过回撤线**——各窗口最大回撤几乎都锚在 −46.9%"
        "(2015-06 峰后持沪深300 吃完股灾下半场,仅转防御快慢有别)。"
        "这不是参数选择问题,是月频 + 月级回望的动量轮动在 A 股急牛急熊环境的**结构性水土不服**;"
        "按验证纪律(参数高原 vs 孤峰),本土化 GEM 判放弃,降级为反面参照。"
        if n_pass == 0 else
        f"{n_pass}/{len(t)} 个窗口通过,详见上表与 PROGRESS.md 判读。"))


def _baselines_view():
    vp = DERIVED / "backtests" / "baselines_verdict.parquet"
    sp = DERIVED / "backtests" / "baselines_sweep.parquet"
    if not vp.exists():
        st.info("未找到 baselines_verdict.parquet——先运行 "
                "`PYTHONPATH=src uv run python -m strategy.run_baselines`。")
        return
    t = pd.read_parquet(vp)
    disp = t.copy()
    for c in ["年化", "最大回撤", "回撤削减"]:
        disp[c] = (disp[c] * 100).round(1).astype(str) + "%"
    disp["年化/基准"] = disp["年化/基准"].round(1)
    disp["通过线"] = disp["通过线"].map({True: "✅", False: "❌"})
    st.caption("三基线信号层(设计文档第十一节)· 共同区间行与其他策略可比 · "
               "通过线:回撤砍 40%+ 且年化 ≥ 基准 70%")
    st.table(disp)

    st.markdown("> **第一轮判读**:Faber 10月均线 **✅ 通过**(SMA 6–15 月全域高原,回撤削减 59–64%),"
                "且 ETF 执行层复测一致(MDD −17.5% vs 信号层 −17.6%);FED 分位 ❌(expanding 分位在 "
                "ERP 结构性抬升下退化为永续持股,滚动 60M 亦无保护);GTAA ❌ 与 GEM 同病"
                "(月频动量排名挡不住 2015 型急跌)。")

    if sp.exists():
        st.caption("敏感性扫描(共同区间 2009-02 起,`scripts/sweep_baselines.py`)")
        s = pd.read_parquet(sp)
        sd = s.copy()
        sd["cagr"] = (sd["cagr"] * 100).round(2).astype(str) + "%"
        sd["mdd"] = (sd["mdd"] * 100).round(1).astype(str) + "%"
        sd["dd_cut"] = (sd["dd_cut"] * 100).round(0).astype(int).astype(str) + "%"
        sd["pass"] = sd["pass"].map({True: "✅", False: "❌"})
        sd = sd.rename(columns={"strategy": "策略", "param": "参数", "cagr": "年化",
                                "mdd": "最大回撤", "dd_cut": "回撤削减",
                                "sharpe": "夏普", "pass": "达标"})
        st.dataframe(sd.set_index(["策略", "参数"]), width="stretch", height=360)

    # 净值对比:四策略 + 基准
    fig = go.Figure()
    bench = _benchmarks()
    names = {"faber": "Faber 10月均线", "fed": "FED 分位", "gtaa": "GTAA"}
    colors = {"faber": INK, "fed": CATEGORICAL[3], "gtaa": CATEGORICAL[4]}
    common = None
    for tag, cn in names.items():
        df = _load_f(f"backtests/{tag}_index.parquet")
        if df is None:
            continue
        nav = df.set_index("date")["nav"]
        common = nav.index.min() if common is None else max(common, nav.index.min())
        fig.add_scatter(x=nav.index, y=nav.values, name=cn,
                        line=dict(color=colors[tag], width=1.8))
    gem = _load("index")
    if gem is not None:
        nav = gem.set_index("date")["nav"]
        fig.add_scatter(x=nav.index, y=nav.values, name="双动量 GEM(放弃)",
                        line=dict(color=MUTED, width=1.2, dash="dot"))
    hs = bench["hs"]
    if common is not None:
        hs = hs[hs.index >= common]
        fig.add_scatter(x=hs.index, y=(hs / hs.iloc[0]).values, name="沪深300 买入持有",
                        line=dict(color=CATEGORICAL[1], width=1.4))
    base_layout(fig)
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, width="stretch")


@st.cache_data(ttl=3600)
def _load_f(rel: str) -> pd.DataFrame | None:
    """按 derived 相对路径读回测明细(基线三策略)。"""
    p = DERIVED / rel
    return pd.read_parquet(p) if p.exists() else None


def main():
    st.header("双动量 GEM(中美本土化)回测")
    st.caption("方法:Gary Antonacci GEM 本土化——每月末比较标普500(折CNY)与沪深300 的 12 个月回报选强者;"
               "胜者跑不赢中债 3M 复利基准则转 511260 债券腿 · 次月首个交易日开盘调仓 · "
               "参数 12M/月度/零成本(第一轮原参数复现)。数据截止以图为准,信号 223 个月(2008-01→2026-07)。")

    with st.sidebar:
        layer = st.radio("回测层", ["信号层·指数", "执行层·ETF", "两层对照", "敏感性扫描", "基线三策略"],
                         help="信号层=干净价格(指数×汇率);执行层=ETF qfq,含 QDII 溢价 ≤3% 买入门控;"
                              "敏感性=回望窗口网格;基线三策略=Faber/FED/GTAA(设计文档第十一节)")

    if layer == "信号层·指数":
        _layer_view("index", "信号层")
    elif layer == "执行层·ETF":
        _layer_view("etf", "执行层")
    elif layer == "两层对照":
        _compare_view()
    elif layer == "敏感性扫描":
        _sweep_view()
    else:
        _baselines_view()

    st.divider()
    st.caption("数据契约:derived/backtests/ 实时读取(CLI 全量重算覆盖)· 复现命令 "
               "`PYTHONPATH=src uv run python -m strategy.backtest` · "
               "报告 reports/gem_cn_*.html(QuantStats)· 测试 scripts/test_gem_*.py")


main()
