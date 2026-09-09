"""Faber 10月均线策略页(第 4 步策略卡片化,项目唯一通过验收的策略)。

区块(DESIGN.md 回测页区块 + 策略页新增"当前信号状态"区,见 DESIGN.md 第二节增补):
①元信息 ②当前信号状态(距均线/权重/下次调仓) ③指标摘要 ④净值 ⑤回撤
⑥证据链摘要(主检验/敏感性/WF/holdout+裁决) ⑦调仓史 ⑧页脚实盘映射。
只读 derived 落盘 + 实时算当前信号(@st.cache_data 当天缓存)。

用法:uv run streamlit run app/faber_strategy.py
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from components import CATEGORICAL, INK, INK2, MUTED, base_layout

st.set_page_config(page_title="Faber 10月均线策略", layout="wide")

DERIVED = Path(__file__).resolve().parents[1] / "data" / "derived"
ASSET_CN = {"hs300": "沪深300", "spx": "标普500(折CNY)", "bond": "十年国债腿", "gold": "黄金(沪金)",
            "cash": "现金(3M 利率)"}
ETF_MAP = {"hs300": "510310", "spx": "513500(QDII,溢价≤3%)", "bond": "511260", "gold": "518880", "cash": "货基/逆回购"}


@st.cache_data(ttl=3600)
def _signals() -> pd.DataFrame:
    from strategy.baseline_signals import faber_signals
    sig, weights = faber_signals()
    return sig, weights


@st.cache_data(ttl=3600)
def _backtest(tag: str) -> pd.DataFrame | None:
    p = DERIVED / "backtests" / f"{tag}.parquet"
    return pd.read_parquet(p) if p.exists() else None


@st.cache_data(ttl=3600)
def _benchmarks() -> dict[str, pd.Series]:
    raw = DERIVED.parent / "raw"
    hs = pd.read_parquet(raw / "index_daily/index_000300.parquet").set_index("date")["close"].rename("沪深300")
    bond = pd.read_parquet(DERIVED / "aligned/bond_leg_spliced_511260.parquet").set_index("date")["close"].rename("债券腿")
    return {"hs": hs, "bond": bond}


def _status_block(sig: pd.DataFrame, weights: pd.DataFrame):
    """当前信号状态:距均线 / 当前权重 / 下次调仓。"""
    last = sig.iloc[-1]
    w = weights.loc[last["exec_date"]] if last["exec_date"] in weights.index else weights.iloc[-1]
    cols = st.columns(4)
    for i, k in enumerate(["hs300", "spx", "bond", "gold"]):
        dist = (last[f"{k}_close"] / last[f"{k}_sma"] - 1) * 100
        held = bool(last[f"{k}_above"])
        cols[i].metric(
            ASSET_CN[k],
            f"{dist:+.2f}%",
            "均线上 · 持有" if held else "均线下 · 现金",
            border=True,
        )
    held = [ASSET_CN[k] for k in ["hs300", "spx", "bond", "gold"] if last[f"{k}_above"]]
    # 下次调仓 = 当前自然月的最后交易日(由 calendar 推导,不硬编码)
    raw = DERIVED.parent / "raw"
    cal = pd.read_parquet(raw / "calendar.parquet")["date"]
    today = pd.Timestamp.today().normalize()
    nxt_month_end = cal[cal >= today]
    nxt_month_end = nxt_month_end.groupby(nxt_month_end.dt.to_period("M")).min().iloc[0] \
        if len(nxt_month_end) else today
    month_last = cal[cal <= nxt_month_end].iloc[-1]
    st.markdown(
        f"**当前组合**(信号日 {last['date']:%Y-%m-%d},执行 {last['exec_date']:%Y-%m-%d} 开盘):"
        + (" + ".join(held) + f" 等权(各 {100/len(held):.0f}%)" if held else "全部现金")
        + f" · 下次调仓:**{month_last:%Y-%m-%d} 月末信号 → 次月首个交易日开盘**")


def _nav_chart():
    idx_df, etf_df = _backtest("faber_index"), _backtest("faber_etf")
    if idx_df is None:
        st.info("先运行 `PYTHONPATH=src uv run python -m strategy.run_baselines`")
        return
    bench = _benchmarks()
    fig = go.Figure()
    d = idx_df.set_index("date")["nav"]
    fig.add_scatter(x=d.index, y=d.values, name="信号层(指数)", line=dict(color=INK, width=2.2))
    if etf_df is not None:
        e = etf_df.set_index("date")["nav"]
        # 归一到信号层同起点对照
        base = d[d.index >= e.index.min()].iloc[0]
        fig.add_scatter(x=e.index, y=e.values * base, name="执行层(ETF,2014 起)",
                        line=dict(color=CATEGORICAL[2], width=1.8))
    hs = bench["hs"]
    hs = hs[hs.index >= d.index.min()]
    fig.add_scatter(x=hs.index, y=(hs / hs.iloc[0]).values, name="沪深300 买入持有",
                    line=dict(color=CATEGORICAL[1], width=1.5))
    bd = bench["bond"]
    bd = bd[bd.index >= d.index.min()]
    fig.add_scatter(x=bd.index, y=(bd / bd.iloc[0]).values, name="债券腿",
                    line=dict(color=MUTED, width=1.2))
    base_layout(fig)
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, width="stretch")


def _dd_chart():
    idx_df = _backtest("faber_index")
    if idx_df is None:
        return
    d = idx_df.set_index("date")
    bench = _benchmarks()["hs"]
    hs = (bench / bench.cummax() - 1).reindex(d.index).ffill()
    fig = go.Figure()
    fig.add_scatter(x=d.index, y=d["drawdown"] * 100, name="策略回撤",
                    line=dict(color=INK, width=2.0), fill="tozeroy", fillcolor="rgba(11,11,11,0.08)")
    fig.add_scatter(x=hs.index, y=hs * 100, name="沪深300 回撤",
                    line=dict(color=CATEGORICAL[1], width=1.3), fill="tozeroy", fillcolor="rgba(235,104,52,0.08)")
    base_layout(fig, y_title="%")
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, width="stretch")


def _evidence_block():
    rows = [
        ("主检验(信号层 2008-11→今)", "年化 +8.64% · MDD −17.6% · 回撤削减 62% · 夏普 0.92", "✅ 通过"),
        ("敏感性(SMA 6–15 月)", "5/5 全域高原通过,回撤削减 59–64%,原版 10M 居中", "✅ 高原"),
        ("walk-forward(8 年训练滚动选参)", "样本外年化 +7.60% · MDD −11.8% · 削减 74%;选参 10 段全落 SMA 6–8", "✅ 通过"),
        ("执行层复测(ETF 2014-02→今)", "年化 +11.11% · MDD −17.5% · 夏普 1.11;两层 MDD 一致", "✅ 通过"),
        ("holdout(2025-08→2026-08,只看一次)", "年化 67.6% 达基准(线 70%)· 回撤深 0.8pp——牛市结构性折价", "❌ 实测未达"),
        ("终局裁决", "2026-08-26 用户验收通过(实测记录保留,建议 2027 新数据追加 holdout)", "✅ 验收通过"),
    ]
    st.table(pd.DataFrame(rows, columns=["检验", "结果摘要", "判"]))


def _trades_block():
    sig = pd.read_parquet(DERIVED / "signals/faber_monthly.parquet")
    t = sig.tail(24)[["date"]].copy()
    for k in ["hs300", "spx", "bond", "gold"]:
        t[ASSET_CN[k]] = sig.tail(24)[f"{k}_above"].map({True: "●", False: "—"})
    t["date"] = t["date"].dt.strftime("%Y-%m")
    t = t.set_index("date").rename(columns={"hs300": "沪深300", "spx": "标普", "bond": "国债", "gold": "黄金"})
    st.caption("近 24 个月信号(●=均线上持有,月末信号次月首个交易日开盘生效)")
    st.dataframe(t, width="stretch", height=460)


def main():
    st.header("Faber 10月均线策略")
    st.caption("每月末比较各资产收盘与 10 月简单均线:线上持有、线下转现金,通过者等权 · "
               "资产:沪深300/标普500(折CNY)/十年国债腿/黄金(沪金) · "
               "月频、次月首个交易日开盘调仓 · 原版参数(Faber 2007)· 唯一通过验收的基线(证据链见下)")

    sig, weights = _signals()
    _status_block(sig, weights)

    idx_df = _backtest("faber_index")
    if idx_df is not None:
        nav = idx_df.set_index("date")["nav"]
        c1, c2, c3, c4 = st.columns(4)
        yrs = len(nav) / 252
        ret = idx_df.set_index("date")["ret"]
        c1.metric("年化(信号层)", f"{nav.iloc[-1] ** (1 / yrs) - 1:+.2%}")
        c2.metric("最大回撤", f"{idx_df.set_index('date')['drawdown'].min():.1%}")
        c3.metric("夏普", f"{ret.mean() / ret.std() * 252 ** 0.5:.2f}")
        c4.metric("距 2015 峰值", f"{nav.iloc[-1] / nav.max() - 1:+.1%}")

    _nav_chart()
    _dd_chart()
    st.subheader("证据链(全部检验的完整记录)")
    _evidence_block()
    _trades_block()

    st.divider()
    st.caption("实盘映射:" + " / ".join(f"{ASSET_CN[k]}→{ETF_MAP[k]}" for k in ["hs300", "spx", "bond", "gold"])
               + " · 现金腿→货基/逆回购 · 复现:`PYTHONPATH=src uv run python -m strategy.run_baselines faber` · "
               "回测工作台(含敏感性/WF):`uv run streamlit run app/gem_backtest.py`")


main()
