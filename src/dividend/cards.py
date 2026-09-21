"""红利低波簇打分卡包装层（估值仪表盘 / 红利低波策略页的消费接口）。

把 score.py 的冻结打分包装成估值卡五件套可直接消费的结构。打分是 0-100
历史分位（低=便宜）而非 σ 方法（sigma.py）的估值z，本模块定义清晰分派
DividendCard，与 MetricResult 的字段映射关系如下——视觉与文案复用
app/components.py 与 DESIGN.md 五件套结构，颜色一律取 metrics.RATING_LEVELS：

| DividendCard 字段 | MetricResult 对应 | 语义说明 |
|---|---|---|
| name | name | 标的中文名（ETF 代码 + 指数口径） |
| current | current | score_pct×100（0-100 历史分位；非原始指标值） |
| unit | unit | "%"（历史分位） |
| sigma | sigma | score_z（打分z，expanding 口径）——**非** σ 方法估值z，仅作偏离度参考 |
| rating | rating | tier_from_pct 五档（低分位=便宜=低档，方向同估值卡"低=绿"） |
| color | color | RATING_LEVELS[rating]["color"]（五档状态色复用） |
| direction | direction | POSITIVE（分位高=贵，同 PE 卡） |
| window | window | "全历史"（各标的起点不同，见 INSTRUMENTS since） |
| series | series | score_pct×100 日频序列（DatetimeIndex） |
| stats | stats | SigmaStats（分位序列的均值/σ/±带，**仅展示用**，非 σ 方法口径） |
| desc | desc | 白话解释（含 P(1年>0) 与不可外推警示） |
| updated | updated | 数据截止日（YYYY-MM-DD） |

MetricResult 没有、打分专有的字段：p_pos_1y / state_n / state_degraded /
non_extrapolatable / weights（冻结权重留档）/ caliber（口径）。

页面只读消费本模块，不得改 score.py 的冻结权重与参数（AGENTS.md 纪律）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from metrics.contract import POSITIVE, RATING_LEVELS
from metrics.sigma import SigmaStats

from . import factors, score

# 五档分位边界（设计文档十二节第 1/2 条：分位低=便宜=绿；取对称五分位，
# 与五档卡的分布分位含义对齐）：<20 极低估 / 20-40 低估 / 40-60 公允 /
# 60-80 高估 / ≥80 极高估。操作建议映射的边界即 40 与 60。
TIER_BOUNDS = (20.0, 40.0, 60.0, 80.0)

# 分位档 → 操作建议（设计文档十二节第 2 条：机械纪律，不做主观加码）：
# 低档（极低估/低估）分批建仓、公允档持有、高档（高估/极高估）减仓/不追加。
ADVICE_BY_TIER = {1: "分批建仓", 2: "分批建仓", 3: "持有", 4: "减仓/不追加", 5: "减仓/不追加"}

PREMIUM_CAP = 3.0  # QDII 溢价买入门控 %（设计文档十二节第 3 条，同 AGENTS.md 信号-执行分离）

# 建议权重 %（设计文档十二节 / HANDOFF 一页纸"当前建议（进取型）"；
# 定位 = 信号观察非实盘指令；簇合计 30-35%）。
# 键为 ETF 代码（页面展示用），与 INSTRUMENTS 的 etf 字段对应。
SUGGESTED_WEIGHTS = {"563020": 11.4, "159307": 9.8, "515450": 8.1, "159545": 3.3}
CLUSTER_WEIGHT_RANGE = (30.0, 35.0)  # 簇合计建议区间 %

# 展示顺序：A 股三兄弟 → QDII
ORDER = ["H30269", "930955", "515450", "159545"]

INSTRUMENTS = {
    "H30269": {"etf": "563020", "label": "红利低波 563020",
               "index_name": "中证红利低波动 H30269", "since": "2015-01", "qdii": False},
    "930955": {"etf": "159307", "label": "红利低波100 159307",
               "index_name": "中证红利低波动100 930955", "since": "2015-01", "qdii": False},
    "515450": {"etf": "515450", "label": "红利低波50 515450",
               "index_name": "标普中国A股红利低波50（净值代理）", "since": "2020-01", "qdii": False},
    "159545": {"etf": "159545", "label": "恒生红利低波 159545",
               "index_name": "恒生港股通高股息低波动 HSHYLV（净值代理）", "since": "2024-03", "qdii": True},
}

_TIER_MEANING = {
    1: "远低于历史常态，显著便宜",
    2: "低于历史常态，偏便宜",
    3: "居于历史中游，不贵不便宜",
    4: "高于历史常态，偏贵",
    5: "远高于历史常态，显著贵",
}

CALIBER_LABELS = {"valuation": "纯估值（去动量，回答「贵贱」）",
                  "full": "含动量（回答「赢面」）"}


def tier_from_pct(pct: float) -> int:
    """打分分位(0-100) → 五档 rating（TIER_BOUNDS 边界左闭右开：pct<20→1 …）。"""
    for i, b in enumerate(TIER_BOUNDS):
        if pct < b:
            return i + 1
    return 5


def advice_for_tier(tier: int) -> str:
    """五档 → 机械操作建议（设计文档十二节第 2 条）。"""
    return ADVICE_BY_TIER[tier]


def advice_for_pct(pct: float) -> str:
    """打分分位 → 机械操作建议：分批建仓(<40) / 持有(40-60) / 减仓·不追加(≥60)。"""
    return ADVICE_BY_TIER[tier_from_pct(pct)]


def apply_premium_gate(advice: str, premium: float | None) -> str:
    """QDII 买入门控：买入建议叠加溢价 ≤3% 检查（设计文档十二节第 3 条）。

    premium=None（离线/净值缺失）时不阻断，但页面必须另行标注口径；
    门控只管买入侧（分批建仓），持有/减仓建议不受影响。
    """
    if advice == ADVICE_BY_TIER[1] and premium is not None and premium > PREMIUM_CAP:
        return "等待溢价回落"
    return advice


@dataclass
class DividendCard:
    """红利低波簇打分卡（字段 ↔ MetricResult 映射见模块 docstring）。"""

    code: str                       # 指数/代理代码（score.py INSTRUMENTS 键）
    name: str                       # 中文名
    current: float                  # 当前打分分位 0-100
    unit: str                       # "%"
    sigma: float                    # 打分z（MetricResult.sigma 槽位；非 σ 方法估值z）
    rating: int                     # 五档 1-5
    color: str                      # 五档状态色
    direction: str                  # positive（分位高=贵）
    window: str                     # "全历史"
    series: pd.Series               # 分位×100 日频（DatetimeIndex）
    stats: SigmaStats               # 展示用（±带=分位σ带，非 σ 方法口径）
    desc: str                       # 白话解释
    updated: str                    # 数据截止日
    p_pos_1y: float                 # P(1年收益>0) 频率概率
    state_n: int                    # 相似状态样本数
    non_extrapolatable: bool        # 概率不可外推标记（score.py 落在数据层）
    state_degraded: bool            # 相似状态退化标记
    weights: dict = field(default_factory=dict)  # 冻结权重留档
    caliber: str = "valuation"      # valuation / full


def _desc(code: str, row: pd.Series, caliber: str) -> str:
    """白话解释（DESIGN.md 第五节模板：是什么 + 在哪档 + 意味着什么）。"""
    meta = INSTRUMENTS[code]
    pct = row["score_pctile"] * 100
    tier = tier_from_pct(pct)
    label = RATING_LEVELS[tier]["label"]
    parts = [
        f"{meta['label']}（{meta['index_name']}）当前估值打分处于 {meta['since']} 以来 "
        f"{pct:.0f}% 历史分位，评级「{label}」——{_TIER_MEANING[tier]}。",
        f"相似估值状态下，历史 P(1年收益>0) = {row['P(fwd252>0)']:.0%}"
        f"（{CALIBER_LABELS[caliber]}；频率法，基于 {int(row['state_n'])} 个相似状态，"
        f"非模型预测）。打分 = expanding z × ≤2023 样本内 ICIR 冻结权重。",
    ]
    if row["non_extrapolatable"]:
        reasons = []
        if row["state_degraded"]:
            reasons.append("相似状态样本不足（已退化取末 500 行）")
        reasons.append("标的可用历史过短（<5 年）" if code == "159545" else "相似状态样本偏少（<60）")
        parts.append(f"⚠️ 概率不可外推（{'；'.join(reasons)}）——P(1年>0) 仅供参考，不构成概率承诺。")
    if code in ("515450", "159545"):
        parts.append("该标的无指数 PE 数据（净值代理），打分仅含股息率/ERP 口径因子。")
    return "\n\n".join(parts)


def compute_cards(caliber: str = "valuation") -> dict[str, DividendCard]:
    """四标的打分卡。caliber：valuation=纯估值（默认，回答「贵贱」）/
    full=含动量（回答「赢面」）。只读消费冻结打分，不落盘（AGENTS.md 规则 5）。"""
    if caliber not in CALIBER_LABELS:
        raise ValueError(f"未知口径: {caliber}")
    panels = factors.build_panels()
    fn = score.score_valuation_only if caliber == "valuation" else score.score_full
    scores, summary = fn(panels)
    cards: dict[str, DividendCard] = {}
    for code, row in summary.set_index("instrument").iterrows():
        s = (scores[code]["score_pct"] * 100).dropna()
        mean, sd = float(s.mean()), float(s.std())
        rating = tier_from_pct(row["score_pctile"] * 100)
        cards[code] = DividendCard(
            code=code,
            name=INSTRUMENTS[code]["label"],
            current=float(row["score_pctile"] * 100),
            unit="%",
            sigma=float(row["score_z"]),
            rating=rating,
            color=RATING_LEVELS[rating]["color"],
            direction=POSITIVE,
            window="全历史",
            series=s,
            stats=SigmaStats(
                mean=mean, sd=sd, n=len(s),
                start=f"{s.index[0]:%Y-%m}", end=f"{s.index[-1]:%Y-%m}",
                z_raw=float(row["score_z"]), val_z=float(row["score_z"]),
                lo2=max(0.0, mean - 2 * sd), lo1=max(0.0, mean - sd),
                hi1=min(100.0, mean + sd), hi2=min(100.0, mean + 2 * sd),
            ),
            desc=_desc(code, row, caliber),
            updated=f"{s.index[-1]:%Y-%m-%d}",
            p_pos_1y=float(row["P(fwd252>0)"]),
            state_n=int(row["state_n"]),
            non_extrapolatable=bool(row["non_extrapolatable"]),
            state_degraded=bool(row["state_degraded"]),
            weights=dict(row["weights"]),
            caliber=caliber,
        )
    return cards
