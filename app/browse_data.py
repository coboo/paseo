"""轻量数据浏览器：可视化查看 data/ 下所有 parquet 数据集。

启动方式（项目根目录）：
    uv run streamlit run app/browse_data.py --server.headless true

首页 = 数据集总览表（中文名/行数/区间/来源，按类别分组），点任意一行进入详情；
也可在侧栏按中文名直接挑选。仅只读，不写任何数据文件。
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# AppTest 等裸执行环境不会把脚本目录加进 sys.path（streamlit run 会）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from components import CATEGORICAL, base_layout

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"

# 数据集中文名登记：键 = 相对 data/ 的路径（不含扩展名）
# 新增数据集时在此补一行；未登记的回退显示文件名 + meta 备注
DATASET_NAMES = {
    # A 股指数日线
    "raw/index_daily/index_000300": "沪深300 指数日线",
    "raw/index_daily/index_000905": "中证500 指数日线",
    "raw/index_daily/index_000852": "中证1000 指数日线",
    "raw/index_daily/index_399006": "创业板指 指数日线",
    "raw/index_daily/index_H30269": "中证红利低波动 指数日线",
    "raw/index_daily/index_930955": "中证红利低波动100 指数日线",
    "raw/index_daily/index_931139": "中证消费50 指数日线",
    "raw/index_daily/index_H30533": "中证海外中国互联网50 指数日线",
    "raw/index_daily/spdiv50_nav_515450": "标普中国A股红利机会（515450 净值兜底）",
    # 海外指数 / 净值
    "raw/index_global/spx_inx": "标普500 指数（美元）",
    "raw/index_global/ndx_ndx": "纳斯达克100 指数（美元）",
    "raw/index_global/n225_n225": "日经225 指数（日元）",
    "raw/index_global/hshylv_nav_159545": "恒生红利低波（159545 净值兜底）",
    # ETF 前复权日线（执行层）
    "raw/etf_daily/etf_qfq_510310": "510310 沪深300ETF（前复权）",
    "raw/etf_daily/etf_qfq_510580": "510580 中证500ETF（前复权）",
    "raw/etf_daily/etf_qfq_159633": "159633 中证1000ETF（前复权）",
    "raw/etf_daily/etf_qfq_159915": "159915 创业板ETF（前复权）",
    "raw/etf_daily/etf_qfq_563020": "563020 红利低波ETF（前复权）",
    "raw/etf_daily/etf_qfq_513500": "513500 标普500ETF（前复权）",
    "raw/etf_daily/etf_qfq_513100": "513100 纳指ETF（前复权）",
    "raw/etf_daily/etf_qfq_513880": "513880 日经225ETF（前复权）",
    "raw/etf_daily/etf_qfq_518880": "518880 黄金ETF（前复权）",
    "raw/etf_daily/etf_qfq_159545": "159545 恒生红利低波ETF（前复权）",
    "raw/etf_daily/etf_qfq_511260": "511260 十年国债ETF（前复权）",
    "raw/etf_daily/etf_qfq_511360": "511360 短融ETF（前复权）",
    "raw/etf_daily/etf_qfq_515450": "515450 红利低波50ETF（前复权）",
    "raw/etf_daily/etf_qfq_159307": "159307 红利低波100ETF（前复权）",
    "raw/etf_daily/etf_qfq_515650": "515650 消费50ETF（前复权）",
    "raw/etf_daily/etf_qfq_513050": "513050 中概互联网ETF（前复权）",
    # QDII 净值（溢价过滤器数据源）
    "raw/etf_nav/nav_513500": "513500 标普500ETF 净值",
    "raw/etf_nav/nav_513100": "513100 纳指ETF 净值",
    "raw/etf_nav/nav_513880": "513880 日经225ETF 净值",
    "raw/etf_nav/nav_159545": "159545 恒生红利低波ETF 净值",
    "raw/etf_nav/nav_513050": "513050 中概互联网ETF 净值",
    # 估值
    "raw/valuation/pe_000300": "沪深300 PE（滚动市盈率）",
    "raw/valuation/pe_000905": "中证500 PE（滚动市盈率）",
    "raw/valuation/pb_000300": "沪深300 PB",
    "raw/valuation/pb_000905": "中证500 PB",
    "raw/valuation/dividend_000300": "沪深300 股息率（快照，逐日积累）",
    "raw/valuation/dividend_000905": "中证500 股息率（快照，逐日积累）",
    "raw/valuation/dividend_all_a": "全 A 股息率",
    # 利率 / 波动率 / 汇率 / 黄金 / 债券指数 / 日历
    "raw/rates/cn10y": "中国国债收益率曲线（3M–30Y 全期限）",
    "raw/qvix/qvix_50etf": "50ETF 波动率 QVIX",
    "raw/qvix/qvix_300etf": "300ETF 波动率 QVIX",
    "raw/fx/usdcny": "美元/人民币 汇率",
    "raw/fx/jpycny": "日元/人民币 汇率",
    "raw/fx/hkdcny": "港币/人民币 汇率",
    "raw/gold/au9999_sge": "上金所 AU9999 黄金现货",
    "raw/gold/au_main_sina": "沪金主力合约",
    "raw/bond_index/cbond_treasury_wealth_7_10y": "中债国债总财富指数（7-10Y）",
    "raw/calendar": "A股交易日历",
    # CMV 复刻新增（2026-09-09）
    "raw/margin/margin_total": "沪深两融合并余额（CMV 两融）",
    "raw/rates/credit_ts_aaa": "中债中短票 AAA 收益率曲线（3Y/10Y）",
    "raw/valuation/a_market_cap": "A股两市总市值（月度，亿元）",
    "raw/macro/gdp_quarterly": "GDP 季度累计值（亿元）",
    "raw/macro/epu_china": "中国 EPU 政策不确定性指数（月度）",
    "raw/macro/urban_unemployment": "全国城镇调查失业率（月度）",
    "raw/macro/pmi_official": "官方制造业 PMI（月度）",
    # derived
    "derived/aligned/bond_leg_spliced_511260": "债券腿拼接序列（财富指数→511260）",
}

# 类别目录的中文名
GROUP_NAMES = {
    "index_daily": "A股指数日线（信号层）",
    "index_global": "海外指数 / 净值（信号层）",
    "etf_daily": "ETF 前复权日线（执行层）",
    "etf_nav": "QDII 净值（溢价过滤器）",
    "valuation": "估值（PE / PB / 股息率）",
    "rates": "利率",
    "qvix": "波动率",
    "fx": "汇率",
    "gold": "黄金",
    "bond_index": "债券指数",
    "aligned": "派生-对齐面板",
}


st.set_page_config(page_title="数据浏览器", page_icon="🗃️", layout="wide")
st.title("📊 数据浏览器")


@st.cache_data
def list_datasets() -> list[Path]:
    """扫描 data/ 下全部 parquet 文件。"""
    return sorted(DATA_ROOT.rglob("*.parquet"))


@st.cache_data
def load_df(path: str) -> pd.DataFrame:
    return pd.read_parquet(path)


def load_meta(path: Path) -> dict:
    meta_path = path.with_suffix(".meta.json")
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {}


def cn_name(path: Path) -> str:
    """中文名：优先登记表，否则回退文件名。"""
    key = str(path.relative_to(DATA_ROOT).with_suffix(""))
    return DATASET_NAMES.get(key, path.stem)


def group_name(path: Path) -> str:
    rel = path.relative_to(DATA_ROOT)
    layer = "派生层 derived" if rel.parts[0] == "derived" else "原始层 raw"
    # 顶层文件（如 calendar）没有子目录
    sub = rel.parts[1] if len(rel.parts) > 2 else ""
    g = GROUP_NAMES.get(sub, sub)
    return f"{layer} / {g}" if g else layer


files = list_datasets()
if not files:
    st.warning("data/ 下没有找到 parquet 文件")
    st.stop()

by_rel = {str(p.relative_to(DATA_ROOT)): p for p in files}

# ---------------------------------------------------------------- 侧栏：数据更新
@st.cache_data
def latest_date() -> str:
    """数据最新日期：以沪深300 指数日线为准（calendar 等含未来日期，不能取全集最大值）。"""
    df = load_df(str(DATA_ROOT / "raw" / "index_daily" / "index_000300.parquet"))
    return str(df["date"].max())[:10]


st.sidebar.header("数据更新")
st.sidebar.metric("数据最新日期", latest_date())

# 更新锁:防并发(更新中刷新页面再点按钮会起第二个进程,parquet 追加竞争)
_UPDATE_LOCK = DATA_ROOT / ".update_lock"
_UPDATE_TIMEOUT_S = 900  # 42 数据集全量含接口重试的上限,防僵死


def _update_running() -> bool:
    """锁文件存在且持锁进程仍存活(锁记更新子进程 pid,子进程退出即自动失效)。"""
    if not _UPDATE_LOCK.exists():
        return False
    txt = _UPDATE_LOCK.read_text().strip()
    if txt == "starting":
        return True   # Popen 瞬间的占位
    try:
        pid = int(txt or 0)
        if pid <= 0:
            raise ValueError(pid)
        os.kill(pid, 0)   # 0 信号探活,进程不存在抛 ProcessLookupError
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        _UPDATE_LOCK.unlink(missing_ok=True)   # 持锁进程已亡,清陈旧锁
        return False


if st.sidebar.button("🔄 更新数据", width="stretch"):
    if _update_running():
        st.sidebar.error("已有一个更新进程在跑(可能是更新中刷新了页面)。它完成后会自动解锁,"
                         "稍等片刻再点;若确认没有更新在跑,可删除 data/.update_lock。")
        st.stop()
    project_root = DATA_ROOT.parent
    env = {**os.environ, "PYTHONPATH": "src"}   # 源码优先,防子进程跑旧安装版
    _UPDATE_LOCK.write_text("starting")         # 占位防 Popen 瞬间竞态
    try:
        with st.sidebar.status("正在更新数据…", expanded=True) as status:
            proc = subprocess.Popen(
                ["uv", "run", "--no-sync", "python", "-m", "data_module.update"],
                cwd=project_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, env=env,
            )
            _UPDATE_LOCK.write_text(str(proc.pid))   # 锁生命周期 = 更新子进程生命周期
            prog_box, log_box = st.empty(), st.empty()
            lines: list[str] = []
            n_done = n_ok = n_fail = 0
            current = ""
            t0 = time.time()
            timed_out = False
            while True:
                line = proc.stdout.readline()
                if not line:               # EOF = 进程结束
                    break
                lines.append(line)
                s = line.strip()
                if s.startswith(">>> ["):  # 新数据集开始
                    n_done += 1
                    m = re.search(r"\[(.+?)]", s)
                    current = m.group(1) if m else ""
                elif s.startswith("OK "):
                    n_ok += 1
                elif s.startswith("FAILED"):
                    n_fail += 1
                elapsed = int(time.time() - t0)
                prog_box.markdown(
                    f"**{n_done}** 个数据集已处理 · ✅ {n_ok} · ❌ {n_fail} · "
                    f"⏱ {elapsed // 60}:{elapsed % 60:02d} · 当前 `{current or '—'}`")
                log_box.code("".join(lines[-10:]), language=None)
                if time.time() - t0 > _UPDATE_TIMEOUT_S:
                    proc.kill()
                    timed_out = True
                    break
            proc.wait()

            summary = "".join(lines)
            if timed_out:
                status.update(label=f"⏱ 超过 {_UPDATE_TIMEOUT_S // 60} 分钟已终止——"
                                    f"成功部分已入库,再点一次只补失败项", state="error")
            elif proc.returncode == 0:
                status.update(label=f"✅ 更新完成({n_ok} 个数据集)", state="complete", expanded=False)
            elif n_ok > 0:
                # 部分失败(典型:东财间歇不可达,已有腾讯/新浪兜底链但偶尔全链失败)。
                # raw 只增不改 + 断点续传:成功部分已入库,重跑只补失败项
                status.update(label=f"⚠️ {n_fail} 个失败——其余 {n_ok} 个已入库,"
                                    f"再点一次只补失败项(常见于东财间歇不可达)",
                              state="error", expanded=True)
            else:
                status.update(label="❌ 全部失败,请查看日志(网络/代理?)", state="error", expanded=True)
    finally:
        _UPDATE_LOCK.unlink(missing_ok=True)
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()

# ---------------------------------------------------------------- 侧栏：选择数据集
st.sidebar.header("选择数据集")
mode = st.sidebar.radio("方式", ["📋 总览表（点行进入）", "🔽 直接挑选"], label_visibility="collapsed")

picked_rel = None
if mode == "🔽 直接挑选":
    labels = {f"{cn_name(p)}　[{p.relative_to(DATA_ROOT)}]": str(p.relative_to(DATA_ROOT)) for p in files}
    picked_rel = labels[st.sidebar.selectbox("数据集", labels.keys())]
else:
    # 总览表：一行一个数据集，点行进入详情
    rows = []
    for p in files:
        df = load_df(str(p))
        meta = load_meta(p)
        rows.append({
            "类别": group_name(p),
            "数据集": cn_name(p),
            "行数": len(df),
            "起始": str(df["date"].min())[:10] if "date" in df.columns else "-",
            "截止": str(df["date"].max())[:10] if "date" in df.columns else "-",
            "来源": meta.get("source_interface", "-"),
            "_rel": str(p.relative_to(DATA_ROOT)),
        })
    overview = pd.DataFrame(rows)
    event = st.dataframe(
        overview.drop(columns=["_rel"]),
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )
    sel = event.selection.rows
    if sel:
        picked_rel = overview.iloc[sel[0]]["_rel"]
        st.sidebar.info(f"已选：{cn_name(by_rel[picked_rel])}")

# ---------------------------------------------------------------- 详情
if not picked_rel:
    st.caption("👆 点击表中任意一行查看走势图与明细；侧栏可直接搜索挑选。")
    st.stop()

path = by_rel[picked_rel]
df = load_df(str(path))
meta = load_meta(path)

st.header(cn_name(path))
st.caption(f"文件：`data/{picked_rel}`")

cols = st.columns(4)
cols[0].metric("行数", len(df))
if "date" in df.columns:
    cols[1].metric("起始", str(df["date"].min())[:10])
    cols[2].metric("截止", str(df["date"].max())[:10])
cols[3].metric("列数", len(df.columns))

if meta:
    with st.expander("元数据（来源/复权/抓取日期）", expanded=False):
        st.json(meta)

# 日期范围过滤
if "date" in df.columns:
    dmin, dmax = df["date"].min().date(), df["date"].max().date()
    rng = st.sidebar.date_input("日期范围", (dmin, dmax), min_value=dmin, max_value=dmax)
    if len(rng) == 2:
        df = df[(df["date"] >= pd.Timestamp(rng[0])) & (df["date"] <= pd.Timestamp(rng[1]))]

# 绘图：数值列可选，默认 close / 第一个数值列
num_cols = [c for c in df.columns if c != "date" and pd.api.types.is_numeric_dtype(df[c])]
if num_cols and "date" in df.columns:
    default = num_cols.index("close") if "close" in num_cols else 0
    ycols = st.multiselect("绘图列", num_cols, default=[num_cols[default]])
    if ycols:
        # categorical 固定顺序取色，超过 8 序列不生成第 9 色（DESIGN.md 3.2）
        if len(ycols) > len(CATEGORICAL):
            st.warning(f"序列色只有 {len(CATEGORICAL)} 个，仅绘制前 {len(CATEGORICAL)} 列。")
            ycols = ycols[: len(CATEGORICAL)]
        fig = go.Figure()
        for i, c in enumerate(ycols):
            fig.add_trace(go.Scatter(
                x=df["date"], y=df[c], name=c, mode="lines",
                line=dict(color=CATEGORICAL[i], width=2),
                hovertemplate=f"%{{x|%Y-%m-%d}}：{c} %{{y:.4g}}<extra></extra>",
            ))
        # 单序列不加图例（标题即命名）；多序列图例置顶横排，文字用墨色
        fig = base_layout(fig, ycols[0] if len(ycols) == 1 else "")
        if len(ycols) > 1:
            fig.update_layout(
                showlegend=True,
                legend=dict(orientation="h", y=1.04, yanchor="bottom"),
                margin=dict(t=56),
            )
        fig.update_layout(height=450)
        st.plotly_chart(fig, width="stretch")

# 明细表：默认看尾部
st.subheader("明细数据")
n = st.slider("显示行数", 10, 500, 50)
order = st.radio("排序", ["最新在前", "最早在前"], horizontal=True)
table = df.tail(n) if order == "最新在前" else df.head(n)
st.dataframe(table, width="stretch")
