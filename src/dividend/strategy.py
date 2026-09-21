"""红利低波簇打分轮动规则引擎（设计文档十三节「基线 5」，纯函数）。

规则（月度，冻结）：
1. 信号 = 纯估值口径打分分位（compute_cards("valuation").series，0-100，低=便宜），
   月末锚点取当月最后可用分位，次一交易日执行（成交约定在 backtest.py）；
2. 档位 → 目标权重：分位 < enter → 全配（100% × 建议权重）；enter ~ exit → 半配（50%）；
   ≥ exit → 零配。建议权重 = cards.SUGGESTED_WEIGHTS（563020=11.4% / 159307=9.8% /
   515450=8.1% / 159545=3.3%，HANDOFF 冻结）；
3. 迟滞：升档（加仓）要求越界 + hyst pp（如 half→full 需 pct < enter − hyst）；
   降档越界即触发。跨两级升档（zero→full）按 graduated 处理：满迟滞进 full，
   只越过 exit 界进 half，否则维持；
4. 簇总仓位上限 32.6%（CLUSTER_CAP），超出按比例缩；
5. 起步全零（从现金开始）；无分位数据的标的维持零配。

本模块只做"分位序列 → 月末锚点目标权重"，不碰价格、不碰成交，可独立测试。
"""
from __future__ import annotations

import pandas as pd

from .cards import INSTRUMENTS, SUGGESTED_WEIGHTS

CODES = list(INSTRUMENTS)  # ["H30269", "930955", "515450", "159545"]

CLUSTER_CAP = 0.326  # 簇总仓位上限（设计文档十三节第 3 条，32.6%）

# 默认参数（展示层建议映射 40/60，迟滞 2pp 为网格默认值；WF 网格见 walkforward.py）
DEFAULT_ENTER = 40.0
DEFAULT_EXIT = 60.0
DEFAULT_HYST = 2.0

GEARS = ("zero", "half", "full")
GEAR_FRACTION = {"zero": 0.0, "half": 0.5, "full": 1.0}
_GEAR_ORDER = {"zero": 0, "half": 1, "full": 2}

# 建议权重（小数）：键 = 信号层资产键（INSTRUMENTS 键），值 = 建议权重 × 100%
DEFAULT_WEIGHTS = {code: SUGGESTED_WEIGHTS[INSTRUMENTS[code]["etf"]] / 100.0
                   for code in CODES}


def raw_gear(pct: float, enter: float, exit: float) -> str:
    """分位 → 档位（无迟滞）：pct < enter → full；enter ~ exit → half；≥ exit → zero。"""
    if pct >= exit:
        return "zero"
    if pct >= enter:
        return "half"
    return "full"


def next_gear(current: str, pct: float, enter: float, exit: float,
              hyst: float = 0.0) -> str:
    """带迟滞的档位状态机（设计文档十三节第 2 条）。

    - 降档（zero/half，即减仓）：越界即触发，无迟滞；
    - 升档（half/full，即加仓）：需越界 + 迟滞 pp——
      half→full 需 pct < enter − hyst，zero→half 需 pct < exit − hyst；
    - 跨两级 zero→full：满迟滞（pct < enter − hyst）直接 full，
      只越过 exit 界（pct < exit − hyst）进 half，否则维持 zero（graduated 升档）。
    """
    target = raw_gear(pct, enter, exit)
    if _GEAR_ORDER[target] < _GEAR_ORDER[current]:
        return target  # 降档即触发
    if _GEAR_ORDER[target] == _GEAR_ORDER[current]:
        return current
    # 升档：越界 + 迟滞
    if target == "full":
        if pct < enter - hyst:
            return "full"
        if _GEAR_ORDER[current] < 1 and pct < exit - hyst:
            return "half"  # graduated：先半配
        return current
    # target == "half"（zero→half）：越过 exit 界 + 迟滞
    return "half" if pct < exit - hyst else current


def infer_anchors(pct_by_code: dict[str, pd.Series]) -> pd.DatetimeIndex:
    """从分位序列索引推导月末锚点（每月最后一个有数据的交易日）。

    显式传入 anchors 的场景（回测/WF，用 A 股日历）不走这里；
    此函数供纯函数测试与轻量调用使用。
    """
    idx = pct_by_code[CODES[0]].index
    for s in pct_by_code.values():
        idx = idx.union(s.index)
    anchors = idx.to_series().groupby(idx.to_period("M")).max()
    return pd.DatetimeIndex(sorted(anchors.values))


def compute_target_weights(pct_by_code: dict[str, pd.Series],
                           enter: float = DEFAULT_ENTER,
                           exit: float = DEFAULT_EXIT,
                           hyst: float = DEFAULT_HYST,
                           weights: dict[str, float] | None = None,
                           cap: float = CLUSTER_CAP,
                           anchors: pd.DatetimeIndex | None = None,
                           ) -> pd.DataFrame:
    """分位序列 → 逐月目标权重（索引=月末锚点，列=四标的，值为 0-1 小数）。

    - 每标的逐锚点演化档位状态机（初始 zero，路径只向前依赖，无前视）；
    - 无分位数据的标的（历史未开始）维持零配；
    - 簇和 > cap 时等比例缩。
    """
    if enter > exit:
        raise ValueError(f"enter 必须 ≤ exit: enter={enter} exit={exit}")
    weights = DEFAULT_WEIGHTS if weights is None else weights
    anchors = infer_anchors(pct_by_code) if anchors is None else anchors
    data_end = min(s.index.max() for s in pct_by_code.values())
    anchors = anchors[anchors <= data_end]

    state = {code: "zero" for code in CODES}
    rows = []
    for a in anchors:
        row = {}
        for code in CODES:
            s = pct_by_code[code]
            past = s.loc[:a]
            if len(past) == 0:
                w = 0.0  # 无数据维持零配
            else:
                state[code] = next_gear(state[code], float(past.iloc[-1]),
                                        enter, exit, hyst)
                w = GEAR_FRACTION[state[code]] * weights[code]
            row[code] = w
        total = sum(row.values())
        if total > cap:
            scale = cap / total
            row = {k: v * scale for k, v in row.items()}
        rows.append(row)
    out = pd.DataFrame(rows, index=pd.DatetimeIndex(anchors))
    return out[CODES]
