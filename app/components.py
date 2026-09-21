"""前端共用绘图组件与色彩常量（DESIGN.md 第三节/第七节的代码化）。

全部页面（Streamlit + Plotly）取色与图面规格的唯一来源，页面内禁止
重写这些常量（风格漂移视为 bug，见 DESIGN.md 第八节）。
"""
import pandas as pd
import plotly.graph_objects as go

from metrics import RATING_LEVELS

# ── 图面 chrome（DESIGN.md 3.3）──
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SURFACE = "#fcfcfb"

# ── 数据序列色（DESIGN.md 3.2 / dataviz categorical 固定顺序，light 模式）──
CATEGORICAL = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
]
BLUE = CATEGORICAL[0]

# ── 行情监控页涨跌色（DESIGN.md 行情页限定豁免：红涨绿跌，仅限该页）──
MKT_UP, MKT_DOWN = "#d03b3b", "#0ca30c"

# ── 极值区 wash（DESIGN.md 3.4：大面积只准 8% 透明度）──
GREEN_WASH = "rgba(12,163,12,0.08)"   # 极便宜/低估侧
RED_WASH = "rgba(208,59,59,0.08)"     # 极贵/高估侧

# ── 五档呈现（DESIGN.md 3.1 表的代码化）──
# 档 2 = good 绿 @50%（叠页面底色，与档 1 区分）；其余档全值。
_TIER_ALPHA = {1: 1.0, 2: 0.5, 3: 1.0, 4: 1.0, 5: 1.0}
# 浅底（50% 绿 / 黄 / 橙）上白字对比度 1.8–2.7:1 不可读 → 墨字；全绿/红底用白字。
_TIER_TEXT_INK = {1: False, 2: True, 3: True, 4: True, 5: False}


def hex_a(hex_color: str, alpha: float) -> str:
    """#rrggbb → rgba()。"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def tier_fill(rating: int) -> str:
    """档位呈现色：RATING_LEVELS 语义色按 3.1 表做透明度处理。"""
    return hex_a(RATING_LEVELS[rating]["color"], _TIER_ALPHA[rating])


def tier_text(rating: int) -> str:
    """档位色块上的文字色（墨/白，见 3.1 表"色块上文字"列）。"""
    return INK if _TIER_TEXT_INK[rating] else "#ffffff"


def base_layout(fig: go.Figure, y_title: str = "") -> go.Figure:
    """通用图面：hairline 实线网格、muted 轴墨、白净面板、x unified hover。

    单序列不加图例（标题即命名）——多序列页面自行 update_layout(showlegend=True)。
    """
    fig.update_layout(
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=INK2, size=13),
        margin=dict(l=10, r=10, t=40, b=10),
        hovermode="x unified",
        xaxis=dict(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED)),
        yaxis=dict(title=y_title, gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED)),
        showlegend=False,
    )
    return fig


# ── 五件套共享模板（2026-09-21 由估值仪表盘页上移；DESIGN.md 第七节）──


def hero_value(current: float, unit: str, name: str, fmt: str = "{:+.2f}") -> str:
    """五件套 1：当前值大字 HTML（3.2rem 系统字重 700 + 单位小字 + 命名行）。"""
    return (
        f'<div style="font-size:3.2rem;font-weight:700;color:{INK};line-height:1">'
        f"{fmt.format(current)}<span style='font-size:1.1rem;color:{MUTED};font-weight:400'>"
        f" {unit}</span></div>"
        f'<div style="color:{MUTED};margin-top:4px">当前值 · {name}</div>'
    )


def rating_badge(rating: int, sub: str) -> str:
    """五件套 2：评级徽章 HTML（档名大字 + 副文案，如「+1.23σ 偏离历史均值」/
    「打分z +0.04（expanding 口径）」）。色块呈现走 tier_fill/tier_text。"""
    return (
        f'<div style="background:{tier_fill(rating)};color:{tier_text(rating)};'
        f'border-radius:10px;padding:14px 20px;text-align:center;margin-top:6px">'
        f'<div style="font-size:1.6rem;font-weight:700">{RATING_LEVELS[rating]["label"]}</div>'
        f'<div style="font-size:0.95rem;opacity:.92">{sub}</div>'
        f"</div>"
    )


def tier_bar(rating: int, ranges: list[str] | None = None) -> str:
    """五件套 3：五档红绿灯色条 HTML——每档范围小字 + 色块 + 档名，当前档加粗描边。

    色块呈现色与文字墨/白一律走 tier_fill/tier_text（DESIGN.md 3.1 表）。
    ranges 缺省 σ 口径（"≤ −2σ"…）；红利低波簇打分卡传分位档（"< 20%"…，
    边界与 src/dividend/cards.py TIER_BOUNDS 一致）。
    """
    labels = ranges or ["≤ −2σ", "−2σ ~ −1σ", "±1σ", "+1σ ~ +2σ", "≥ +2σ"]
    cells = []
    for r, rng in zip(range(1, 6), labels):
        active = r == rating
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


def fig_pct_bands(series: pd.Series, title: str, lo: float = 20.0, hi: float = 80.0,
                  y_title: str = "%") -> go.Figure:
    """分位序列 + 五档色带图（红利低波簇打分卡主图，_fig_erp 的分位版）。

    阈值线点线 muted（阈值语义）；<lo 涂 GREEN_WASH（便宜侧）、>hi 涂 RED_WASH
    （贵侧），8% 透明度（DESIGN.md 3.4）；y 轴锁 0-100。
    """
    s = series.dropna()
    fig = go.Figure()
    fig.add_hrect(y0=0, y1=lo, fillcolor=GREEN_WASH, line_width=0,
                  annotation_text=f"便宜区 <{lo:.0f}%", annotation_font=dict(color=MUTED, size=11))
    fig.add_hrect(y0=hi, y1=100, fillcolor=RED_WASH, line_width=0,
                  annotation_text=f"贵区 >{hi:.0f}%", annotation_font=dict(color=MUTED, size=11))
    for y in (20, 40, 60, 80):
        fig.add_hline(y=y, line=dict(color=MUTED, width=1, dash="dot"),
                      annotation_text=f"{y}%", annotation_font=dict(color=MUTED, size=10),
                      annotation_position="bottom right")
    fig.add_trace(go.Scatter(
        x=s.index, y=s.values, name="打分分位", mode="lines",
        line=dict(color=BLUE, width=2),
        hovertemplate="%{x|%Y-%m-%d}：分位 %{y:.0f}%<extra></extra>",
    ))
    fig = base_layout(fig, y_title)
    fig.update_layout(title=title, yaxis=dict(range=[0, 100], gridcolor=GRID,
                                              zeroline=False, tickfont=dict(color=MUTED)))
    return fig
