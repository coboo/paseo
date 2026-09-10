"""前端共用绘图组件与色彩常量（DESIGN.md 第三节/第七节的代码化）。

全部页面（Streamlit + Plotly）取色与图面规格的唯一来源，页面内禁止
重写这些常量（风格漂移视为 bug，见 DESIGN.md 第八节）。
"""
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
